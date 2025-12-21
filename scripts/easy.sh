#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DIR}"

usage() {
  cat <<'EOF'
Non-tech runner (authorized domains only)

Usage:
  bash scripts/easy.sh setup
  bash scripts/easy.sh run --queue NAME --input data/in.xlsx [--output data/out.xlsx] [--phase fast|slow] [--two-pass]

Requirements:
  - You must provide an allowlist file: data/allowed_domains.txt (one domain per line).
    The easy runner will refuse to run without it to prevent accidental misuse.
  - Redis must be running (CELERY uses redis://localhost:6379/0).

Examples:
  bash scripts/easy.sh setup
  bash scripts/easy.sh run --queue camp_a --input data/comments_a.xlsx --two-pass

What it does:
  - Purges old Redis tasks for the queue
  - Starts a Celery worker in tmux (if available) or prints manual commands
  - Runs the pipeline and writes:
      output.xlsx, output_timeouts.xlsx, output_no_comment.xlsx
EOF
}

need_project() {
  if [[ ! -f "${DIR}/push_jobs_from_excel.py" ]]; then
    echo "Run from project root; missing push_jobs_from_excel.py" >&2
    exit 1
  fi
}

need_venv() {
  VENV_DIR="${VENV_DIR:-}"
  if [[ -z "${VENV_DIR}" ]]; then
    if [[ -d "${DIR}/.venv" ]]; then
      VENV_DIR="${DIR}/.venv"
    elif [[ -d "${DIR}/venv" ]]; then
      VENV_DIR="${DIR}/venv"
    else
      echo "Missing venv. Run: bash scripts/easy.sh setup" >&2
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

require_allowlist() {
  allow="${ALLOWED_DOMAINS_FILE:-data/allowed_domains.txt}"
  if [[ ! -f "${allow}" ]]; then
    echo "Missing allowlist: ${allow}" >&2
    echo "Create it with one domain per line, e.g.:" >&2
    echo "  example.com" >&2
    echo "  blog.example.com" >&2
    exit 2
  fi
  export ALLOWED_DOMAINS_FILE="${allow}"
}

setup_cmd() {
  need_project
  if [[ ! -d "${DIR}/.venv" ]]; then
    python3 -m venv "${DIR}/.venv"
  fi
  # shellcheck disable=SC1091
  source "${DIR}/.venv/bin/activate"
  python -m pip install --upgrade pip wheel
  python -m pip install -r requirements.txt
  mkdir -p logs data
  if [[ ! -f "data/proxies.txt" && -f "data/proxies.example.txt" ]]; then
    cp data/proxies.example.txt data/proxies.txt
  fi
  echo "Setup done."
  echo "- Edit proxies: data/proxies.txt (optional)"
  echo "- Add allowlist: data/allowed_domains.txt (required for easy runner)"
}

phase_env_fast() {
  export USE_UC="${USE_UC:-false}"
  export PAGE_LOAD_STRATEGY="${PAGE_LOAD_STRATEGY:-eager}"
  export DISABLE_IMAGES="${DISABLE_IMAGES:-true}"
  export STOP_LOADING_ON_FORM_FOUND="${STOP_LOADING_ON_FORM_FOUND:-true}"
  export SEARCH_IFRAMES="${SEARCH_IFRAMES:-false}"
  export MAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"
  export RETRY_DELAY_SEC="${RETRY_DELAY_SEC:-1}"
  export AFTER_SUBMIT_PAUSE="${AFTER_SUBMIT_PAUSE:-1}"
  export PAGELOAD_TIMEOUT="${PAGELOAD_TIMEOUT:-40}"
  export FIND_TIMEOUT="${FIND_TIMEOUT:-6}"
  export COMMENT_FORM_WAIT_SEC="${COMMENT_FORM_WAIT_SEC:-6}"
}

phase_env_slow() {
  export USE_UC="${USE_UC:-false}"
  export PAGE_LOAD_STRATEGY="${PAGE_LOAD_STRATEGY:-eager}"
  export DISABLE_IMAGES="${DISABLE_IMAGES:-true}"
  export STOP_LOADING_ON_FORM_FOUND="${STOP_LOADING_ON_FORM_FOUND:-true}"
  export SEARCH_IFRAMES="${SEARCH_IFRAMES:-true}"
  export MAX_ATTEMPTS="${MAX_ATTEMPTS:-2}"
  export RETRY_DELAY_SEC="${RETRY_DELAY_SEC:-2}"
  export AFTER_SUBMIT_PAUSE="${AFTER_SUBMIT_PAUSE:-1}"
  export PAGELOAD_TIMEOUT="${PAGELOAD_TIMEOUT:-60}"
  export FIND_TIMEOUT="${FIND_TIMEOUT:-10}"
  export COMMENT_FORM_WAIT_SEC="${COMMENT_FORM_WAIT_SEC:-25}"
}

run_cmd() {
  need_project
  need_venv
  require_allowlist

  queue=""
  input=""
  output=""
  phase="fast"
  two_pass=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --queue) queue="$2"; shift 2 ;;
      --input) input="$2"; shift 2 ;;
      --output) output="$2"; shift 2 ;;
      --phase) phase="$2"; shift 2 ;;
      --two-pass) two_pass=1; shift 1 ;;
      -h|--help) usage; exit 0 ;;
      *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
  done
  if [[ -z "${queue}" || -z "${input}" ]]; then
    echo "Missing --queue/--input" >&2
    usage
    exit 2
  fi
  if [[ -z "${output}" ]]; then
    output="data/out_${queue}.xlsx"
  fi

  case "${phase}" in
    fast) phase_env_fast ;;
    slow) phase_env_slow ;;
    *) echo "Invalid --phase: ${phase} (use fast|slow)" >&2; exit 2 ;;
  esac

  mkdir -p logs
  export PUSH_JOBS_LOG="logs/push_jobs_${queue}.log"
  export CELERY_QUEUE="${queue}"

  echo "[easy] Purge queue=${queue}"
  redis-cli -n 0 DEL "${queue}" >/dev/null 2>&1 || true

  if command -v tmux >/dev/null 2>&1; then
    session="blogcomment_${queue}"
    tmux kill-session -t "${session}" >/dev/null 2>&1 || true
    tmux new-session -d -s "${session}" -n run
    tmux send-keys -t "${session}:run" "cd '${DIR}' && source '${VENV_DIR}/bin/activate' && export PYTHONPATH='${DIR}' && export C_FORCE_ROOT=1 && bash scripts/vps.sh worker --concurrency 2 --queues '${queue}' --pageload '${PAGELOAD_TIMEOUT}' --find-timeout '${FIND_TIMEOUT}' --comment-wait '${COMMENT_FORM_WAIT_SEC}'" C-m
    tmux split-window -v -t "${session}:run"
    tmux send-keys -t "${session}:run.1" "cd '${DIR}' && source '${VENV_DIR}/bin/activate' && export PYTHONPATH='${DIR}' && python3 push_jobs_from_excel.py --queue '${queue}' --input '${input}' --output '${output}' --limit 0 --task-timeout 240 --flush-every 50 --resume-ok" C-m
    if [[ "${two_pass}" == "1" ]]; then
      tmux send-keys -t "${session}:run.1" " && python3 push_jobs_from_excel.py --queue '${queue}' --input '${output%.xlsx}_no_comment.xlsx' --output '${output%.xlsx}_retry_no_comment.xlsx' --limit 0 --task-timeout 240 --flush-every 20" C-m
    fi
    tmux attach -t "${session}"
    return
  fi

  cat <<EOF
tmux not found. Open 2 terminals and run:

Terminal 1:
  export C_FORCE_ROOT=1
  bash scripts/vps.sh worker --concurrency 2 --queues ${queue} --pageload ${PAGELOAD_TIMEOUT} --find-timeout ${FIND_TIMEOUT} --comment-wait ${COMMENT_FORM_WAIT_SEC}

Terminal 2:
  python3 push_jobs_from_excel.py --queue ${queue} --input ${input} --output ${output} --limit 0 --task-timeout 240 --flush-every 50 --resume-ok
EOF
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  -h|--help|"") usage ;;
  setup) setup_cmd ;;
  run) run_cmd "$@" ;;
  *) echo "Unknown command: ${cmd}" >&2; usage; exit 2 ;;
esac

