from __future__ import annotations
import requests, socket
from urllib.parse import urlparse

THIRD_PARTY_HINTS = [
    "disqus.com", "facebook.com/plugins/comments", "fb-comments",
    "intensedebate", "utteranc.es", "giscus.app", "talk.hyvor.com",
    "remark42", "commento.io", "data-hypercomments", "wpdiscuz",
]
LOGIN_HINTS = ["must be logged in", "you must be logged in", "đăng nhập để bình luận"]
CAPTCHA_HINTS = ["g-recaptcha", "hcaptcha", "captcha"]

def _dns_ok(host: str) -> bool:
    try: socket.getaddrinfo(host, None); return True
    except Exception: return False

def analyzable_row(row) -> tuple[bool, str]:
    url = str(row.get("url", "")).strip()
    if not url: return False, "Missing url"
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parts = urlparse(url)
    if not parts.netloc: return False, "Invalid URL"
    if not _dns_ok(parts.hostname or ""): return False, "DNS not resolved"

    try:
        r = requests.get(url, timeout=(4,6), headers={"User-Agent":"Mozilla/5.0"})
        html = r.text.lower()
        if any(x in html for x in THIRD_PARTY_HINTS): return False, "Third-party comments"
        if any(x in html for x in CAPTCHA_HINTS):     return False, "Captcha required"
        if any(x in html for x in LOGIN_HINTS):       return False, "Login required"
        if ("wp-comments-post" in html) or ("id=\"commentform\"" in html) or ("name=\"comment\"" in html):
            return True, ""
    except Exception:
        pass
    return True, ""  # không chắc nhưng cho qua để Selenium thử
