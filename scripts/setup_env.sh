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
# export PROXY_XLSX="data/proxies.xlsx"
# Nếu file proxy chỉ chứa "PORT" (loại FPT/VNPT/Viettel port), set thêm:
# export PROXY_HOST="proxy.provider.com"    # không kèm port
# export PROXY_SCHEME="http"               # hoặc socks5
# export PROXY_USER="username"             # nếu nhà cung cấp yêu cầu auth
# export PROXY_PASS="password"
# Nếu nhà cung cấp trả dạng "IP:PORT:USER:PASS" (VD tmproxy), bạn có thể dán trực tiếp vào file proxy.
