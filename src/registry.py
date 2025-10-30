# src/registry.py
from __future__ import annotations
import json
import hashlib
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

from .config import REGISTRY_DB

_LOCK = threading.RLock()
_INIT_ONCE = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(REGISTRY_DB, timeout=10, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_schema() -> None:
    global _INIT_ONCE
    if _INIT_ONCE:
        return
    with _LOCK:
        if _INIT_ONCE:
            return
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_registry (
                    key TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    name TEXT,
                    email TEXT,
                    meta_json TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_url ON seen_registry(url)")
        finally:
            conn.close()
        _INIT_ONCE = True


def _fingerprint(url: str, content: str, name: str, email: str) -> str:
    raw = "|".join((url.strip(), content.strip(), name.strip(), email.strip()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _make_key(url: str, content: str, name: str, email: str) -> str:
    return f"{url.strip()}::{_fingerprint(url, content, name, email)}"


def was_seen(url: str, content: str, name: str, email: str) -> bool:
    _ensure_schema()
    key = _make_key(url, content, name, email)
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("SELECT 1 FROM seen_registry WHERE key = ?", (key,))
            return cur.fetchone() is not None
        finally:
            conn.close()


def mark_seen(url: str, content: str, name: str, email: str, meta: Optional[Dict[str, Any]] = None) -> None:
    _ensure_schema()
    key = _make_key(url, content, name, email)
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    now = time.time()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO seen_registry (key, url, name, email, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    meta_json=excluded.meta_json,
                    created_at=excluded.created_at
                """,
                (key, url.strip(), name.strip(), email.strip(), meta_json, now),
            )
        finally:
            conn.close()


def get_meta(url: str, content: str, name: str, email: str) -> Optional[Dict[str, Any]]:
    """
    Lấy thông tin meta đã lưu (phục vụ việc debug / báo cáo).
    """
    _ensure_schema()
    key = _make_key(url, content, name, email)
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("SELECT meta_json FROM seen_registry WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row or not row[0]:
                return None
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        finally:
            conn.close()
