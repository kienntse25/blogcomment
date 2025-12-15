# push_jobs_from_excel.py
from __future__ import annotations
import os
import re
import argparse
import logging
import unicodedata
import time
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

def _default_input_path() -> str:
    env_path = (os.getenv("INPUT_XLSX") or "").strip()
    if env_path:
        return env_path
    if os.path.exists("data/comments.xlsx"):
        return "data/comments.xlsx"
    if os.path.exists("data/comments.template.xlsx"):
        return "data/comments.template.xlsx"
    return "data/comments.xlsx"

def _default_output_path() -> str:
    env_path = (os.getenv("OUTPUT_XLSX") or "").strip()
    return env_path or "data/comments_out.xlsx"

def _default_timeouts_output_path(output_path: str) -> str:
    # Derive a sibling file name, e.g. comments_out.xlsx -> comments_timeouts.xlsx
    base = os.path.basename(output_path)
    if base.lower().endswith(".xlsx"):
        base = base[:-5]
    dirname = os.path.dirname(output_path) or "."
    return os.path.join(dirname, f"{base}_timeouts.xlsx")


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
    ap.add_argument("--input", default=_default_input_path(), help="Đường dẫn file Excel input")
    ap.add_argument("--output", default=_default_output_path(), help="Đường dẫn file Excel output")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Số dòng tối đa để đẩy (0 hoặc giá trị âm = không giới hạn)",
    )
    ap.add_argument(
        "--task-timeout",
        type=int,
        default=240,
        help="Timeout chờ kết quả mỗi task (giây)",
    )
    ap.add_argument(
        "--flush-every",
        type=int,
        default=25,
        help="Ghi tạm kết quả ra file output sau mỗi N kết quả (giúp xem progress khi đang chạy)",
    )
    ap.add_argument(
        "--timeouts-output",
        default=None,
        help="Ghi riêng các dòng bị Page load timeout ra file Excel (để chạy lại batch riêng)",
    )
    ap.add_argument(
        "--timeout-reason-substr",
        default="Page load timeout",
        help="Chuỗi reason để phân loại sang file timeouts (mặc định: 'Page load timeout')",
    )
    ap.add_argument("--sync-one", action="store_true", help="Chạy 1 dòng đầu không cần Celery")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    timeouts_output = args.timeouts_output or _default_timeouts_output_path(args.output)
    timeout_token = str(args.timeout_reason_substr or "").strip().lower()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("push_jobs.log", encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info(f"Input: {args.input}")
    logging.info(f"Output: {args.output}")
    logging.info(f"Timeouts output: {timeouts_output}")

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
    job_by_url: dict[str, dict] = {}
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
        job_by_url[url] = jobs[-1]

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
    timeout_jobs: list[dict] = []
    flush_every = max(1, int(args.flush_every))
    last_flushed = 0
    poll_interval = 0.5

    # Chờ theo kiểu "as completed": tránh bị kẹt ở 1 task chậm/treo, và ghi output dần theo tiến độ.
    pending = [(j, ar) for (j, ar) in tasks]
    t_start = time.time()

    while pending:
        progressed = False
        i = len(pending) - 1
        while i >= 0:
            j, ar = pending[i]
            if ar.ready():
                try:
                    out = ar.get(timeout=1)
                except Exception as e:
                    out = {"url": j["url"], "status":"FAILED", "reason":f"No result/timeout: {e}", "comment_link":"", "duration_sec":0.0}
                results.append(out)
                try:
                    reason = str((out or {}).get("reason", "")).lower()
                except Exception:
                    reason = ""
                if timeout_token and timeout_token in reason:
                    src_job = job_by_url.get(j["url"])
                    if src_job:
                        timeout_jobs.append(src_job)
                pending[i] = pending[-1]
                pending.pop()
                progressed = True
                if len(results) - last_flushed >= flush_every:
                    pd.DataFrame(results, columns=RESULT_COLUMNS).to_excel(args.output, index=False)
                    last_flushed = len(results)
                    logging.info(f"Đã ghi tạm {args.output} ({last_flushed} dòng).")
                    if timeout_jobs:
                        pd.DataFrame(timeout_jobs, columns=["url", "anchor", "website", "content", "name", "email"]).rename(
                            columns={
                                "url": "URL",
                                "anchor": "Anchor",
                                "website": "Website",
                                "content": "Nội Dung",
                                "name": "Name",
                                "email": "Email",
                            }
                        ).to_excel(timeouts_output, index=False)
                        logging.info(f"Đã ghi tạm {timeouts_output} ({len(timeout_jobs)} dòng timeouts).")
            i -= 1

        if not progressed:
            # Nếu quá lâu không có task nào xong, vẫn tiếp tục chờ (giữ tốc độ poll vừa phải)
            time.sleep(poll_interval)

    if not results:
        results=[{"url":"", "status":"FAILED", "reason":"No tasks executed", "comment_link":"", "duration_sec":0.0, "language":"unknown", "attempts":0}]
    pd.DataFrame(results, columns=RESULT_COLUMNS).to_excel(args.output, index=False)
    logging.info(f"Đã ghi {args.output} ({len(results)} dòng).")

    if timeout_jobs:
        pd.DataFrame(timeout_jobs, columns=["url", "anchor", "website", "content", "name", "email"]).rename(
            columns={
                "url": "URL",
                "anchor": "Anchor",
                "website": "Website",
                "content": "Nội Dung",
                "name": "Name",
                "email": "Email",
            }
        ).to_excel(timeouts_output, index=False)
        logging.info(f"Đã ghi {timeouts_output} ({len(timeout_jobs)} dòng timeouts).")

if __name__ == "__main__":
    main()
