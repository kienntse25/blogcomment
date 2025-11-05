from __future__ import annotations
import os
from typing import Iterable


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None:
        return float(default)
    try:
        return float(val)
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return int(default)
    try:
        return int(val)
    except ValueError:
        return int(default)


def _parse_versions(raw: str | None, fallback: Iterable[int]) -> list[int]:
    if not raw:
        return list(fallback)
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out or list(fallback)

def _parse_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


# Timeout & timing
FIND_TIMEOUT = _env_float("FIND_TIMEOUT", 8.0)           # Thời gian tìm field (s)
AFTER_SUBMIT_PAUSE = _env_float("AFTER_SUBMIT_PAUSE", 2.0)  # Dừng lại sau khi submit (s)
PAGE_LOAD_TIMEOUT = _env_int("PAGELOAD_TIMEOUT", 25)     # Timeout load trang (s)

# Log/DB
SCRIPT_LOG = os.getenv("SCRIPT_LOG", "blog_comment_tool.log")
REGISTRY_DB = os.getenv("REGISTRY_DB", os.getenv("SEEN_DB", "data/registry.sqlite3"))
SEEN_DB = REGISTRY_DB  # giữ tên cũ cho tương thích

# Trình duyệt & Selenium
HEADLESS = _env_bool("HEADLESS", True)                   # Khi chạy VPS (không GUI), để True
PAGE_LOAD_STRATEGY = os.getenv("PAGE_LOAD_STRATEGY", "normal")
DISABLE_IMAGES = _env_bool("DISABLE_IMAGES", False)
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
)

# Cho undetected-chromedriver: thử auto trước (0), sau đó fallback các version được cấu hình
RETRY_DRIVER_VERSIONS = _parse_versions(
    os.getenv("RETRY_DRIVER_VERSIONS"),
    [141, 0, 140],
)

# Pipeline defaults
INPUT_XLSX = os.getenv("INPUT_XLSX", "data/comments.xlsx")
OUTPUT_XLSX = os.getenv("OUTPUT_XLSX", "data/comments_out.xlsx")
BATCH_SIZE = _env_int("BATCH_SIZE", 40)
PAUSE_MIN = _env_float("PAUSE_MIN", 0.3)
PAUSE_MAX = _env_float("PAUSE_MAX", 0.7)
SCREENSHOT_ON_FAIL = _env_bool("SCREENSHOT_ON_FAIL", False)
FAILSHOT_DIR = os.getenv("FAILSHOT_DIR", "logs/failshots")
MAX_ATTEMPTS = _env_int("MAX_ATTEMPTS", 2)
RETRY_DELAY_SEC = _env_float("RETRY_DELAY_SEC", 3.0)
LANG_DETECT_MIN_CHARS = _env_int("LANG_DETECT_MIN_CHARS", 160)

# Proxy
PROXY_URL = (os.getenv("PROXY_URL") or "").strip() or None
PROXY_LIST = _parse_list(os.getenv("PROXY_LIST"))
_proxy_file_env = (os.getenv("PROXY_FILE") or "").strip()
if _proxy_file_env:
    PROXY_FILE = _proxy_file_env
else:
    _default_proxy_file = os.path.join("data", "proxies.txt")
    PROXY_FILE = _default_proxy_file if os.path.exists(_default_proxy_file) else None

_proxy_xlsx_env = (os.getenv("PROXY_XLSX") or "").strip()
if _proxy_xlsx_env:
    PROXY_XLSX = _proxy_xlsx_env
else:
    _default_proxy_xlsx = os.path.join("data", "proxies.xlsx")
    PROXY_XLSX = _default_proxy_xlsx if os.path.exists(_default_proxy_xlsx) else None
