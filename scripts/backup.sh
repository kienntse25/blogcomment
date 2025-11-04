#!/usr/bin/env bash
set -euo pipefail

TS="$(date +%Y%m%d-%H%M%S)"
DEST="${BLOG_COMMENT_BACKUP_DIR:-$HOME/backups/blog-comment-tool}"

mkdir -p "${DEST}"
tar czf "${DEST}/backup-${TS}.tar.gz" data/registry.sqlite3 logs

# Keep last 7 days of backups.
find "${DEST}" -maxdepth 1 -name 'backup-*.tar.gz' -mtime +7 -delete
