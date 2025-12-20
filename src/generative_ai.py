from __future__ import annotations
import os
import time
import argparse
import logging
import re
import unicodedata
import pandas as pd
import google.generativeai as genai
from logging import getLogger
from dotenv import load_dotenv

log = getLogger(__name__)
_RETRY_IN_RE = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


def configure_gemini_api():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.error("Biến môi trường GEMINI_API_KEY chưa được thiết lập. Không thể sử dụng Gemini.")
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        log.error(f"Lỗi khi cấu hình Gemini API: {e}")
        return False


def _normalize_header(text: str) -> str:
    if text is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(text))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = txt.lower()
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def _resolve_column(df: pd.DataFrame, desired: str, aliases: list[str] | None = None) -> str | None:
    aliases = aliases or []
    norm_to_original: dict[str, str] = {}
    for col in df.columns:
        norm = _normalize_header(col)
        if norm and norm not in norm_to_original:
            norm_to_original[norm] = col

    candidates = [_normalize_header(desired)]
    candidates.extend(_normalize_header(a) for a in aliases)
    for c in candidates:
        if c in norm_to_original:
            return norm_to_original[c]
    return None


def generate_content_from_excel(
    file_path: str,
    keyword_col: str = "Anchor",
    content_col: str = "Nội Dung",
    website_col: str = "Website",
    only_if_empty: bool = True,
):
    """
    Đọc file Excel, dùng cột `keyword_col` (mặc định: Anchor) để tạo nội dung bằng Gemini
    và cập nhật lại cột `content_col` (mặc định: Nội Dung).
    """
    if not os.path.exists(file_path):
        log.error(f"File không tồn tại: {file_path}")
        return -1

    if not configure_gemini_api():
        return -1

    log.info(f"Đang đọc file Excel: {file_path}")
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        log.error(f"Không thể đọc file Excel: {e}")
        return -1

    keyword_col_actual = _resolve_column(df, keyword_col, aliases=["keyword", "anchor"])
    if not keyword_col_actual:
        log.error(f"Không tìm thấy cột '{keyword_col}' trong file Excel. Columns={list(df.columns)}")
        return -1

    content_col_actual = _resolve_column(
        df,
        content_col,
        aliases=[
            "noi dung",
            "noi_dung",
            "content",
            "comment",
            "noi dung comment",
            "noi dung binh luan",
        ],
    )
    if not content_col_actual:
        log.error(f"Không tìm thấy cột '{content_col}' trong file Excel. Columns={list(df.columns)}")
        return -1

    website_col_actual: str | None = None
    if website_col:
        website_col_actual = _resolve_column(df, website_col, aliases=["site", "web", "website url"])
        if not website_col_actual:
            log.warning(f"Không tìm thấy cột '{website_col}' trong file Excel. Sẽ tạo content không kèm website.")

    # 1. Thu thập các keywords và chỉ số dòng tương ứng
    tasks = []
    for index, row in df.iterrows():
        keyword_val = row.get(keyword_col_actual)
        existing = row.get(content_col_actual)
        if only_if_empty and existing and not pd.isna(existing) and str(existing).strip():
            continue
        # Bỏ qua các giá trị rỗng hoặc NaN (Not a Number) từ Excel
        if keyword_val and not pd.isna(keyword_val):
            keyword = str(keyword_val).strip()
            website = ""
            if website_col_actual:
                website_val = row.get(website_col_actual)
                if website_val and not pd.isna(website_val):
                    website = str(website_val).strip()
            tasks.append({"index": index, "keyword": keyword, "website": website})

    if not tasks:
        log.warning("Không có keyword nào hợp lệ để tạo nội dung.")
        return 0

    log.info(f"Tìm thấy {len(tasks)} dòng cần tạo nội dung. Bắt đầu tạo nội dung bằng Gemini...")

    def _save_atomic() -> None:
        tmp_path = f"{file_path}.tmp"
        df.to_excel(tmp_path, index=False, engine="openpyxl")
        os.replace(tmp_path, file_path)

    # 2. Gọi Gemini API để tạo nội dung cho từng keyword
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    model = genai.GenerativeModel(model_name)
    request_count = 0
    try:
        rpm = int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "10"))
    except ValueError:
        rpm = 10
    rpm = max(1, rpm)
    min_delay = float(os.getenv("GEMINI_MIN_DELAY_SEC", str(60.0 / rpm)))
    min_delay = max(0.0, min_delay)
    try:
        flush_every = int(os.getenv("GEMINI_FLUSH_EVERY", "1"))
    except ValueError:
        flush_every = 1
    flush_every = max(1, flush_every)
    updated = 0

    for task in tasks:
        keyword = task["keyword"]
        website = task.get("website") or ""
        prompt_tpl = os.getenv(
            "GEMINI_PROMPT_TEMPLATE",
            "Write a natural blog comment (20-35 words). "
            "Include this exact phrase: \"{anchor}\". "
            "Do not be spammy. No emojis. ",
        )
        prompt = prompt_tpl.format(anchor=keyword, website=website)
        generated_content = ""
        for attempt in range(1, 4):
            try:
                response = model.generate_content(prompt)
                generated_content = (getattr(response, "text", "") or "").strip()
                request_count += 1
                break
            except Exception as e:
                msg = str(e)
                log.error(f"Lỗi khi tạo nội dung cho keyword '{keyword}' (attempt {attempt}/3): {msg}")
                m = _RETRY_IN_RE.search(msg)
                if m:
                    try:
                        delay = float(m.group(1)) + 0.5
                    except ValueError:
                        delay = 5.0
                else:
                    delay = 5.0
                if attempt >= 3:
                    log.warning(f"Bỏ qua keyword '{keyword}' sau {attempt} lần lỗi.")
                    break
                log.info(f"Tạm nghỉ {delay:.1f} giây rồi thử lại keyword này...")
                time.sleep(delay)

        if not generated_content:
            continue

        df.loc[task["index"], content_col_actual] = generated_content
        updated += 1
        log.info(f"Đã tạo nội dung cho keyword: '{keyword}'")
        if updated % flush_every == 0:
            _save_atomic()
            log.info(f"Đã lưu tạm {file_path} (updated={updated})")
        if min_delay:
            time.sleep(min_delay)

    # Final flush (if needed)
    if updated % flush_every != 0:
        _save_atomic()
    log.info(f"Hoàn tất. Đã cập nhật {updated} dòng vào: {file_path}")
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate comment content via Gemini into an Excel file.")
    ap.add_argument("--input", default=os.getenv("INPUT_XLSX", "data/comments.xlsx"))
    ap.add_argument("--anchor-col", default="Anchor")
    ap.add_argument("--website-col", default="Website")
    ap.add_argument("--content-col", default="Nội Dung")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing content cells")
    ap.add_argument(
        "--flush-every",
        type=int,
        default=int(os.getenv("GEMINI_FLUSH_EVERY", "1")),
        help="Save back to Excel after every N generated rows (default: env GEMINI_FLUSH_EVERY or 1)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    os.environ["GEMINI_FLUSH_EVERY"] = str(max(1, int(args.flush_every)))
    updated = generate_content_from_excel(
        file_path=args.input,
        keyword_col=args.anchor_col,
        website_col=args.website_col,
        content_col=args.content_col,
        only_if_empty=not args.overwrite,
    )
    return 0 if updated >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
