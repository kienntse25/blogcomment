#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INPUT="data/comments.xlsx"
OUTPUT="data/comments_out.xlsx"
START_WORKER=1
USE_UC="${USE_UC:-false}"
FLUSH_REDIS=0
CONCURRENCY="${CELERY_CONCURRENCY:-2}"

usage() {
  cat <<'EOF'
Usage: scripts/run_campaign.sh [options]

Options:
  --input PATH         Excel input (default: data/comments.xlsx)
  --output PATH        Excel output (default: data/comments_out.xlsx)
  --no-worker          Don't start Celery worker (assume it's already running)
  --use-uc             Enable undetected-chromedriver for worker (USE_UC=true)
  --flush-redis        FLUSHALL before running (clears old tasks)
  --concurrency N      Celery worker concurrency (default: $CELERY_CONCURRENCY or 2)
  -h, --help           Show help

Flow:
  1) Run Gemini prefill: python -m src.generative_ai --input <input>
  2) Run Celery worker (optional)
  3) Run pipeline: python push_jobs_from_excel.py --input <input> --output <output> --limit 0
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --no-worker) START_WORKER=0; shift 1 ;;
    --use-uc) USE_UC=true; shift 1 ;;
    --flush-redis) FLUSH_REDIS=1; shift 1 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

VENV_DIR="${VENV_DIR:-}"
if [[ -z "${VENV_DIR}" ]]; then
  if [[ -d "${DIR}/.venv" ]]; then
    VENV_DIR="${DIR}/.venv"
  elif [[ -d "${DIR}/venv" ]]; then
    VENV_DIR="${DIR}/venv"
  else
    echo "Missing venv: create .venv or set VENV_DIR" >&2
    exit 1
  fi
fi

source "${VENV_DIR}/bin/activate"

if [[ -f "${DIR}/scripts/setup_env.sh" ]]; then
  # shellcheck disable=SC1091
  source "${DIR}/scripts/setup_env.sh"
fi

cd "${DIR}"

if [[ "${FLUSH_REDIS}" == "1" ]]; then
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli FLUSHALL || true
  else
    echo "redis-cli not found; skipping --flush-redis" >&2
  fi
fi

export USE_UC="${USE_UC}"

echo "[campaign] Gemini prefill -> ${INPUT}"
python -m src.generative_ai --input "${INPUT}" || true

WORKER_PID=""
cleanup() {
  if [[ -n "${WORKER_PID}" ]]; then
    kill "${WORKER_PID}" >/dev/null 2>&1 || true
    # Allow celery prefork children to exit
    sleep 1
  fi
}
trap cleanup EXIT

if [[ "${START_WORKER}" == "1" ]]; then
  echo "[campaign] Starting worker (concurrency=${CONCURRENCY}, USE_UC=${USE_UC})"
  celery -A src.tasks worker --loglevel=info --concurrency="${CONCURRENCY}" &
  WORKER_PID="$!"
  sleep 2
fi

echo "[campaign] Pipeline -> input=${INPUT} output=${OUTPUT}"
python push_jobs_from_excel.py --input "${INPUT}" --output "${OUTPUT}" --limit 0

echo "[campaign] Done: ${OUTPUT}"
