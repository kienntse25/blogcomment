# src/worker_lib.py
from __future__ import annotations
import os
import time
import socket
import logging
import random
import undetected_chromedriver as uc
from selenium.common.exceptions import InvalidSessionIdException
from urllib3.exceptions import ProtocolError, ReadTimeoutError
from http.client import RemoteDisconnected

from .config import (
    HEADLESS,
    RETRY_DRIVER_VERSIONS,
    MAX_ATTEMPTS,
    RETRY_DELAY_SEC,
    PROXY_URL,
    PROXY_LIST,
    PROXY_FILE,
)
from .registry import was_seen, mark_seen
from . import commenter
from .driver_factory import make_selenium_driver

log = logging.getLogger("worker_lib")

_FILE_PROXY_CACHE: list[str] | None = None
_FILE_PROXY_MTIME: float | None = None


def _load_proxies_from_file() -> list[str]:
    global _FILE_PROXY_CACHE, _FILE_PROXY_MTIME
    if not PROXY_FILE:
        return []
    try:
        st = os.stat(PROXY_FILE)
    except FileNotFoundError:
        _FILE_PROXY_CACHE = None
        _FILE_PROXY_MTIME = None
        return []
    except OSError:
        return []

    if _FILE_PROXY_CACHE is not None and _FILE_PROXY_MTIME == st.st_mtime:
        return _FILE_PROXY_CACHE

    try:
        with open(PROXY_FILE, "r", encoding="utf-8") as fh:
            proxies = [
                line.strip()
                for line in fh
                if line.strip() and not line.strip().startswith("#")
            ]
    except OSError:
        return []

    _FILE_PROXY_CACHE = proxies
    _FILE_PROXY_MTIME = st.st_mtime
    return proxies


def _pick_proxy() -> str | None:
    candidates: list[str] = []
    if PROXY_LIST:
        candidates.extend(PROXY_LIST)
    file_proxies = _load_proxies_from_file()
    if file_proxies:
        candidates.extend(file_proxies)
    if candidates:
        return random.choice(candidates)
    return PROXY_URL


def _make_driver_uc(version_main: int = 0, proxy: str | None = None):
    """
    version_main = 0 → để UC auto chọn.
    Nếu lỗi version mismatch, sẽ fallback sang các version trong RETRY_DRIVER_VERSIONS.
    """
    opts = uc.ChromeOptions()
    if HEADLESS:
        opts.headless = True
        opts.add_argument("--headless=new")
    # các flag an toàn
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,2400")

    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")

    driver = uc.Chrome(options=opts, version_main=(version_main or None), use_subprocess=True)
    try:
        driver.set_window_size(1280, 2400)
    except Exception:
        pass
    return driver


def _acquire_driver(prefer_uc: bool = True, proxy: str | None = None):
    errors: list[str] = []
    if prefer_uc:
        for idx, ver in enumerate(RETRY_DRIVER_VERSIONS, start=1):
            try:
                driver = _make_driver_uc(ver, proxy=proxy)
                log.info(
                    "[worker_lib] Created Chrome driver (provider=uc, attempt=%d, major=%s)",
                    idx,
                    ver or "auto",
                )
                return driver, "uc", ""
            except Exception as e:
                msg = f"uc_major={ver or 'auto'} -> {e}"
                errors.append(msg)
                log.warning("[worker_lib] make_driver UC attempt %d failed: %s", idx, e)
    try:
        driver = make_selenium_driver(proxy=proxy)
        log.info("[worker_lib] Fallback to Selenium driver (provider=selenium)")
        return driver, "selenium", ""
    except Exception as e:
        errors.append(f"selenium -> {e}")
    return None, "none", "; ".join(errors)


def _should_retry(reason: str) -> bool:
    if not reason:
        return True
    reason_lower = reason.lower()
    fatal_tokens = (
        "login",
        "captcha",
        "already attempted",
        "comment box not found",
        "no submit button",
        "dns not resolved",
        "invalid url",
        "third-party",
        "requires login",
        "remote disconnected",
        "connection aborted",
    )
    return not any(tok in reason_lower for tok in fatal_tokens)

def run_one_link(job: dict) -> dict:
    """
    job: {'url','anchor','content','name','email','website'}
    return: dict {'url','status','reason','comment_link','duration_sec','language','attempts'}
    """
    t0 = time.time()
    url    = str(job.get("url", "")).strip()
    name   = str(job.get("name", "")).strip()
    email  = str(job.get("email", "")).strip()
    content= str(job.get("content","")).strip()

    if not url:
        return {
            "url": "",
            "status": "FAILED",
            "reason": "Empty URL",
            "comment_link": "",
            "duration_sec": 0.0,
            "language": "unknown",
            "attempts": 0,
        }

    # Chặn lặp lại (nhận diện bằng url+content+name+email)
    if was_seen(url, content, name or "", email or ""):
        return {
            "url": url,
            "status": "SKIPPED",
            "reason": "Already attempted (registry)",
            "comment_link": "",
            "duration_sec": 0.0,
            "language": "unknown",
            "attempts": 0,
        }

    attempts = 0
    last_reason = ""
    comment_link = ""
    status = "FAILED"
    language = "unknown"
    prefer_uc = True
    proxy = _pick_proxy()
    last_driver_provider = "none"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        driver = None
        try:
            driver, driver_provider, last_driver_err = _acquire_driver(
                prefer_uc=prefer_uc,
                proxy=proxy,
            )
            if not driver:
                last_reason = f"WebDriver init fail: {last_driver_err}"
                log.error("[worker_lib] Unable to create driver for %s: %s", url, last_driver_err)
                break
            last_driver_provider = driver_provider

            ok, rsn, cm_link = commenter.process_job(driver, job)
            language = commenter.detect_language(driver) or "unknown"
            status = "OK" if ok else "FAILED"
            last_reason = rsn
            comment_link = cm_link or ""

            if ok:
                break

            if not _should_retry(rsn) or attempt == MAX_ATTEMPTS:
                break

            log.info("[worker_lib] Retry scheduled for %s (attempt %d/%d) reason=%s", url, attempt, MAX_ATTEMPTS, rsn)
            time.sleep(RETRY_DELAY_SEC)
        except InvalidSessionIdException as e:
            status = "FAILED"
            last_reason = "WebDriver session lost"
            log.warning(
                "[worker_lib] Invalid session for %s (attempt %d/%d, provider=%s): %s",
                url,
                attempt,
                MAX_ATTEMPTS,
                last_driver_provider,
                e,
            )
            prefer_uc = False
            proxy = None
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(RETRY_DELAY_SEC)
        except (RemoteDisconnected, ProtocolError) as e:
            status = "FAILED"
            last_reason = "Remote disconnected"
            log.warning(
                "[worker_lib] Remote disconnect for %s (attempt %d/%d, provider=%s): %s",
                url,
                attempt,
                MAX_ATTEMPTS,
                last_driver_provider,
                e,
            )
            prefer_uc = False
            proxy = None
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(RETRY_DELAY_SEC)
        except (ReadTimeoutError, TimeoutError, socket.timeout) as e:
            status = "FAILED"
            last_reason = "Read timeout"
            log.warning(
                "[worker_lib] Read timeout for %s (attempt %d/%d, provider=%s): %s",
                url,
                attempt,
                MAX_ATTEMPTS,
                last_driver_provider,
                e,
            )
            prefer_uc = False
            proxy = None
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(RETRY_DELAY_SEC)
        except Exception as e:
            status = "FAILED"
            last_reason = f"Exception: {e}"
            log.exception("[worker_lib] Exception while processing %s", url)
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(RETRY_DELAY_SEC)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None

    duration = round(time.time() - t0, 2)
    mark_seen(
        url,
        content,
        name or "",
        email or "",
        {
            "status": status,
            "reason": last_reason,
            "comment_link": comment_link,
            "language": language,
            "attempts": attempts,
            "driver": last_driver_provider,
        },
    )
    return {
        "url": url,
        "status": status,
        "reason": last_reason,
        "comment_link": comment_link,
        "duration_sec": duration,
        "language": language,
        "attempts": attempts,
    }
