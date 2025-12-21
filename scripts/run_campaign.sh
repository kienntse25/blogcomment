#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INPUT="data/comments.xlsx"
OUTPUT="data/comments_out.xlsx"
START_WORKER=1
USE_UC="${USE_UC:-true}"
FLUSH_REDIS=0
CLEAN_OUTPUT=0
CONCURRENCY="${CELERY_CONCURRENCY:-2}"
QUEUE="${CELERY_QUEUE:-}"
SKIP_GEMINI=0
REQUIRE_GEMINI=0
GEMINI_FLUSH_EVERY="${GEMINI_FLUSH_EVERY:-10}"
RESUME_OK=0

usage() {
  cat <<'EOF'
Usage: scripts/run_campaign.sh [options]

Options:
  --input PATH         Excel input (default: data/comments.xlsx)
  --output PATH        Excel output (default: data/comments_out.xlsx)
  --queue NAME         Campaign queue (default: env CELERY_QUEUE or camp_test)
  --resume-ok          Skip URLs already OK in output
  --skip-gemini        Skip Gemini prefill step
  --require-gemini     Fail if Gemini prefill fails
  --gemini-flush-every N  Save Excel after every N generated rows (default: env GEMINI_FLUSH_EVERY or 10)
  --no-worker          Don't start Celery worker (assume it's already running)
  --use-uc             Enable undetected-chromedriver for worker (USE_UC=true) (default)
  --no-uc              Disable undetected-chromedriver (USE_UC=false)
  --flush-redis        FLUSHALL before running (clears old tasks)
  --clean-output       Remove output + *_timeouts.xlsx before running
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
    --queue) QUEUE="$2"; shift 2 ;;
    --resume-ok) RESUME_OK=1; shift 1 ;;
    --skip-gemini) SKIP_GEMINI=1; shift 1 ;;
    --require-gemini) REQUIRE_GEMINI=1; shift 1 ;;
    --gemini-flush-every) GEMINI_FLUSH_EVERY="$2"; shift 2 ;;
    --no-worker) START_WORKER=0; shift 1 ;;
    --use-uc) USE_UC=true; shift 1 ;;
    --no-uc) USE_UC=false; shift 1 ;;
    --flush-redis) FLUSH_REDIS=1; shift 1 ;;
    --clean-output) CLEAN_OUTPUT=1; shift 1 ;;
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

if [[ "${CLEAN_OUTPUT}" == "1" ]]; then
  out_dir="$(dirname "${OUTPUT}")"
  out_base="$(basename "${OUTPUT}")"
  if [[ "${out_base,,}" == *.xlsx ]]; then
    out_stem="${out_base%.xlsx}"
  else
    out_stem="${out_base}"
  fi
  timeouts_path="${out_dir}/${out_stem}_timeouts.xlsx"
  rm -f "${OUTPUT}" "${timeouts_path}" push_jobs.log "logs/push_jobs_${out_stem}.log" "logs/push_jobs_${QUEUE}.log" || true
fi

if [[ "${FLUSH_REDIS}" == "1" ]]; then
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli FLUSHALL || true
  else
    echo "redis-cli not found; skipping --flush-redis" >&2
  fi
fi

export USE_UC="${USE_UC}"
if [[ -z "${QUEUE}" ]]; then
  QUEUE="camp_test"
fi
export CELERY_QUEUE="${QUEUE}"

if [[ "${SKIP_GEMINI}" == "1" ]]; then
  echo "[campaign] Skip Gemini prefill"
else
  echo "[campaign] Gemini prefill -> ${INPUT} (flush_every=${GEMINI_FLUSH_EVERY})"
  export GEMINI_FLUSH_EVERY
  if ! python -m src.generative_ai --input "${INPUT}"; then
    if [[ "${REQUIRE_GEMINI}" == "1" ]]; then
      echo "[campaign] Gemini prefill failed; aborting because --require-gemini is set" >&2
      exit 1
    fi
    echo "[campaign] Gemini prefill failed; continuing (set --require-gemini to stop on errors)" >&2
  fi
fi

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
  echo "[campaign] Starting worker (queue=${QUEUE}, concurrency=${CONCURRENCY}, USE_UC=${USE_UC})"
  celery -A src.tasks worker --loglevel=info --concurrency="${CONCURRENCY}" -Q "${QUEUE}" &
  WORKER_PID="$!"
  sleep 2
fi

echo "[campaign] Pipeline -> input=${INPUT} output=${OUTPUT} queue=${QUEUE}"
PIPE_ARGS=(--input "${INPUT}" --output "${OUTPUT}" --queue "${QUEUE}" --limit 0)
if [[ "${RESUME_OK}" == "1" ]]; then
  PIPE_ARGS+=(--resume-ok)
fi
python push_jobs_from_excel.py "${PIPE_ARGS[@]}"

echo "[campaign] Done: ${OUTPUT}"
