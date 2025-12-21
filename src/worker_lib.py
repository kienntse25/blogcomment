# src/worker_lib.py
from __future__ import annotations
import os
import time
import socket
import logging
import random
from contextlib import contextmanager
import undetected_chromedriver as uc
from urllib.parse import urlparse
from selenium.common.exceptions import InvalidSessionIdException
from urllib3.exceptions import ProtocolError, ReadTimeoutError
from http.client import RemoteDisconnected
from pathlib import Path
import re

from .config import (
    HEADLESS,
    RETRY_DRIVER_VERSIONS,
    MAX_ATTEMPTS,
    RETRY_DELAY_SEC,
    RESPECT_ROBOTS,
    USER_AGENT,
    ALLOWED_DOMAINS_FILE,
    SCREENSHOT_ON_FAIL,
    FAILSHOT_DIR,
    PAGE_LOAD_STRATEGY,
    DISABLE_IMAGES,
    PROXY_URL,
    PROXY_LIST,
    PROXY_FILE,
    PROXY_XLSX,
    PROXY_SCHEME,
    PROXY_HOST,
    PROXY_USER,
    PROXY_PASS,
)
from .registry import was_seen, mark_seen
from . import commenter
from .driver_factory import make_selenium_driver
from .utils.allowlist import is_url_allowed
from .utils.robots import is_allowed as robots_allowed

log = logging.getLogger("worker_lib")

_FILE_PROXY_CACHE: list[str] | None = None
_FILE_PROXY_MTIME: float | None = None
_XLSX_PROXY_CACHE: list[str] | None = None
_XLSX_PROXY_MTIME: float | None = None
_SAN_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_filename(text: str) -> str:
    s = _SAN_RE.sub("_", (text or "").strip())
    return s[:120] if s else "unknown"


def _save_fail_artifacts(driver, url: str, reason: str) -> dict[str, str]:
    """
    Save screenshot + HTML for debugging (optional).
    Returns {"screenshot": path, "html": path} (may be empty).
    """
    if not SCREENSHOT_ON_FAIL:
        return {}
    try:
        Path(FAILSHOT_DIR).mkdir(parents=True, exist_ok=True)
    except Exception:
        return {}

    host = ""
    try:
        host = (urlparse(url).netloc or "").split("@")[-1]
    except Exception:
        host = ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{_sanitize_filename(host)}"

    out: dict[str, str] = {}
    png = str(Path(FAILSHOT_DIR) / f"{base}.png")
    htmlp = str(Path(FAILSHOT_DIR) / f"{base}.html")
    metap = str(Path(FAILSHOT_DIR) / f"{base}.txt")
    try:
        driver.save_screenshot(png)
        out["screenshot"] = png
    except Exception:
        pass
    try:
        src = driver.page_source or ""
        Path(htmlp).write_text(src, encoding="utf-8", errors="ignore")
        out["html"] = htmlp
    except Exception:
        pass
    try:
        Path(metap).write_text(f"url={url}\nreason={reason}\n", encoding="utf-8", errors="ignore")
        out["meta"] = metap
    except Exception:
        pass
    return out


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


def _load_proxies_from_xlsx() -> list[str]:
    global _XLSX_PROXY_CACHE, _XLSX_PROXY_MTIME
    if not PROXY_XLSX:
        return []
    try:
        st = os.stat(PROXY_XLSX)
    except FileNotFoundError:
        _XLSX_PROXY_CACHE = None
        _XLSX_PROXY_MTIME = None
        return []
    except OSError:
        return []

    if _XLSX_PROXY_CACHE is not None and _XLSX_PROXY_MTIME == st.st_mtime:
        return _XLSX_PROXY_CACHE

    try:
        import pandas as pd  # type: ignore
    except Exception:
        return []

    try:
        df = pd.read_excel(PROXY_XLSX, engine="openpyxl")
    except Exception as exc:
        log.warning("Unable to read proxy xlsx %s: %s", PROXY_XLSX, exc)
        return []

    if df.empty:
        _XLSX_PROXY_CACHE = []
        _XLSX_PROXY_MTIME = st.st_mtime
        return []

    target_col = None
    for col in df.columns:
        col_norm = str(col).strip().lower()
        if col_norm in {"proxy", "proxies", "url"}:
            target_col = col
            break
    if target_col is None:
        target_col = df.columns[0]

    proxies: list[str] = []
    for val in df[target_col].tolist():
        if val is None:
            continue
        text = str(val).strip()
        if not text or text.lower() in {"nan", "none"}:
            continue
        if text.startswith("#"):
            continue
        proxies.append(text)

    _XLSX_PROXY_CACHE = proxies
    _XLSX_PROXY_MTIME = st.st_mtime
    return proxies


def _use_uc() -> bool:
    # UC can be unstable on some Chrome builds; keep it opt-in.
    return os.getenv("USE_UC", "false").strip().lower() in {"1", "true", "yes", "on"}


def _clear_uc_cache() -> None:
    # UC caches patched driver under these locations (Linux & macOS). Clearing helps with
    # "Text file busy" / missing binary issues after concurrent patching.
    home = os.path.expanduser("~")
    linux_cache = os.path.join(home, ".local", "share", "undetected_chromedriver")
    mac_cache = os.path.join(home, "Library", "Application Support", "undetected_chromedriver")
    for path in (linux_cache, mac_cache):
        try:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            continue


@contextmanager
def _uc_patch_lock():
    """
    Serializes UC patching across Celery prefork workers to avoid:
    - Errno 26: Text file busy
    - missing chromedriver under UC cache dir
    """
    try:
        import fcntl  # Unix only
    except Exception:
        yield
        return

    lock_path = os.getenv("UC_LOCK_FILE", "/tmp/undetected_chromedriver.lock")
    timeout_sec = float(os.getenv("UC_LOCK_TIMEOUT_SEC", "60"))
    start = time.time()
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start >= timeout_sec:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    break
                time.sleep(0.2)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass


def _proxy_base_url() -> str | None:
    """
    Build base proxy URL from env for "port-only" proxies.
    Example: PROXY_HOST=proxy.provider.com, PROXY_USER/PASS optional.
    Returns like: http://user:pass@proxy.provider.com
    """
    if not PROXY_HOST:
        return None
    host = PROXY_HOST.strip()
    scheme = (PROXY_SCHEME or "http").strip() or "http"

    if "://" in host:
        parsed = urlparse(host)
        scheme = parsed.scheme or scheme
        netloc = parsed.netloc or parsed.path
    else:
        netloc = host

    if "@" in netloc:
        return f"{scheme}://{netloc}"
    if PROXY_USER and PROXY_PASS:
        return f"{scheme}://{PROXY_USER}:{PROXY_PASS}@{netloc}"
    return f"{scheme}://{netloc}"


def _normalize_proxy_entry(raw: str) -> str | None:
    """
    Accept:
      - full URL: http://user:pass@host:port
      - host:port
      - port-only (digits), expanded using PROXY_HOST (+ optional auth envs)
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none"} or text.startswith("#"):
        return None

    if "://" in text:
        return text

    # Excel often turns numeric ports into "12345.0"
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    # Common provider format: host:port:user:pass (e.g. tmproxy)
    parts = text.split(":")
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        scheme = (PROXY_SCHEME or "http").strip() or "http"
        return f"{scheme}://{user}:{password}@{host}:{port}"

    if text.isdigit():
        base = _proxy_base_url()
        if not base:
            return None
        return f"{base}:{text}"

    if ":" in text and text.rsplit(":", 1)[-1].isdigit():
        # host:port -> ensure scheme/auth
        base = _proxy_base_url()
        if base:
            # If PROXY_HOST also provided, only use its auth+scheme, but keep the given host:port.
            parsed = urlparse(base)
            scheme = parsed.scheme or (PROXY_SCHEME or "http")
            auth = ""
            if parsed.username and parsed.password:
                auth = f"{parsed.username}:{parsed.password}@"
            return f"{scheme}://{auth}{text}"
        return f"http://{text}"

    return text


def _proxy_candidates(exclude: str | None = None) -> list[str]:
    raw: list[str] = []
    if PROXY_LIST:
        raw.extend(PROXY_LIST)
    raw.extend(_load_proxies_from_xlsx() or [])
    raw.extend(_load_proxies_from_file() or [])
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        p = _normalize_proxy_entry(item)
        if not p:
            continue
        if exclude and p == exclude:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _pick_proxy() -> str | None:
    candidates = _proxy_candidates()
    if candidates:
        return random.choice(candidates)
    return PROXY_URL


def _pick_proxy_excluding(exclude: str | None) -> str | None:
    candidates = _proxy_candidates(exclude=exclude)
    if candidates:
        return random.choice(candidates)
    return None


def _make_driver_uc(version_main: int = 0, proxy: str | None = None):
    """
    version_main = 0 → để UC auto chọn.
    Nếu lỗi version mismatch, sẽ fallback sang các version trong RETRY_DRIVER_VERSIONS.
    """
    if os.getenv("UC_CLEAR_CACHE", "false").strip().lower() in {"1", "true", "yes", "on"}:
        with _uc_patch_lock():
            _clear_uc_cache()

    def _common_flags() -> list[str]:
        flags_str = os.getenv(
            "CHROME_FLAGS",
            "--headless=new --disable-gpu --disable-software-rasterizer "
            "--no-sandbox --disable-dev-shm-usage --window-size=1200,2000 "
            "--disable-blink-features=AutomationControlled "
            "--disable-features=IsolateOrigins,site-per-process "
            "--remote-allow-origins=*",
        )
        flags = [f for f in flags_str.split() if f]
        if not HEADLESS:
            flags = [f for f in flags if not f.startswith("--headless")]
        return flags

    opts = uc.ChromeOptions()
    try:
        if PAGE_LOAD_STRATEGY in {"eager", "none", "normal"}:
            opts.page_load_strategy = PAGE_LOAD_STRATEGY
    except Exception:
        pass
    for f in _common_flags():
        opts.add_argument(f)
    if HEADLESS:
        opts.headless = True
    # window-size fallback (nếu CHROME_FLAGS không set)
    opts.add_argument("--window-size=1280,2400")

    ua = os.getenv("USER_AGENT")
    if ua:
        opts.add_argument(f"--user-agent={ua}")

    if DISABLE_IMAGES:
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.geolocation": 2,
        }
        try:
            opts.add_experimental_option("prefs", prefs)
        except Exception:
            pass
        opts.add_argument("--blink-settings=imagesEnabled=false")

    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")

    def _create():
        use_subprocess = os.getenv("UC_USE_SUBPROCESS", "true").strip().lower() in {"1", "true", "yes", "on"}
        return uc.Chrome(
            options=opts,
            version_main=(version_main or None),
            use_subprocess=use_subprocess,
        )

    try:
        with _uc_patch_lock():
            driver = _create()
    except FileNotFoundError:
        with _uc_patch_lock():
            _clear_uc_cache()
            time.sleep(1)
            driver = _create()
    except OSError as exc:
        # Errno 26: "Text file busy" happens when multiple processes patch/use the same binary.
        if getattr(exc, "errno", None) == 26:
            with _uc_patch_lock():
                _clear_uc_cache()
                time.sleep(1)
                driver = _create()
        else:
            raise
    try:
        driver.set_window_size(1280, 2400)
    except Exception:
        pass
    return driver


def _acquire_driver(prefer_uc: bool = True, proxy: str | None = None):
    errors: list[str] = []
    if prefer_uc and _use_uc():
        for idx, ver in enumerate(RETRY_DRIVER_VERSIONS, start=1):
            try:
                driver = _make_driver_uc(ver, proxy=proxy)
                # Smoke test: sometimes chromedriver/Chrome dies immediately after creation,
                # resulting in "Connection refused" on the first command. Catch it here so
                # we can try another major (or fall back to Selenium) instead of wasting attempts.
                try:
                    driver.execute_script("return 1;")
                except Exception as exc:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    raise RuntimeError(f"uc session died after init: {exc}") from exc
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
    # DNS failures can be proxy-specific. If we have multiple proxies, allow a retry to pick a new one.
    if any(tok in reason_lower for tok in ("dns error", "dns not resolved", "name or service not known")):
        try:
            return len(_proxy_candidates()) > 1
        except Exception:
            return False
    fatal_tokens = (
        "login",
        "captcha",
        "already attempted",
        "no submit button",
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

    # Optional guardrails: allowlist + robots.txt (for controlled/authorized environments).
    if ALLOWED_DOMAINS_FILE and not is_url_allowed(url):
        return {
            "url": url,
            "status": "FAILED",
            "reason": f"Not allowed by allowlist ({ALLOWED_DOMAINS_FILE})",
            "comment_link": "",
            "duration_sec": 0.0,
            "language": "unknown",
            "attempts": 0,
        }
    if RESPECT_ROBOTS and not robots_allowed(url, USER_AGENT):
        return {
            "url": url,
            "status": "FAILED",
            "reason": "Disallowed by robots.txt",
            "comment_link": "",
            "duration_sec": 0.0,
            "language": "unknown",
            "attempts": 0,
        }

    # Không SKIP theo registry: link nào được paste thì luôn thử chạy.

    attempts = 0
    last_reason = ""
    comment_link = ""
    status = "FAILED"
    language = "unknown"
    prefer_uc = True
    proxy = _pick_proxy()
    last_driver_provider = "none"

    extra = 0
    try:
        extra = int(os.getenv("EXTRA_ATTEMPTS_ON_DRIVER_FAIL", "1"))
    except ValueError:
        extra = 1
    max_attempts = max(1, MAX_ATTEMPTS + max(0, extra))

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        driver = None
        try:
            # Nếu retry, thử proxy khác (hoặc no-proxy) để tăng tỷ lệ thành công.
            if attempt > 1:
                proxy = _pick_proxy_excluding(proxy)

            driver, driver_provider, last_driver_err = _acquire_driver(
                prefer_uc=prefer_uc,
                proxy=proxy,
            )
            if not driver:
                last_reason = f"WebDriver init fail: {last_driver_err}"
                log.error("[worker_lib] Unable to create driver for %s: %s", url, last_driver_err)
                prefer_uc = False
                proxy = None
                if attempt == max_attempts:
                    break
                time.sleep(RETRY_DELAY_SEC)
                continue
            last_driver_provider = driver_provider

            ok, rsn, cm_link = commenter.process_job(driver, job)
            language = commenter.detect_language(driver) or "unknown"
            status = "OK" if ok else "FAILED"
            last_reason = rsn
            comment_link = cm_link or ""

            if ok:
                break
            if attempt == max_attempts:
                arts = _save_fail_artifacts(driver, url, rsn)
                if arts:
                    log.info("[worker_lib] Saved fail artifacts for %s: %s", url, arts)

            if not _should_retry(rsn) or attempt == max_attempts:
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
            if attempt == max_attempts:
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
            if attempt == max_attempts:
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
            if attempt == max_attempts:
                break
            time.sleep(RETRY_DELAY_SEC)
        except Exception as e:
            status = "FAILED"
            last_reason = f"Exception: {e}"
            log.exception("[worker_lib] Exception while processing %s", url)
            prefer_uc = False
            proxy = None
            if attempt == max_attempts:
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
