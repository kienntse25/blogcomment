#!/usr/bin/env bash
# Load common environment variables for the blog comment tool.

export HEADLESS=true
export MAX_ATTEMPTS=2
export RETRY_DELAY_SEC=3.0
export CELERY_BROKER_URL=redis://localhost:6379/0
export CELERY_RESULT_BACKEND=redis://localhost:6379/0
# export PROXY_URL="http://user:pass@host:port"
# export PROXY_LIST="http://proxy1:port,http://proxy2:port"
# export PROXY_FILE="data/proxies.txt"
