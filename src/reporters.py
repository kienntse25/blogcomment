import csv, time, statistics
from pathlib import Path

def log_result(campaign, result: dict):
    log_path = Path(f"logs/{campaign}/run_times.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    new = not log_path.exists()
    with log_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["ts", "url", "status", "reason", "duration_sec"])
        writer.writerow([time.strftime("%F %T"), result["url"], result["status"], result["reason"], result["duration_sec"]])

def summary_daily(campaign):
    path = Path(f"logs/{campaign}/run_times.csv")
    if not path.exists(): return None

    rows = list(csv.DictReader(path.open()))
    total = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    fail = total - ok
    durations = [float(r["duration_sec"]) for r in rows if r["duration_sec"]]

    summary_path = Path("logs/summary_daily.csv")
    new = not summary_path.exists()
    with summary_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["date", "campaign", "total", "success", "fail", "success_rate", "avg_time_sec"])
        writer.writerow([
            time.strftime("%F"),
            campaign,
            total,
            ok,
            fail,
            f"{ok*100/total:.2f}%",
            round(statistics.mean(durations), 2) if durations else 0
        ])
