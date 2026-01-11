#!/bin/bash
set -e

echo "=============================================="
echo "Xoa thong tin ca nhan khoi git history"
echo "=============================================="

if ! command -v git-filter-repo &> /dev/null; then
    echo "Chua cai dat git-filter-repo: pip install git-filter-repo"
    exit 1
fi

BACKUP_DIR="../blogcomment-backup-$(date +%Y%m%d-%H%M%S).git"
cp -r .git "$BACKUP_DIR"
echo "Backup saved to: $BACKUP_DIR"

read -p "Ten moi (Enter de xoa): " NEW_NAME
read -p "Email moi (Enter de xoa): " NEW_EMAIL
read -p "Repo URL moi: " NEW_REPO_URL

if [ -z "$NEW_NAME" ] && [ -z "$NEW_EMAIL" ]; then
    git filter-repo --name-callback 'return None' --email-callback 'return None' --force
else
    git filter-repo --name-callback "return '$NEW_NAME'" --email-callback "return '$NEW_EMAIL'" --force
fi

if [ -n "$NEW_REPO_URL" ]; then
    git remote set-url origin "$NEW_REPO_URL"
    if [ -f "scripts/deploy_vps.sh" ]; then
        sed -i "s|https://github.com/kienntse25/blogcomment.git|$NEW_REPO_URL|g" scripts/deploy_vps.sh
    fi
fi

echo ""
echo "5 commits gan nhat:"
git log --oneline -5
echo ""
echo "Remote URL:"
git remote get-url origin
echo ""
echo "Done! Force push: git push origin main --force"
