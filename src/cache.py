from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlsplit
from typing import Optional, Dict, Any

DEFAULT_CACHE_PATH = "data/forms_cache.json"

def _empty():
    return {"version": 1, "hosts": {}}

def load_cache(path: str = DEFAULT_CACHE_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists(): return _empty()
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return _empty()

def save_cache(cache: Dict[str, Any], path: str = DEFAULT_CACHE_PATH) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def _host_path(url: str):
    s = urlsplit(url); return (s.netloc.lower(), s.path or "/")

def lookup(cache: Dict[str, Any], url: str) -> Optional[Dict[str, Any]]:
    host, path = _host_path(url)
    h = cache.get("hosts", {}).get(host)
    if not h: return None
    return h.get(path) or h.get("default")

def upsert(cache: Dict[str, Any], url: str, selectors: Dict[str, Any], scope: str = "domain") -> None:
    host, path = _host_path(url)
    hosts = cache.setdefault("hosts", {})
    entry = hosts.setdefault(host, {})
    entry["default" if scope == "domain" else path] = selectors
