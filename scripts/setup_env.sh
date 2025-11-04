#!/usr/bin/env bash
# Load common environment variables for the blog comment tool.

export HEADLESS=true
export MAX_ATTEMPTS=2
export RETRY_DELAY_SEC=3.0
export CELERY_BROKER_URL=redis://localhost:6379/0
export CELERY_RESULT_BACKEND=redis://localhost:6379/0
