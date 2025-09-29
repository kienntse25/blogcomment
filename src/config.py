from dotenv import load_dotenv
import os
load_dotenv()

def _b(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on")

HEADLESS   = _b("HEADLESS", "true")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "120"))

PAUSE_MIN  = float(os.getenv("PAUSE_MIN", "0.3"))
PAUSE_MAX  = float(os.getenv("PAUSE_MAX", "0.7"))

INPUT_XLSX  = os.getenv("INPUT_XLSX", "data/comments.xlsx")
OUTPUT_XLSX = os.getenv("OUTPUT_XLSX", "data/comments_out.xlsx")

FIND_TIMEOUT       = float(os.getenv("FIND_TIMEOUT", "3"))
AFTER_SUBMIT_PAUSE = float(os.getenv("AFTER_SUBMIT_PAUSE", "0.6"))

PAGE_LOAD_STRATEGY = os.getenv("PAGE_LOAD_STRATEGY", "eager")
DISABLE_IMAGES     = _b("DISABLE_IMAGES", "true")

USER_AGENT         = os.getenv("USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
SCREENSHOT_ON_FAIL = _b("SCREENSHOT_ON_FAIL", "true")
FAILSHOT_DIR       = os.getenv("FAILSHOT_DIR", "logs/fails")
