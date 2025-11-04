#!/usr/bin/env python3
"""Simple systemd-based health check for Redis and Celery."""

from __future__ import annotations

import subprocess
import sys


def check_service(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def main() -> int:
    failures: list[str] = []
    for service in ("redis-server", "celery"):
        if not check_service(service):
            failures.append(service)

    if failures:
        for service in failures:
            print(f"{service} DOWN", file=sys.stderr)
        return 1

    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
