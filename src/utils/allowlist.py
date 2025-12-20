from __future__ import annotations

import os
from urllib.parse import urlparse

_CACHE: list[str] | None = None
_CACHE_MTIME: float | None = None


def _default_allowlist_file() -> str | None:
    path = (os.getenv("ALLOWED_DOMAINS_FILE") or "").strip()
    if path:
        return path
    default_path = os.path.join("data", "allowed_domains.txt")
    return default_path if os.path.exists(default_path) else None


def _load_rules(path: str) -> list[str]:
    rules: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # accept full URLs or plain domains
            if "://" in s:
                try:
                    s = urlparse(s).netloc
                except Exception:
                    pass
            s = s.strip().lower()
            if s.startswith("."):
                s = s[1:]
            if s:
                rules.append(s)
    return rules


def get_allowlist_rules() -> list[str] | None:
    """
    Returns a list of domain rules, or None if no allowlist configured.
    Rules examples:
      - example.com           (matches example.com and any subdomain)
      - *.example.com         (matches subdomains only, not example.com)
    """
    global _CACHE, _CACHE_MTIME
    path = _default_allowlist_file()
    if not path:
        _CACHE = None
        _CACHE_MTIME = None
        return None
    try:
        st = os.stat(path)
    except OSError:
        _CACHE = None
        _CACHE_MTIME = None
        return None
    if _CACHE is not None and _CACHE_MTIME == st.st_mtime:
        return _CACHE
    try:
        rules = _load_rules(path)
    except OSError:
        _CACHE = None
        _CACHE_MTIME = None
        return None
    _CACHE = rules
    _CACHE_MTIME = st.st_mtime
    return rules


def _match_domain(domain: str, rule: str) -> bool:
    d = domain.strip().lower()
    r = rule.strip().lower()
    if not d or not r:
        return False
    if r.startswith("*."):
        base = r[2:]
        return d.endswith("." + base)
    # default: match exact OR any subdomain
    return d == r or d.endswith("." + r)


def is_url_allowed(url: str) -> bool:
    """
    If allowlist is configured, only allow URLs whose netloc matches any rule.
    If allowlist is not configured, returns True.
    """
    rules = get_allowlist_rules()
    if not rules:
        return True
    try:
        host = urlparse(url).netloc.split("@")[-1].split(":")[0].strip().lower()
    except Exception:
        return False
    if not host:
        return False
    return any(_match_domain(host, rule) for rule in rules)

