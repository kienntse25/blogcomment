#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DIR}"

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

export PYTHONPATH="${DIR}:${PYTHONPATH:-}"

CONCURRENCY="${CELERY_CONCURRENCY:-2}"
QUEUES="${CELERY_QUEUES:-${CELERY_QUEUE:-camp_test}}"
LOGLEVEL="${CELERY_LOGLEVEL:-info}"
POOL="${CELERY_POOL:-}"

# If UC is enabled, prefork children are "daemonic" and UC may fail with:
# "daemonic processes are not allowed to have children".
# Threads pool keeps execution in the main process and is usually compatible with UC.
if [[ -z "${POOL}" ]]; then
  if [[ "${USE_UC:-}" =~ ^(1|true|yes|on)$ ]]; then
    POOL="threads"
  fi
fi

EXTRA_ARGS=()
if [[ -n "${QUEUES}" ]]; then
  EXTRA_ARGS+=("-Q" "${QUEUES}")
fi
if [[ -n "${CONCURRENCY}" ]]; then
  EXTRA_ARGS+=("--concurrency=${CONCURRENCY}")
fi
if [[ -n "${POOL}" ]]; then
  EXTRA_ARGS+=("--pool=${POOL}")
fi

# These improve stability for browser workers (avoid one child holding too much state).
EXTRA_ARGS+=("--prefetch-multiplier=1")
EXTRA_ARGS+=("--max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD:-20}")

exec celery -A src.tasks worker --loglevel="${LOGLEVEL}" "${EXTRA_ARGS[@]}"
