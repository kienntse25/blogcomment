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

# Output (merged) columns for easy filtering in Excel
OUT_STATUS_COL = "Status"
OUT_REASON_COL = "Reason"
OUT_COMMENT_LINK_COL = "Comment Link"
OUT_DURATION_COL = "Duration (sec)"
OUT_LANGUAGE_COL = "Language"
OUT_ATTEMPTS_COL = "Attempts"
OUT_UPDATED_AT_COL = "Updated At"
OUT_EXTRA_COLUMNS = [
    OUT_STATUS_COL,
    OUT_REASON_COL,
    OUT_COMMENT_LINK_COL,
    OUT_DURATION_COL,
    OUT_LANGUAGE_COL,
    OUT_ATTEMPTS_COL,
    OUT_UPDATED_AT_COL,
]

def _cell_str(value) -> str:
    if value is None:
        return ""
    return str(value)

# Đọc Excel (đảm bảo tồn tại)
def _read_df(path, sheet_name=None):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không thấy file: {path}")
    if sheet_name:
        return pd.read_excel(path, engine="openpyxl", sheet_name=sheet_name).fillna("")
    # Đọc tất cả sheets và gộp lại
    all_sheets = pd.read_excel(path, engine="openpyxl", sheet_name=None)
    if isinstance(all_sheets, dict):
        dfs = list(all_sheets.values())
        if not dfs:
            raise ValueError(f"File {path} không có sheet nào")
        return pd.concat(dfs, ignore_index=True).fillna("")
    return all_sheets.fillna("")

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

def _default_no_comment_output_path(output_path: str) -> str:
    base = os.path.basename(output_path)
    if base.lower().endswith(".xlsx"):
        base = base[:-5]
    dirname = os.path.dirname(output_path) or "."
    return os.path.join(dirname, f"{base}_no_comment.xlsx")

def _default_log_path(output_path: str) -> str:
    base = os.path.basename(output_path)
    if base.lower().endswith(".xlsx"):
        base = base[:-5]
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", base).strip("_") or "run"
    return os.path.join("logs", f"push_jobs_{base}.log")

def _setup_logging(output_path: str) -> str:
    log_path = (os.getenv("PUSH_JOBS_LOG") or "").strip()
    if not log_path:
        log_path = _default_log_path(output_path)
    if log_path not in {"-", "stdout", "stderr"}:
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        except Exception:
            pass
        handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()]
    else:
        log_path = "stdout"
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
    return log_path


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


def _load_existing_progress(output_path: str) -> tuple[pd.DataFrame | None, set[str]]:
    """
    Return (existing_out_df, ok_urls) if output exists.
    Supports:
      - merged output (has URL + Status)
      - old results-only output (has url + status)
    """
    if not os.path.exists(output_path):
        return None, set()
    try:
        ex = pd.read_excel(output_path, engine="openpyxl").fillna("")
    except Exception:
        return None, set()

    ok_urls: set[str] = set()

    cols = {str(c).strip(): c for c in ex.columns}
    if "URL" in cols and (OUT_STATUS_COL in cols or "status" in cols or "Status" in cols):
        status_col = cols.get(OUT_STATUS_COL) or cols.get("Status") or cols.get("status")
        for _, r in ex.iterrows():
            u = str(r.get(cols["URL"], "")).strip()
            st = str(r.get(status_col, "")).strip().upper()
            if u and st == "OK":
                ok_urls.add(u)
        return ex, ok_urls

    # results-only legacy
    if "url" in cols and "status" in cols:
        for _, r in ex.iterrows():
            u = str(r.get(cols["url"], "")).strip()
            st = str(r.get(cols["status"], "")).strip().upper()
            if u and st == "OK":
                ok_urls.add(u)
        return ex, ok_urls

    return ex, ok_urls


def _overlay_existing_into_output(
    out_df: pd.DataFrame, input_df: pd.DataFrame, existing_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Best-effort: preserve prior progress if output already exists.
    - If existing is merged output and aligns by row index (same len and URL per row), copy extra columns.
    - If existing is results-only, map by URL and fill extra columns.
    """
    if existing_df is None or existing_df.empty:
        return out_df

    ex_cols = {str(c).strip(): c for c in existing_df.columns}
    if "URL" in ex_cols and len(existing_df) == len(input_df):
        # Ensure per-row URL matches (at least for the first 50 non-empty).
        ok_align = 0
        checked = 0
        for i in range(min(len(input_df), 50)):
            u_in = str(input_df.iloc[i].get("URL", "")).strip()
            u_ex = str(existing_df.iloc[i].get(ex_cols["URL"], "")).strip()
            if not u_in and not u_ex:
                continue
            checked += 1
            if u_in == u_ex:
                ok_align += 1
        if checked == 0 or ok_align / checked >= 0.9:
            for col in OUT_EXTRA_COLUMNS:
                if col in ex_cols:
                    out_df[col] = existing_df[ex_cols[col]]
            return out_df

    # Legacy results-only: map by URL (supports duplicates by consuming in order)
    if "url" in ex_cols and "status" in ex_cols:
        buckets: dict[str, list[dict]] = {}
        for _, r in existing_df.iterrows():
            u = str(r.get(ex_cols["url"], "")).strip()
            if not u:
                continue
            buckets.setdefault(u, []).append(
                {
                    OUT_STATUS_COL: str(r.get(ex_cols.get("status"), "")).strip(),
                    OUT_REASON_COL: str(r.get(ex_cols.get("reason"), "")).strip(),
                    OUT_COMMENT_LINK_COL: str(r.get(ex_cols.get("comment_link"), "")).strip(),
                    OUT_DURATION_COL: r.get(ex_cols.get("duration_sec"), ""),
                    OUT_LANGUAGE_COL: str(r.get(ex_cols.get("language"), "")).strip(),
                    OUT_ATTEMPTS_COL: r.get(ex_cols.get("attempts"), ""),
                }
            )
        for idx, row in out_df.iterrows():
            u = str(row.get("URL", "")).strip()
            if not u or u not in buckets or not buckets[u]:
                continue
            v = buckets[u].pop(0)
            for k, val in v.items():
                out_df.at[idx, k] = val
        return out_df

    return out_df

def _sync_one(job: dict) -> dict:
    # Chạy trực tiếp không cần Celery (để test ra file out ngay)
    from src.worker_lib import run_one_link
    return run_one_link(job)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=_default_input_path(), help="Đường dẫn file Excel input")
    ap.add_argument("--output", default=_default_output_path(), help="Đường dẫn file Excel output")
    ap.add_argument(
        "--queue",
        default=(os.getenv("CELERY_QUEUE") or "").strip() or None,
        help="Tên queue Celery cho campaign (vd: camp_a). Nếu bỏ trống sẽ dùng queue mặc định.",
    )
    ap.add_argument(
        "--attach-anchor",
        dest="attach_anchor",
        action="store_true",
        default=(os.getenv("ATTACH_ANCHOR", "true").strip().lower() in {"1", "true", "yes", "on"}),
        help="Gắn Anchor/Website vào comment (mặc định: ATTACH_ANCHOR=true).",
    )
    ap.add_argument(
        "--no-attach-anchor",
        dest="attach_anchor",
        action="store_false",
        help="Không gắn Anchor/Website vào comment (ghi đúng Nội Dung như trong file).",
    )
    ap.add_argument(
        "--resume-ok",
        action="store_true",
        help="Nếu output đã tồn tại, bỏ qua các URL có status=OK trong output (hữu ích khi crash/restart).",
    )
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
    ap.add_argument(
        "--no-comment-output",
        default=None,
        help="Ghi riêng các dòng bị 'Comment box not found' ra file Excel (để chạy batch chậm hơn)",
    )
    ap.add_argument(
        "--no-comment-reason-substr",
        default="Comment box not found",
        help="Chuỗi reason để phân loại sang file no_comment (mặc định: 'Comment box not found')",
    )
    ap.add_argument("--sync-one", action="store_true", help="Chạy 1 dòng đầu không cần Celery")
    args = ap.parse_args()

    out_dir = os.path.dirname(args.output) or "."
    os.makedirs(out_dir, exist_ok=True)
    timeouts_output = args.timeouts_output or _default_timeouts_output_path(args.output)
    timeout_token = str(args.timeout_reason_substr or "").strip().lower()
    no_comment_output = args.no_comment_output or _default_no_comment_output_path(args.output)
    no_comment_token = str(args.no_comment_reason_substr or "").strip().lower()

    log_path = _setup_logging(args.output)
    logging.info(f"Log: {log_path}")
    logging.info(f"Input: {args.input}")
    logging.info(f"Output: {args.output}")
    logging.info(f"Timeouts output: {timeouts_output}")
    logging.info(f"No-comment output: {no_comment_output}")
    logging.info("Output mode: merged (input columns + result columns)")

    # Đọc input
    try:
        df = _read_df(args.input)
    except Exception as e:
        logging.error(f"Không thể đọc Excel: {e}")
        pd.DataFrame(columns=REQUIRED_COLUMNS + OUT_EXTRA_COLUMNS).to_excel(args.output, index=False)
        return

    # Bắt buộc header (chấp nhận alias, không phân biệt hoa thường/dấu)
    df, miss = _standardize_columns(df)
    if miss:
        logging.error(f"Thiếu cột {miss}. Yêu cầu header: {REQUIRED_COLUMNS}")
        pd.DataFrame(columns=REQUIRED_COLUMNS + OUT_EXTRA_COLUMNS).to_excel(args.output, index=False)
        return

    done_ok: set[str] = set()
    existing_out, ok_urls = _load_existing_progress(args.output)
    if args.resume_ok and ok_urls:
        done_ok = set(ok_urls)
    if done_ok:
        logging.info(f"[resume] Sẽ bỏ qua {len(done_ok)} URL đã OK trong {args.output}")

    # Prepare merged output frame (same row count as input) and preserve previous progress if any.
    out_merged = df.copy()
    for col in OUT_EXTRA_COLUMNS:
        if col not in out_merged.columns:
            out_merged[col] = ""
    if existing_out is not None:
        out_merged = _overlay_existing_into_output(out_merged, df, existing_out)
    # Ensure output file exists early (helps monitoring progress on VPS).
    try:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        out_merged.to_excel(args.output, index=False)
        logging.info(f"Initialized output file: {args.output} (rows={len(out_merged)})")
    except Exception as e:
        logging.warning(f"Không thể khởi tạo output sớm ({args.output}): {e}")

    # Tạo jobs
    jobs=[]
    max_jobs = args.limit if args.limit and args.limit > 0 else None
    skipped_empty = 0
    skipped_ok = 0
    for i, row in df.iterrows():
        if max_jobs is not None and len(jobs) >= max_jobs:
            break
        url = str(row["URL"]).strip()
        if not url:
            logging.warning(f"Dòng {i+2} URL trống → bỏ qua")
            skipped_empty += 1
            continue
        if done_ok and url in done_ok:
            skipped_ok += 1
            continue
        jobs.append({
            "__row": int(i),
            "url": url,
            "anchor": str(row["Anchor"]).strip(),
            "website": str(row["Website"]).strip(),
            "content": str(row["Nội Dung"]).strip(),
            "name": str(row["Name"]).strip() or "Guest",
            "email": str(row["Email"]).strip(),
            "attach_anchor": bool(args.attach_anchor),
        })

    logging.info(
        "Prepared jobs=%d (input_rows=%d, skipped_empty=%d, skipped_ok=%d%s)",
        len(jobs),
        len(df),
        skipped_empty,
        skipped_ok,
        f", limit={max_jobs}" if max_jobs is not None else "",
    )

    if not jobs:
        logging.warning("Không có job hợp lệ.")
        out_merged.to_excel(args.output, index=False)
        return

    # Test nhanh 1 dòng (không Celery)
    if args.sync_one:
        logging.info("[SYNC-ONE] chạy 1 job không Celery để kiểm tra end-to-end")
        res = _sync_one({k: v for k, v in jobs[0].items() if k != "__row"})
        i = jobs[0]["__row"]
        out_merged.at[i, OUT_STATUS_COL] = str(res.get("status", "")).strip()
        out_merged.at[i, OUT_REASON_COL] = str(res.get("reason", "")).strip()
        out_merged.at[i, OUT_COMMENT_LINK_COL] = str(res.get("comment_link", "")).strip()
        out_merged.at[i, OUT_DURATION_COL] = _cell_str(res.get("duration_sec", ""))
        out_merged.at[i, OUT_LANGUAGE_COL] = str(res.get("language", "")).strip()
        out_merged.at[i, OUT_ATTEMPTS_COL] = _cell_str(res.get("attempts", ""))
        out_merged.at[i, OUT_UPDATED_AT_COL] = time.strftime("%Y-%m-%d %H:%M:%S")
        out_merged.to_excel(args.output, index=False)
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
            if args.queue:
                ar = run_comment.apply_async(args=[{k: v for k, v in j.items() if k != "__row"}], queue=args.queue, routing_key=args.queue)
            else:
                ar = run_comment.delay({k: v for k, v in j.items() if k != "__row"})
            tasks.append((j, ar, time.time()))
            logging.info(f"Đã gửi task cho URL: {j['url']} (queue={args.queue or 'default'})")
        except Exception as e:
            logging.error(f"Gửi task lỗi {j['url']}: {e}")

    logging.info("Đang chờ kết quả từ các task...")
    timeout_rows: set[int] = set()
    no_comment_rows: set[int] = set()
    flush_every = max(1, int(args.flush_every))
    finished = 0
    poll_interval = 0.5

    # Chờ theo kiểu "as completed": tránh bị kẹt ở 1 task chậm/treo, và ghi output dần theo tiến độ.
    pending = [(j, ar, sent_at) for (j, ar, sent_at) in tasks]
    t_start = time.time()
    last_heartbeat = t_start

    while pending:
        progressed = False
        i = len(pending) - 1
        while i >= 0:
            j, ar, sent_at = pending[i]
            # Hard per-task timeout: prevents the whole run from "stopping" because a task is stuck forever.
            if args.task_timeout and args.task_timeout > 0 and not ar.ready():
                age = time.time() - sent_at
                if age >= args.task_timeout:
                    row_i = int(j.get("__row", -1))
                    out = {
                        "url": j.get("url", ""),
                        "status": "FAILED",
                        "reason": f"No result/timeout after {int(age)}s",
                        "comment_link": "",
                        "duration_sec": 0.0,
                        "language": "unknown",
                        "attempts": "",
                    }
                    if row_i >= 0:
                        out_merged.at[row_i, OUT_STATUS_COL] = "FAILED"
                        out_merged.at[row_i, OUT_REASON_COL] = out["reason"]
                        out_merged.at[row_i, OUT_COMMENT_LINK_COL] = ""
                        out_merged.at[row_i, OUT_DURATION_COL] = out.get("duration_sec", "")
                        out_merged.at[row_i, OUT_LANGUAGE_COL] = out.get("language", "")
                        out_merged.at[row_i, OUT_ATTEMPTS_COL] = out.get("attempts", "")
                        out_merged.at[row_i, OUT_UPDATED_AT_COL] = time.strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        # Best-effort: ask Celery to drop it (may already be running).
                        ar.revoke(terminate=False)
                    except Exception:
                        pass
                    pending[i] = pending[-1]
                    pending.pop()
                    progressed = True
                    finished += 1
                    if finished % flush_every == 0:
                        out_merged.to_excel(args.output, index=False)
                        logging.info(f"Đã ghi tạm {args.output} (done={finished}).")
                    i -= 1
                    continue
            if ar.ready():
                try:
                    out = ar.get(timeout=1)
                except Exception as e:
                    out = {"url": j["url"], "status":"FAILED", "reason":f"No result/timeout: {e}", "comment_link":"", "duration_sec":0.0}
                row_i = int(j.get("__row", -1))
                if row_i >= 0:
                    out_merged.at[row_i, OUT_STATUS_COL] = str((out or {}).get("status", "")).strip()
                    out_merged.at[row_i, OUT_REASON_COL] = str((out or {}).get("reason", "")).strip()
                    out_merged.at[row_i, OUT_COMMENT_LINK_COL] = str((out or {}).get("comment_link", "")).strip()
                    out_merged.at[row_i, OUT_DURATION_COL] = _cell_str((out or {}).get("duration_sec", ""))
                    out_merged.at[row_i, OUT_LANGUAGE_COL] = str((out or {}).get("language", "")).strip()
                    out_merged.at[row_i, OUT_ATTEMPTS_COL] = _cell_str((out or {}).get("attempts", ""))
                    out_merged.at[row_i, OUT_UPDATED_AT_COL] = time.strftime("%Y-%m-%d %H:%M:%S")
                try:
                    reason = str((out or {}).get("reason", "")).lower()
                except Exception:
                    reason = ""
                if timeout_token and timeout_token in reason:
                    if row_i >= 0:
                        timeout_rows.add(row_i)
                if no_comment_token and no_comment_token in reason:
                    if row_i >= 0:
                        no_comment_rows.add(row_i)
                pending[i] = pending[-1]
                pending.pop()
                progressed = True
                finished += 1
                if finished % flush_every == 0:
                    out_merged.to_excel(args.output, index=False)
                    logging.info(f"Đã ghi tạm {args.output} (done={finished}).")
                    if timeout_rows:
                        df.loc[sorted(timeout_rows), REQUIRED_COLUMNS].to_excel(timeouts_output, index=False)
                        logging.info(f"Đã ghi tạm {timeouts_output} ({len(timeout_rows)} dòng timeouts).")
                    if no_comment_rows:
                        df.loc[sorted(no_comment_rows), REQUIRED_COLUMNS].to_excel(no_comment_output, index=False)
                        logging.info(f"Đã ghi tạm {no_comment_output} ({len(no_comment_rows)} dòng no_comment).")
            i -= 1

        if not progressed:
            # Heartbeat để biết process còn sống (tránh hiểu nhầm "dừng ở 250").
            now = time.time()
            if now - last_heartbeat >= 60:
                logging.info(
                    "Still waiting... finished=%d pending=%d elapsed=%ds",
                    finished,
                    len(pending),
                    int(now - t_start),
                )
                last_heartbeat = now
            # Nếu quá lâu không có task nào xong, vẫn tiếp tục chờ (giữ tốc độ poll vừa phải)
            time.sleep(poll_interval)

    out_merged.to_excel(args.output, index=False)
    logging.info(f"Đã ghi {args.output} (total_rows={len(out_merged)}).")

    if timeout_rows:
        df.loc[sorted(timeout_rows), REQUIRED_COLUMNS].to_excel(timeouts_output, index=False)
        logging.info(f"Đã ghi {timeouts_output} ({len(timeout_rows)} dòng timeouts).")
    if no_comment_rows:
        df.loc[sorted(no_comment_rows), REQUIRED_COLUMNS].to_excel(no_comment_output, index=False)
        logging.info(f"Đã ghi {no_comment_output} ({len(no_comment_rows)} dòng no_comment).")

if __name__ == "__main__":
    main()
