from __future__ import annotations
import os
import time
import argparse
import logging
import pandas as pd
import google.generativeai as genai
from logging import getLogger
from dotenv import load_dotenv

log = getLogger(__name__)


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
        return

    if not configure_gemini_api():
        return

    log.info(f"Đang đọc file Excel: {file_path}")
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        log.error(f"Không thể đọc file Excel: {e}")
        return

    if keyword_col not in df.columns:
        log.error(f"Không tìm thấy cột '{keyword_col}' trong file Excel.")
        return
    if content_col not in df.columns:
        log.error(f"Không tìm thấy cột '{content_col}' trong file Excel.")
        return
    if website_col and website_col not in df.columns:
        log.warning(f"Không tìm thấy cột '{website_col}' trong file Excel. Sẽ tạo content không kèm website.")

    # 1. Thu thập các keywords và chỉ số dòng tương ứng
    tasks = []
    for index, row in df.iterrows():
        keyword_val = row.get(keyword_col)
        existing = row.get(content_col)
        if only_if_empty and existing and not pd.isna(existing) and str(existing).strip():
            continue
        # Bỏ qua các giá trị rỗng hoặc NaN (Not a Number) từ Excel
        if keyword_val and not pd.isna(keyword_val):
            keyword = str(keyword_val).strip()
            website = ""
            if website_col and website_col in df.columns:
                website_val = row.get(website_col)
                if website_val and not pd.isna(website_val):
                    website = str(website_val).strip()
            tasks.append({"index": index, "keyword": keyword, "website": website})

    if not tasks:
        log.warning("Không có keyword nào hợp lệ để tạo nội dung.")
        return

    log.info(f"Tìm thấy {len(tasks)} dòng cần tạo nội dung. Bắt đầu tạo nội dung bằng Gemini...")

    # 2. Gọi Gemini API để tạo nội dung cho từng keyword
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    model = genai.GenerativeModel(model_name)
    results_to_update = []
    request_count = 0

    for task in tasks:
        # Giới hạn tốc độ: nghỉ 1 phút sau mỗi 15 request
        if request_count > 0 and request_count % 15 == 0:
            log.info("Đã đạt giới hạn 15 requests. Tạm nghỉ 60 giây...")
            time.sleep(60)
            log.info("Tiếp tục tạo nội dung...")

        keyword = task["keyword"]
        website = task.get("website") or ""
        prompt_tpl = os.getenv(
            "GEMINI_PROMPT_TEMPLATE",
            "Write a natural blog comment (20-35 words). "
            "Include this exact phrase: \"{anchor}\". "
            "Do not be spammy. No emojis. ",
        )
        prompt = prompt_tpl.format(anchor=keyword, website=website)
        try:
            response = model.generate_content(prompt)
            generated_content = response.text.strip()
            results_to_update.append({"index": task["index"], "content": generated_content})
            request_count += 1
            log.info(f"Đã tạo nội dung cho keyword: '{keyword}'")
        except Exception as e:
            log.error(f"Lỗi khi tạo nội dung cho keyword '{keyword}': {e}")
            log.info("Tạm nghỉ 5 giây trước khi thử lại keyword tiếp theo...")
            time.sleep(5)

    # 3. Cập nhật lại nội dung vào DataFrame
    if results_to_update:
        log.info(f"Đang cập nhật {len(results_to_update)} dòng vào file Excel...")
        for result in results_to_update:
            df.loc[result["index"], content_col] = result["content"]

        # 4. Lưu lại file Excel
        df.to_excel(file_path, index=False, engine="openpyxl")
        log.info(f"Đã cập nhật và lưu file thành công: {file_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate comment content via Gemini into an Excel file.")
    ap.add_argument("--input", default=os.getenv("INPUT_XLSX", "data/comments.xlsx"))
    ap.add_argument("--anchor-col", default="Anchor")
    ap.add_argument("--website-col", default="Website")
    ap.add_argument("--content-col", default="Nội Dung")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing content cells")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    generate_content_from_excel(
        file_path=args.input,
        keyword_col=args.anchor_col,
        website_col=args.website_col,
        content_col=args.content_col,
        only_if_empty=not args.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
