# src/driver_factory.py
from __future__ import annotations
import os
import time
import shutil
import threading
from typing import Optional

# Selenium chuẩn
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from webdriver_manager.chrome import ChromeDriverManager

# (tuỳ chọn) UC
try:
    import undetected_chromedriver as uc  # noqa: F401
    HAS_UC = True
except Exception:
    HAS_UC = False


def _common_flags() -> list[str]:
    flags_str = os.getenv(
        "CHROME_FLAGS",
        "--headless=new --disable-gpu --disable-software-rasterizer "
        "--no-sandbox --disable-dev-shm-usage --window-size=1200,2000 "
        "--disable-blink-features=AutomationControlled "
        "--disable-features=IsolateOrigins,site-per-process "
        "--remote-allow-origins=*"
    )
    return [f for f in flags_str.split() if f]


def _browser_path() -> Optional[str]:
    """Trả về path Chrome nếu ENV cung cấp; nếu không để Selenium tự tìm."""
    bp = os.getenv("CHROME_BINARY")
    return bp if bp and os.path.exists(bp) else None

_DRIVER_LOCK = threading.Lock()
_DRIVER_PATH: Optional[str] = os.getenv("CHROMEDRIVER_PATH")

def _resolve_driver_path() -> str:
    global _DRIVER_PATH
    with _DRIVER_LOCK:
        if not _DRIVER_PATH:
            try:
                _DRIVER_PATH = ChromeDriverManager(cache_valid_range=30).install()
            except TypeError:
                # webdriver-manager >= 4 dropped cache_valid_range
                _DRIVER_PATH = ChromeDriverManager().install()
    return _DRIVER_PATH


def make_selenium_driver(proxy: Optional[str] = None):
    """Dùng Selenium chuẩn (sử dụng webdriver-manager để đảm bảo có chromedriver)."""
    opts = ChromeOptions()
    pls = (os.getenv("PAGE_LOAD_STRATEGY") or "").strip().lower()
    if pls in {"eager", "none", "normal"}:
        opts.page_load_strategy = pls
    for f in _common_flags():
        opts.add_argument(f)
    # Binary path (tuỳ chọn)
    bp = _browser_path()
    if bp:
        opts.binary_location = bp

    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")

    # User-Agent (tuỳ chọn)
    ua = os.getenv("USER_AGENT")
    if ua:
        opts.add_argument(f"--user-agent={ua}")

    # Quan trọng cho macOS headless
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Optional: speed up by disabling images (helps on heavy pages)
    if os.getenv("DISABLE_IMAGES", "false").strip().lower() in {"1", "true", "yes", "on"}:
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.geolocation": 2,
        }
        opts.add_experimental_option("prefs", prefs)
        opts.add_argument("--blink-settings=imagesEnabled=false")

    driver_path = _resolve_driver_path()
    service = ChromeService(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(int(os.getenv("PAGELOAD_TIMEOUT", "25")))
    return driver


def _clear_uc_cache():
    """Xoá cache UC khi cần (tránh crash do binary patch cũ)."""
    home = os.path.expanduser("~")
    mac_cache = os.path.join(home, "Library", "Application Support", "undetected_chromedriver")
    if os.path.isdir(mac_cache):
        shutil.rmtree(mac_cache, ignore_errors=True)


def make_uc_driver(proxy: Optional[str] = None):
    """Dùng undetected_chromedriver khi thật sự cần stealth."""
    # Dọn cache cũ nếu được yêu cầu
    if os.getenv("UC_CLEAR_CACHE", "false").lower() == "true":
        _clear_uc_cache()

    options = uc.ChromeOptions()
    pls = (os.getenv("PAGE_LOAD_STRATEGY") or "").strip().lower()
    if pls in {"eager", "none", "normal"}:
        options.page_load_strategy = pls
    for f in _common_flags():
        options.add_argument(f)

    bp = _browser_path()
    if bp:
        options.binary_location = bp

    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    ua = os.getenv("USER_AGENT")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    if os.getenv("DISABLE_IMAGES", "false").strip().lower() in {"1", "true", "yes", "on"}:
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.geolocation": 2,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--blink-settings=imagesEnabled=false")

    # Một số site kén version, bạn có thể ép version chính của Chrome nếu biết (VD: 129)
    version_main = os.getenv("UC_VERSION_MAIN")
    def _create_uc():
        if version_main and version_main.isdigit():
            return uc.Chrome(options=options, version_main=int(version_main))
        return uc.Chrome(options=options)

    try:
        drv = _create_uc()
    except FileNotFoundError:
        _clear_uc_cache()
        drv = _create_uc()
    except OSError as exc:
        if getattr(exc, "errno", None) == 26:  # Text file busy
            _clear_uc_cache()
            time.sleep(1)
            drv = _create_uc()
        else:
            raise

    drv.set_page_load_timeout(int(os.getenv("PAGELOAD_TIMEOUT", "25")))
    return drv


def get_driver(proxy: Optional[str] = None):
    """
    Factory: mặc định dùng Selenium chuẩn.
    Set USE_UC=true để dùng undetected_chromedriver.
    """
    use_uc = os.getenv("USE_UC", "false").lower() == "true"
    if use_uc and HAS_UC:
        return make_uc_driver(proxy)
    # fallback về Selenium chuẩn
    return make_selenium_driver(proxy)
