#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DIR}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/vps.sh worker [--concurrency N] [--queues Q1,Q2] [--loglevel info] [--pool prefork|threads|solo] [--pageload SEC] [--find-timeout SEC] [--comment-wait SEC]
  bash scripts/vps.sh run --input PATH --output PATH [--queue NAME] [--timeout SEC] [--flush-every N] [--resume-ok] [--no-anchor]
  bash scripts/vps.sh prefill --input PATH [--flush-every N] [--overwrite]
  bash scripts/vps.sh clean --output PATH
  bash scripts/vps.sh purge --queues Q1,Q2 [--db N] [--flushdb]

Notes:
  - worker reads proxies automatically from data/proxies.txt (if exists).
  - run writes output incrementally; use --resume-ok to skip URLs already OK in output.
EOF
}

need_venv() {
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
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
  if [[ -f "${DIR}/scripts/setup_env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${DIR}/scripts/setup_env.sh"
  fi
  export PYTHONPATH="${DIR}:${PYTHONPATH:-}"
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  -h|--help|"")
    usage
    exit 0
    ;;

  worker)
    need_venv
    concurrency="${CELERY_CONCURRENCY:-2}"
    queues="${CELERY_QUEUES:-${CELERY_QUEUE:-camp_test}}"
    loglevel="${CELERY_LOGLEVEL:-info}"
    pool="${CELERY_POOL:-}"
    pageload="${PAGELOAD_TIMEOUT:-}"
    find_timeout="${FIND_TIMEOUT:-}"
    comment_wait="${COMMENT_FORM_WAIT_SEC:-}"

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --concurrency) concurrency="$2"; shift 2 ;;
        --queues) queues="$2"; shift 2 ;;
        --loglevel) loglevel="$2"; shift 2 ;;
        --pool) pool="$2"; shift 2 ;;
        --pageload) pageload="$2"; shift 2 ;;
        --find-timeout) find_timeout="$2"; shift 2 ;;
        --comment-wait) comment_wait="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
      esac
    done

    export CELERY_CONCURRENCY="${concurrency}"
    export CELERY_QUEUES="${queues}"
    export CELERY_LOGLEVEL="${loglevel}"
    if [[ -n "${pool}" ]]; then
      export CELERY_POOL="${pool}"
    fi
    if [[ -n "${pageload}" ]]; then
      export PAGELOAD_TIMEOUT="${pageload}"
    fi
    if [[ -n "${find_timeout}" ]]; then
      export FIND_TIMEOUT="${find_timeout}"
    fi
    if [[ -n "${comment_wait}" ]]; then
      export COMMENT_FORM_WAIT_SEC="${comment_wait}"
    fi
    exec bash "${DIR}/scripts/run_worker.sh"
    ;;

  run)
    need_venv
    input=""
    output=""
    queue="${CELERY_QUEUE:-}"
    timeout="${PAGELOAD_TIMEOUT:-}"
    flush_every="${PUSH_FLUSH_EVERY:-}"
    resume_ok=0
    no_anchor=0

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --input) input="$2"; shift 2 ;;
        --output) output="$2"; shift 2 ;;
        --queue) queue="$2"; shift 2 ;;
        --timeout) timeout="$2"; shift 2 ;;
        --flush-every) flush_every="$2"; shift 2 ;;
        --resume-ok) resume_ok=1; shift 1 ;;
        --no-anchor) no_anchor=1; shift 1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
      esac
    done

    if [[ -z "${input}" || -z "${output}" ]]; then
      echo "Missing --input/--output" >&2
      usage
      exit 2
    fi
    if [[ -n "${timeout}" ]]; then
      export PAGELOAD_TIMEOUT="${timeout}"
    fi
    # Default per-output log file (avoid interleaved push_jobs.log when running many campaigns).
    if [[ -z "${PUSH_JOBS_LOG:-}" ]]; then
      mkdir -p "${DIR}/logs" || true
      out_base="$(basename "${output}")"
      if [[ "${out_base,,}" == *.xlsx ]]; then
        out_stem="${out_base%.xlsx}"
      else
        out_stem="${out_base}"
      fi
      if [[ -n "${queue}" ]]; then
        export PUSH_JOBS_LOG="logs/push_jobs_${queue}.log"
      else
        export PUSH_JOBS_LOG="logs/push_jobs_${out_stem}.log"
      fi
    fi
    args=(--input "${input}" --output "${output}" --limit 0)
    if [[ -n "${queue}" ]]; then
      args+=(--queue "${queue}")
    fi
    if [[ -n "${timeout}" ]]; then
      # Also enforce per-task timeout in the pipeline so one stuck URL doesn't block the whole run.
      args+=(--task-timeout "${timeout}")
    fi
    if [[ -n "${flush_every}" ]]; then
      args+=(--flush-every "${flush_every}")
    fi
    if [[ "${resume_ok}" == "1" ]]; then
      args+=(--resume-ok)
    fi
    if [[ "${no_anchor}" == "1" ]]; then
      args+=(--no-attach-anchor)
    fi
    python push_jobs_from_excel.py "${args[@]}"
    ;;

  prefill)
    need_venv
    input=""
    flush_every="${GEMINI_FLUSH_EVERY:-10}"
    overwrite=0
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --input) input="$2"; shift 2 ;;
        --flush-every) flush_every="$2"; shift 2 ;;
        --overwrite) overwrite=1; shift 1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
      esac
    done
    if [[ -z "${input}" ]]; then
      echo "Missing --input" >&2
      usage
      exit 2
    fi
    export GEMINI_FLUSH_EVERY="${flush_every}"
    cmd=(python -m src.generative_ai --input "${input}" --flush-every "${flush_every}")
    if [[ "${overwrite}" == "1" ]]; then
      cmd+=(--overwrite)
    fi
    "${cmd[@]}"
    ;;

  clean)
    output=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --output) output="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
      esac
    done
    if [[ -z "${output}" ]]; then
      echo "Missing --output" >&2
      usage
      exit 2
    fi
    out_dir="$(dirname "${output}")"
    out_base="$(basename "${output}")"
    if [[ "${out_base,,}" == *.xlsx ]]; then
      out_stem="${out_base%.xlsx}"
    else
      out_stem="${out_base}"
    fi
    rm -f "${output}" "${out_dir}/${out_stem}_timeouts.xlsx" push_jobs.log "logs/push_jobs_${out_stem}.log" || true
    if [[ -n "${CELERY_QUEUE:-}" ]]; then
      rm -f "logs/push_jobs_${CELERY_QUEUE}.log" || true
    fi
    echo "Cleaned: ${output}"
    ;;

  purge)
    db="${REDIS_DB:-0}"
    queues=""
    flushdb=0
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --queues) queues="$2"; shift 2 ;;
        --db) db="$2"; shift 2 ;;
        --flushdb) flushdb=1; shift 1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
      esac
    done
    if [[ "${flushdb}" == "1" ]]; then
      redis-cli -n "${db}" FLUSHDB
      echo "Redis DB ${db} flushed."
      exit 0
    fi
    if [[ -z "${queues}" ]]; then
      echo "Missing --queues" >&2
      usage
      exit 2
    fi
    IFS=',' read -r -a qs <<< "${queues}"
    for q in "${qs[@]}"; do
      q="$(echo "${q}" | xargs)"
      [[ -z "${q}" ]] && continue
      redis-cli -n "${db}" DEL "${q}" >/dev/null || true
      echo "Purged queue key: ${q} (db=${db})"
    done
    ;;

  *)
    echo "Unknown command: ${cmd}" >&2
    usage
    exit 2
    ;;
esac
