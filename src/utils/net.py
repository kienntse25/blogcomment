# src/utils/net.py
from __future__ import annotations
import os
import logging
from typing import Tuple, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import ProtocolError as Urllib3ProtocolError

logger = logging.getLogger(__name__)

def _session() -> requests.Session:
    s = requests.Session()
    # Retry chiến lược: retry 3 lần với backoff
    retry = Retry(
        total=3,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=(403, 408, 409, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    ua = os.getenv("USER_AGENT", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
    s.headers.update({"User-Agent": ua, "Accept": "*/*"})
    return s

def soft_reachable(url: str, timeout: Optional[float] = None) -> Tuple[bool, str, Optional[int]]:
    """
    HEAD trước (nhẹ), nếu bị chặn HEAD thì fallback GET stream=True.
    Không raise: luôn trả (ok, reason, status_code).
    """
    timeout = timeout or float(os.getenv("PRECHECK_TIMEOUT", "6"))
    s = _session()
    try:
        r = s.head(url, timeout=timeout, allow_redirects=True, verify=False)
        code = r.status_code
        if 200 <= code < 400:
            return True, f"HEAD {code}", code
        # Nếu từ chối HEAD (405) hay chặn, thử GET nhẹ
        if code in (401, 403, 405, 406, 409, 410, 429, 500, 502, 503, 504):
            gr = s.get(url, timeout=timeout, allow_redirects=True, stream=True, verify=False)
            gcode = gr.status_code
            if 200 <= gcode < 400:
                return True, f"GET {gcode}", gcode
            return False, f"GET {gcode}", gcode
        return False, f"HEAD {code}", code
    except (requests.exceptions.SSLError, requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout, requests.exceptions.ProxyError,
            requests.exceptions.ConnectionError, Urllib3ProtocolError) as e:
        # KHÔNG chặn—chỉ cảnh báo, để Selenium tiếp tục
        logger.warning(f"[precheck] Soft fail for {url} -> {e.__class__.__name__}: {e}")
        return False, f"soft-fail:{e.__class__.__name__}", None
    except Exception as e:
        logger.warning(f"[precheck] Soft fail for {url} -> {e}")
        return False, f"soft-fail:{type(e).__name__}", None
