# VPS Commands (chuẩn hoá)

Tài liệu này dành cho user chạy trên VPS (Ubuntu) bằng 2–3 terminal hoặc `tmux`.

## 0) Vào thư mục dự án

```bash
cd /root/blogcomment
```

## Gợi ý: dùng tmux để không bị ngắt SSH

```bash
sudo apt-get update && sudo apt-get install -y tmux
tmux new -s blogcomment
```

Trong `tmux`: chạy worker/pipeline như các bước bên dưới. Thoát `tmux` mà không tắt job: bấm `Ctrl+b` rồi `d`.

## 1) Làm sạch trước khi chạy (khuyến nghị)

Xoá output cũ + log pipeline của từng campaign (không xoá file input):

```bash
bash scripts/vps.sh clean --output data/out_camp_a.xlsx
bash scripts/vps.sh clean --output data/out_camp_b.xlsx
bash scripts/vps.sh clean --output data/out_camp_c.xlsx
```

Xoá task tồn trong Redis queue (để tránh “chạy nhầm data cũ”):

```bash
bash scripts/vps.sh purge --queues camp_a,camp_b,camp_c
```

## 2) Terminal 1: bật worker (xem status trực tiếp)

```bash
export C_FORCE_ROOT=1
# Nếu muốn bật UC (không khuyến nghị khi VPS hay crash): export USE_UC=true

bash scripts/vps.sh worker --concurrency 3 --queues camp_a,camp_b,camp_c --pageload 60 --comment-wait 25
```

Bạn sẽ thấy log kiểu:
`Task run_comment[...] succeeded ... {status: OK/FAILED, reason: ...}`

## 3) Terminal 2: chạy campaign A (đẩy job + ghi out dần)

```bash
bash scripts/vps.sh run \
  --queue camp_a \
  --input data/comments_a.xlsx \
  --output data/out_camp_a.xlsx \
  --timeout 60 \
  --flush-every 50 \
  --resume-ok
```

## 4) Terminal 3: chạy campaign B/C (tuỳ chọn)

```bash
bash scripts/vps.sh run --queue camp_b --input data/comments_b.xlsx --output data/out_camp_b.xlsx --timeout 60 --flush-every 50 --resume-ok
bash scripts/vps.sh run --queue camp_c --input data/comments_c.xlsx --output data/out_camp_c.xlsx --timeout 60 --flush-every 50 --resume-ok
```

## Xem log / debug nhanh

- Log pipeline (đẩy job + ghi file out): `tail -f logs/push_jobs_camp_a.log`
- File out ghi theo tiến độ (mỗi `--flush-every`): `ls -lh data/out_camp_a.xlsx`
- Nếu thấy “dừng ở N dòng”: thường là pipeline đang **chờ task** hoặc worker bị dừng. Kiểm tra:
  - `tail -n 50 logs/push_jobs_camp_a.log`
  - Nhìn Terminal worker còn chạy không
  - `redis-cli llen camp_a` (xem còn bao nhiêu task đang chờ)
