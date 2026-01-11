# Chuan bi thuong mai hoa Blog Comment Tool

## Cac buoc thuc hien

### 1. Xoa thong tin ca nhan

pip install git-filter-repo
bash clean_identity.sh

### 2. Force push
git push origin main --force

### 3. Update VPS
bash scripts/update_vps.sh

## Deployment moi
REPO_URL=git@github.com:company/repo.git bash scripts/deploy_vps.sh
