# src/main.py
from __future__ import annotations
import argparse, os, time, multiprocessing as mp
from pathlib import Path
from loguru import logger

from .config import (
    HEADLESS, BATCH_SIZE, PAUSE_MIN, PAUSE_MAX,
    INPUT_XLSX, OUTPUT_XLSX, SCREENSHOT_ON_FAIL, FAILSHOT_DIR
)
from .utils.io_excel import load_rows, save_rows
from .utils.throttle import human_pause
from .analyzer import analyzable_row
from .discover import discover_form
from .cache import load_cache, save_cache, lookup, upsert
from .utils.driver import build_driver


# =========================
# Helpers
# =========================
def _sanitize(s: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)[:120]


def save_fail_screenshot(driver, url: str, reason: str) -> str:
    if not SCREENSHOT_ON_FAIL:
        return ""
    Path(FAILSHOT_DIR).mkdir(parents=True, exist_ok=True)
    host = _sanitize(url.split("/")[2] if "://" in url else url)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(FAILSHOT_DIR, f"{ts}_{host}.png")
    try:
        driver.save_screenshot(path)
        return path
    except Exception:
        return ""


def _row_to_selectors(row) -> dict:
    def _val(k):
        v = str(row.get(k, "")).strip()
        return v if v else None

    def _to_int(v):
        try:
            return int(str(v).strip())
        except Exception:
            return None

    return {
        "ta_sel": _val("tpl_ta_sel"),
        "name_sel": _val("tpl_name_sel"),
        "email_sel": _val("tpl_email_sel"),
        "btn_sel": _val("tpl_btn_sel"),
        "ta_iframe": _to_int(_val("tpl_ta_iframe")),
        "btn_iframe": _to_int(_val("tpl_btn_iframe")),
    }


def _write_selectors_to_row(df, i, sel: dict, scope: str = "domain"):
    # Các cột template sẽ auto tạo nếu chưa có
    df.at[i, "tpl_ta_sel"] = sel.get("ta_sel") or ""
    df.at[i, "tpl_name_sel"] = sel.get("name_sel") or ""
    df.at[i, "tpl_email_sel"] = sel.get("email_sel") or ""
    df.at[i, "tpl_btn_sel"] = sel.get("btn_sel") or ""
    df.at[i, "tpl_ta_iframe"] = "" if sel.get("ta_iframe") is None else str(sel.get("ta_iframe"))
    df.at[i, "tpl_btn_iframe"] = "" if sel.get("btn_iframe") is None else str(sel.get("btn_iframe"))
    df.at[i, "tpl_scope"] = scope


def _ensure_object_cols(df, cols: list[str]):
    """Đảm bảo các cột là dtype=object để ghi string không cảnh báo."""
    import pandas as pd
    for c in cols:
        if c not in df.columns:
            df[c] = pd.Series(dtype="object")
        else:
            if str(df[c].dtype) != "object":
                df[c] = df[c].astype("object")


# =========================
# analyze
# =========================
def cmd_analyze(args: argparse.Namespace) -> None:
    inp, out = args.input or INPUT_XLSX, args.output or OUTPUT_XLSX
    df = load_rows(inp)
    _ensure_object_cols(df, ["status", "notes"])
    for i, row in df.iterrows():
        ok, reason = analyzable_row(row)
        if ok:
            df.at[i, "status"] = "Analyzed"
            df.at[i, "notes"] = ""
        else:
            df.at[i, "status"] = "Skipped"
            df.at[i, "notes"] = reason
    save_rows(df, out)
    logger.info(f"Analyze done -> {out}")


# =========================
# scan (ghi template + cache)
# =========================
def cmd_scan(args: argparse.Namespace) -> None:
    inp = args.input or INPUT_XLSX
    scope, cache_path = args.scope, args.cache
    start, limit = int(args.start or 0), int(args.limit or 0)
    save_every = max(1, int(args.save_every or 10))
    write_template = bool(args.write_template)

    df = load_rows(inp)
    rows = [(i, row) for i, row in df.iterrows()]
    if start > 0:
        rows = rows[start:]
    if limit > 0:
        rows = rows[:limit]

    cache = load_cache(cache_path)
    driver = build_driver(HEADLESS)
    scanned = 0
    try:
        for pos, (i, row) in enumerate(rows, 1):
            url = str(row.get("url", "")).strip()
            if not url:
                continue

            # nếu đã có template trong excel thì bỏ qua scan
            if any(_row_to_selectors(row).values()):
                continue

            sel = lookup(cache, url) or discover_form(driver, url)
            if sel:
                upsert(cache, url, sel, scope=scope)
                scanned += 1
                if write_template:
                    _write_selectors_to_row(df, i, sel, scope=scope)

            if scanned % save_every == 0:
                save_cache(cache, cache_path)
                if write_template:
                    save_rows(df, inp)

            if pos % BATCH_SIZE == 0:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = build_driver(HEADLESS)

            human_pause(PAUSE_MIN, PAUSE_MAX)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    save_cache(cache, cache_path)
    if write_template:
        save_rows(df, inp)
    logger.info(f"Scan done -> {cache_path} (new: {scanned})")


# =========================
# worker for parallel posting
# =========================
def _worker_post(tasklist: list, options: dict) -> list[tuple[int, str, str]]:
    from .commenter import post_comment
    from selenium.common.exceptions import WebDriverException

    headless = bool(options.get("headless", True))
    pause_min = float(options.get("pause_min", 0.3))
    pause_max = float(options.get("pause_max", 0.7))
    restart_each = int(options.get("restart_each", 100))

    driver = build_driver(headless)
    out = []
    processed = 0

    try:
        for t in tasklist:
            i, url, name, email, comment, sel = t
            try:
                ok, reason = post_comment(driver, url, name, email, comment, selectors=sel)
                out.append((i, "Posted" if ok else "Failed", reason))
            except WebDriverException as e:
                out.append((i, "Failed", f"WebDriver: {getattr(e, 'msg', str(e))[:180]}"))
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = build_driver(headless)
            except Exception as e:
                out.append((i, "Failed", f"Unhandled: {e.__class__.__name__}: {e}"))
            processed += 1
            if processed % restart_each == 0:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = build_driver(headless)
            human_pause(pause_min, pause_max)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return out


# Hàm entry top-level cho multiprocessing (tránh lambda để picklable trên Windows)
def _worker_entry(args):
    chunk, options = args
    return _worker_post(chunk, options)


# =========================
# post (song song)
# =========================
def cmd_post(args: argparse.Namespace) -> None:
    inp = args.input or OUTPUT_XLSX
    start, limit = int(args.start or 0), int(args.limit or 0)
    save_every = max(1, int(args.save_every or 5))
    dry_run = bool(args.dry_run)
    cache_path = args.cache
    prefer_template = bool(args.prefer_template)
    use_template_only = bool(args.use_template_only)
    workers = max(1, int(getattr(args, "workers", 1)))
    chunk_size = max(10, int(getattr(args, "chunk", 60)))

    df = load_rows(inp)
    _ensure_object_cols(df, ["status", "notes"])

    rows_all = [(i, row) for i, row in df.iterrows() if str(row.get("status", "")).strip() == "Analyzed"]
    if start > 0:
        rows_all = rows_all[start:]
    if limit > 0:
        rows_all = rows_all[:limit]

    cache = load_cache(cache_path) if cache_path else {"hosts": {}}
    tasks: list[tuple[int, str, str, str, str, dict | None]] = []

    for i, row in rows_all:
        url = str(row.get("url", "")).strip()
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip()
        comment = str(row.get("comment", "")).strip()
        tpl = _row_to_selectors(row)
        has_tpl = any(tpl.values())

        if use_template_only and not has_tpl:
            df.at[i, "status"] = "Failed"
            df.at[i, "notes"] = "No template selectors"
            continue

        if prefer_template and has_tpl:
            sel = tpl
        elif has_tpl:
            sel = tpl
        else:
            sel = (lookup(cache, url) if cache_path else None)

        tasks.append((i, url, name, email, comment, sel))

    if dry_run:
        for i, *_ in tasks:
            df.at[i, "notes"] = "DRY RUN: would open and post"
        save_rows(df, inp)
        logger.info(f"DRY RUN updated -> {inp}")
        return

    if workers == 1:
        res = _worker_post(tasks, {"headless": HEADLESS, "pause_min": PAUSE_MIN, "pause_max": PAUSE_MAX})
        for i, st, note in res:
            df.at[i, "status"] = st
            df.at[i, "notes"] = note
    else:
        chunks = [tasks[x : x + chunk_size] for x in range(0, len(tasks), chunk_size)]
        options = {"headless": HEADLESS, "pause_min": PAUSE_MIN, "pause_max": PAUSE_MAX}
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=workers) as pool:
            for res in pool.imap_unordered(_worker_entry, [(c, options) for c in chunks]):
                for i, st, note in res:
                    df.at[i, "status"] = st
                    df.at[i, "notes"] = note
                save_rows(df, inp)  # lưu sau mỗi chunk

    save_rows(df, inp)
    logger.info(f"Posting done -> {inp} (processed {len(tasks)} rows)")


# =========================
# run all (analyze -> scan -> post)
# =========================
def cmd_run(args: argparse.Namespace) -> None:
    a = argparse.Namespace(input=args.input or INPUT_XLSX, output=args.output or OUTPUT_XLSX)
    cmd_analyze(a)

    if args.cache:
        s = argparse.Namespace(
            input=args.output or OUTPUT_XLSX,
            scope="domain",
            cache=args.cache,
            start=0,
            limit=0,
            save_every=20,
            write_template=True,
        )
        cmd_scan(s)

    p = argparse.Namespace(
        input=args.output or OUTPUT_XLSX,
        start=0,
        limit=0,
        save_every=5,
        dry_run=False,
        cache=args.cache,
        prefer_template=True,
        use_template_only=False,
        workers=getattr(args, "workers", 1),
        chunk=80,
    )
    cmd_post(p)


# API “1 phát” cho GUI (không bắt buộc, nhưng tiện gọi)
def run_pipeline_file(input_path: str) -> str:
    """Chạy phân tích -> scan -> post cho 1 file Excel. Trả về output path."""
    stem, _ = os.path.splitext(input_path)
    out = f"{stem}_out_{time.strftime('%Y%m%d-%H%M')}.xlsx"
    cmd_analyze(argparse.Namespace(input=input_path, output=out))
    cmd_scan(
        argparse.Namespace(
            input=out,
            cache="data/forms_cache.json",
            scope="domain",
            start=0,
            limit=0,
            save_every=20,
            write_template=True,
        )
    )
    cmd_post(
        argparse.Namespace(
            input=out,
            start=0,
            limit=0,
            save_every=1,
            dry_run=False,
            cache="data/forms_cache.json",
            prefer_template=True,
            use_template_only=False,
            workers=4,
            chunk=80,
        )
    )
    return out


# =========================
# CLI
# =========================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="blog-comment-tool",
        description="Fast SEO blog comment tool (pre-filter + template + parallel)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("analyze")
    pa.add_argument("--input", "-i", default=INPUT_XLSX)
    pa.add_argument("--output", "-o", default=OUTPUT_XLSX)
    pa.set_defaults(func=cmd_analyze)

    ps = sub.add_parser("scan")
    ps.add_argument("--input", "-i", default=INPUT_XLSX)
    ps.add_argument("--cache", default="data/forms_cache.json")
    ps.add_argument("--scope", choices=["domain", "path"], default="domain")
    ps.add_argument("--start", type=int, default=0)
    ps.add_argument("--limit", type=int, default=0)
    ps.add_argument("--save-every", type=int, default=20)
    ps.add_argument("--write-template", action="store_true")
    ps.set_defaults(func=cmd_scan)

    pp = sub.add_parser("post")
    pp.add_argument("--input", "-i", default=OUTPUT_XLSX)
    pp.add_argument("--start", type=int, default=0)
    pp.add_argument("--limit", type=int, default=0)
    pp.add_argument("--save-every", type=int, default=5)
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--cache", default="data/forms_cache.json")
    pp.add_argument("--prefer-template", action="store_true")
    pp.add_argument("--use-template-only", action="store_true")
    pp.add_argument("--workers", type=int, default=1)
    pp.add_argument("--chunk", type=int, default=60)
    pp.set_defaults(func=cmd_post)

    pr = sub.add_parser("run")
    pr.add_argument("--input", "-i", default=INPUT_XLSX)
    pr.add_argument("--output", "-o", default=OUTPUT_XLSX)
    pr.add_argument("--cache", default="data/forms_cache.json")
    pr.add_argument("--workers", type=int, default=1)
    pr.set_defaults(func=cmd_run)
    return p


def main():
    mp.freeze_support()  # cần cho Windows khi đóng gói/khởi động process con
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
