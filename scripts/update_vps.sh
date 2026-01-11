#!/bin/bash
set -e

echo "=============================================="
echo "Cap nhat Blog Comment Tool tren VPS"
echo "=============================================="

cd ~/blogcomment

echo "Dang fetch code moi..."
git fetch origin

echo "Dang reset hard..."
git reset --hard origin/main

echo "Dang install dependencies..."
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Dang restart service..."
systemctl restart blog-comment-worker

echo ""
echo "Kiem tra trang thai..."
systemctl status blog-comment-worker --no-pager --brief || true

echo ""
echo "Xem logs gan day..."
journalctl -u blog-comment-worker -n 20 --no-pager

echo ""
echo "=============================================="
echo "✅ Cap nhat hoan thanh!"
echo "=============================================="
