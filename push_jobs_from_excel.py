# push_jobs_from_excel.py
from __future__ import annotations
import os
import re
import argparse
import logging
import unicodedata
import pandas as pd

REQUIRED_COLUMNS = ["URL", "Anchor", "Website", "Nội Dung", "Name", "Email"]
COLUMN_ALIASES = {
    "URL": ["link", "posturl"],
    "Anchor": ["anchor text", "anchor_text"],
    "Website": ["web", "site", "website url"],
    "Nội Dung": ["content", "comment", "noi dung", "noi_dung"],
    "Name": ["author", "full name"],
    "Email": ["mail", "contact email"],
}
RESULT_COLUMNS = ["url", "status", "reason", "comment_link", "duration_sec", "language", "attempts"]

# Đọc Excel (đảm bảo tồn tại)
def _read_df(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không thấy file: {path}")
    return pd.read_excel(path, engine="openpyxl").fillna("")


def _normalize_header(text: str) -> str:
    if text is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(text))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = txt.lower()
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def _standardize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    norm_to_original: dict[str, str] = {}
    for col in df.columns:
        norm = _normalize_header(col)
        if norm and norm not in norm_to_original:
            norm_to_original[norm] = col

    missing: list[str] = []
    rename_map: dict[str, str] = {}

    for display in REQUIRED_COLUMNS:
        candidates = [_normalize_header(display)]
        aliases = COLUMN_ALIASES.get(display, [])
        candidates.extend(_normalize_header(alias) for alias in aliases)

        matched_col = next((norm_to_original[c] for c in candidates if c in norm_to_original), None)
        if matched_col:
            rename_map[matched_col] = display
        else:
            missing.append(display)

    if missing:
        return None, missing

    if rename_map:
        df = df.rename(columns=rename_map)

    return df, []

def _sync_one(job: dict) -> dict:
    # Chạy trực tiếp không cần Celery (để test ra file out ngay)
    from src.worker_lib import run_one_link
    return run_one_link(job)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/comments.xlsx", help="Đường dẫn file Excel input")
    ap.add_argument("--output", default="data/comments_out.xlsx", help="Đường dẫn file Excel output")
    ap.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Số dòng tối đa để đẩy (0 hoặc giá trị âm = không giới hạn)",
    )
    ap.add_argument("--sync-one", action="store_true", help="Chạy 1 dòng đầu không cần Celery")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("push_jobs.log", encoding="utf-8"), logging.StreamHandler()],
    )

    # Đọc input
    try:
        df = _read_df(args.input)
    except Exception as e:
        logging.error(f"Không thể đọc Excel: {e}")
        pd.DataFrame(columns=RESULT_COLUMNS).to_excel(args.output, index=False)
        return

    # Bắt buộc header (chấp nhận alias, không phân biệt hoa thường/dấu)
    df, miss = _standardize_columns(df)
    if miss:
        logging.error(f"Thiếu cột {miss}. Yêu cầu header: {REQUIRED_COLUMNS}")
        pd.DataFrame(columns=RESULT_COLUMNS).to_excel(args.output, index=False)
        return

    # Tạo jobs
    jobs=[]
    max_jobs = args.limit if args.limit and args.limit > 0 else None
    for i, row in df.iterrows():
        if max_jobs is not None and len(jobs) >= max_jobs:
            break
        url = str(row["URL"]).strip()
        if not url:
            logging.warning(f"Dòng {i+2} URL trống → bỏ qua")
            continue
        jobs.append({
            "url": url,
            "anchor": str(row["Anchor"]).strip(),
            "website": str(row["Website"]).strip(),
            "content": str(row["Nội Dung"]).strip(),
            "name": str(row["Name"]).strip() or "Guest",
            "email": str(row["Email"]).strip(),
        })

    if not jobs:
        logging.warning("Không có job hợp lệ.")
        pd.DataFrame(columns=RESULT_COLUMNS).to_excel(args.output, index=False)
        return

    # Test nhanh 1 dòng (không Celery)
    if args.sync_one:
        logging.info("[SYNC-ONE] chạy 1 job không Celery để kiểm tra end-to-end")
        res = _sync_one(jobs[0])
        pd.DataFrame([res]).to_excel(args.output, index=False)
        logging.info(f"Đã ghi {args.output}")
        return

    # Đẩy qua Celery
    try:
        from src.tasks import run_comment
    except Exception as e:
        logging.error(f"Import task lỗi: {e}")
        pd.DataFrame(columns=RESULT_COLUMNS).to_excel(args.output, index=False)
        return

    tasks=[]
    for j in jobs:
        try:
            ar = run_comment.delay(j)
            tasks.append((j, ar))
            logging.info(f"Đã gửi task cho URL: {j['url']}")
        except Exception as e:
            logging.error(f"Gửi task lỗi {j['url']}: {e}")

    logging.info("Đang chờ kết quả từ các task...")
    results=[]
    for j, ar in tasks:
        try:
            out = ar.get(timeout=240)
        except Exception as e:
            out = {"url": j["url"], "status":"FAILED", "reason":f"No result/timeout: {e}", "comment_link":"", "duration_sec":0.0}
        results.append(out)

    if not results:
        results=[{"url":"", "status":"FAILED", "reason":"No tasks executed", "comment_link":"", "duration_sec":0.0, "language":"unknown", "attempts":0}]
    pd.DataFrame(results, columns=RESULT_COLUMNS).to_excel(args.output, index=False)
    logging.info(f"Đã ghi {args.output} ({len(results)} dòng).")

if __name__ == "__main__":
    main()
