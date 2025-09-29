set -euo pipefail
cd "$(dirname "$0")"
INPUT="data/comments.xlsx"
STAMP=$(date +%Y%m%d-%H%M)
OUT="data/comments_out_${STAMP}.xlsx"
CACHE="data/forms_cache.json"

WORKERS=${WORKERS:-4}
CHUNK=${CHUNK:-80}
SAVE_EVERY=${SAVE_EVERY:-1}

# tốc độ/độ ổn định (override .env cho phiên chạy này)
export HEADLESS=${HEADLESS:-true}
export FIND_TIMEOUT=${FIND_TIMEOUT:-3}
export AFTER_SUBMIT_PAUSE=${AFTER_SUBMIT_PAUSE:-0.6}
export PAUSE_MIN=${PAUSE_MIN:-0.3}
export PAUSE_MAX=${PAUSE_MAX:-0.7}

mkdir -p data logs

# ==== venv & deps ====
if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# ==== pipeline ====
echo "==> ANALYZE -> $OUT"
python -m src.main analyze --input "$INPUT" --output "$OUT"

echo "==> SCAN (write template) -> $CACHE"
python -m src.main scan --input "$OUT" --cache "$CACHE" --scope domain --write-template --save-every 20

echo "==> POST (workers=$WORKERS)"
python -m src.main post \
  --input "$OUT" \
  --cache "$CACHE" \
  --prefer-template \
  --workers "$WORKERS" \
  --chunk "$CHUNK" \
  --save-every "$SAVE_EVERY"

echo "✅ Done. Output: $OUT"
