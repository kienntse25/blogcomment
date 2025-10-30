# src/tasks.py
from __future__ import annotations
import logging
from .celery_app import celery
from .worker_lib import run_one_link

log = logging.getLogger(__name__)

@celery.task(name="run_comment", bind=True)
def run_comment(self, job: dict) -> dict:
    """
    job: {'url','anchor','content','name','email','website'}
    """
    try:
        return run_one_link(job)
    except Exception as e:
        log.exception("run_comment error")
        return {
            "url": (job or {}).get("url", ""),
            "status": "FAILED",
            "reason": f"Exception: {e}",
            "comment_link": "",
            "duration_sec": 0.0,
            "language": "unknown",
            "attempts": 0,
        }
