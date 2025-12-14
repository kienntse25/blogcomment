#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${DIR}/.venv/bin/activate"

python push_jobs_from_excel.py "$@"
