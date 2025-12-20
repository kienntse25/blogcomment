## Blog Comment Tool

Tool tự động gửi bình luận hàng loạt cho mục đích SEO an toàn. Hệ thống gồm các thành phần chính:

- **Celery + Redis** làm hàng đợi phân tán để mở rộng tới hàng nghìn URL (8.000+) song song.
- **Selenium (undetected-chromedriver)** để điều khiển trình duyệt headless trên VPS, tự nhận diện nền tảng bình luận (WordPress, Blogger, Disqus, Hyvor, Commento…).
- **Registry SQLite** (`data/registry.sqlite3`) đảm bảo mỗi URL + nội dung + người gửi chỉ được xử lý một lần.
- **Ngôn ngữ**: tự phát hiện ngôn ngữ trang bằng `langdetect`, ghi lại cùng kết quả để thống kê.
- **Retry & Logging**: ghi log chi tiết, tự retry những lỗi tạm thời và lưu toàn bộ meta (status, lý do, link comment, số lần thử, language).
- **Excel Pipeline**: đọc `data/comments.xlsx` (cột: `URL | Anchor | Website | Nội Dung | Name | Email`), xử lý jobs qua Celery hoặc chế độ test một dòng (`--sync-one`), rồi xuất `data/comments_out.xlsx` với trạng thái, lý do lỗi, link comment, thời gian, ngôn ngữ và số lần thử.

### Cài đặt nhanh

```bash
make venv                      # tạo và cài đặt virtualenv
cp .env.example .env           # (tuỳ chọn) tạo file env local
source scripts/setup_env.sh    # nạp biến môi trường mặc định
make worker                    # chạy Celery worker (giữ tab này)
make pipeline                  # tab khác: chạy pipeline từ Excel
```

### Chạy nhanh trên VPS (dễ thao tác)

Mở 2 terminal:

- Terminal 1 (worker):

```bash
bash scripts/vps.sh worker --concurrency 3 --queues camp_test
```

- Terminal 2 (run 1 file):

```bash
bash scripts/vps.sh run --input data/comments_thoitiet.xlsx --output data/comments_out.xlsx --timeout 60 --flush-every 50 --resume-ok
```

Không gắn anchor (chỉ dùng nội dung trong cột `Nội Dung`):

```bash
bash scripts/vps.sh run --no-anchor --input data/comments_thoitiet.xlsx --output data/comments_out.xlsx --timeout 60 --flush-every 50 --resume-ok
```

Tuỳ chọn dọn output trước khi chạy:

```bash
bash scripts/vps.sh clean --output data/comments_out.xlsx
```

Các script tiện ích:

- `scripts/run.sh`: kích hoạt venv và chạy worker (tương đương `make worker`).
- `scripts/run_worker.sh`: chạy worker với cấu hình qua ENV (queue/concurrency), dùng cho systemd.
- `scripts/run_pipeline.sh`: chạy pipeline, nhận thêm tham số CLI nếu cần (vd. `--sync-one`).
- `scripts/health_check.py`: kiểm tra trạng thái `redis-server` và `celery` (dùng cho cron/timer).
- `scripts/backup.sh`: nén `data/registry.sqlite3` + `logs/` vào thư mục backup (`$BLOG_COMMENT_BACKUP_DIR` hoặc `~/backups/blog-comment-tool`).

Triển khai service nền: mẫu systemd nằm tại `deploy/celery.service`. Sao chép file này lên VPS, chỉnh đường dẫn cho phù hợp rồi kích hoạt bằng:

```bash
sudo cp deploy/celery.service /etc/systemd/system/celery.service
sudo systemctl daemon-reload
sudo systemctl enable --now celery
```

Chạy campaign bằng systemd (oneshot, có thể chạy nhiều campaign theo queue riêng): mẫu nằm tại `deploy/campaign@.service`.

```bash
sudo cp deploy/campaign@.service /etc/systemd/system/blogcomment-campaign@.service
sudo systemctl daemon-reload
# ví dụ chạy campaign tên "a" (đọc env từ deploy/campaigns/a.env nếu có)
sudo systemctl start blogcomment-campaign@a
```

Chạy với file Excel mới trên VPS:

- Dùng tham số: `python push_jobs_from_excel.py --input data/your_file.xlsx --output data/comments_out.xlsx --limit 0`
- Hoặc dùng Makefile: `make pipeline INPUT=data/your_file.xlsx OUTPUT=data/comments_out.xlsx`

Mẫu input nằm ở `data/comments.template.xlsx`. Upload file của bạn vào `data/` rồi chạy với `--input` (khuyến nghị, để tránh xung đột khi `git pull`).

Tách riêng các URL bị `Page load timeout` để chạy lại:

- Khi chạy pipeline, tool sẽ tạo thêm file `*_timeouts.xlsx` bên cạnh output (VD: `data/comments_out_timeouts.xlsx`).
- Chạy lại batch timeout với timeout lớn hơn, concurrency thấp hơn:

```bash
export PAGELOAD_TIMEOUT=60
export FIND_TIMEOUT=12
python push_jobs_from_excel.py --input data/comments_out_timeouts.xlsx --output data/comments_out_retry.xlsx --limit 0
```

Resume khi crash/restart (bỏ qua URL đã OK trong output):

```bash
python push_jobs_from_excel.py --resume-ok --input data/comments_thoitiet.xlsx --output data/comments_out.xlsx --limit 0
```

Format file output:

- Giữ nguyên các cột input (vd `URL | Anchor | Website | Nội Dung | Name | Email`)
- Thêm các cột để lọc nhanh:
  - `Status` (`OK`/`FAILED`)
  - `Reason`
  - `Comment Link`
  - `Duration (sec)`
  - `Language`
  - `Attempts`
  - `Updated At`

Tạo nội dung tự động bằng Gemini (theo cột `Anchor`):

```bash
export GEMINI_API_KEY=...   # hoặc đặt trong .env
python -m src.generative_ai --input data/comments_thoitiet.xlsx
```

Lệnh trên sẽ điền vào cột `Nội Dung` / `Nội dung` cho các dòng đang trống (có thể dùng `--overwrite` nếu muốn ghi đè).

Gợi ý cấu hình ổn định trên VPS (tùy chọn):

- Tăng retry cho lỗi driver (mặc định thêm 1 lần): `EXTRA_ATTEMPTS_ON_DRIVER_FAIL=1`
- Nếu UC hay crash: thử `UC_USE_SUBPROCESS=false`

Chạy "một lệnh" (Gemini → Worker → Pipeline):

```bash
./scripts/run_campaign.sh --input data/comments_thoitiet.xlsx --output data/comments_out.xlsx --flush-redis --clean-output
```

Tuỳ chọn bật UC khi cần:

```bash
./scripts/run_campaign.sh --use-uc --input data/comments_thoitiet.xlsx --output data/comments_out.xlsx
```

### Chạy nhiều campaign cùng lúc

Mỗi campaign nên dùng **queue riêng** để không trộn task.

Ví dụ chạy 2 campaign song song (mở 3 terminal):

- Terminal 1: start 1 worker nghe nhiều queue:

```bash
celery -A src.tasks worker --loglevel=info --concurrency=6 -Q camp_a,camp_b
```

- Terminal 2:

```bash
python push_jobs_from_excel.py --queue camp_a --input data/comments_a.xlsx --output data/out_a.xlsx --limit 0
```

- Terminal 3:

```bash
python push_jobs_from_excel.py --queue camp_b --input data/comments_b.xlsx --output data/out_b.xlsx --limit 0
```

Hoặc dùng script (mỗi campaign tự start worker riêng nếu không dùng `--no-worker`):

```bash
./scripts/run_campaign.sh --queue camp_a --input data/comments_a.xlsx --output data/out_a.xlsx
./scripts/run_campaign.sh --queue camp_b --input data/comments_b.xlsx --output data/out_b.xlsx
```

### Allowlist domain (khuyến nghị cho môi trường được phép)

Nếu bạn muốn tool chỉ chạy trên các domain được phép, tạo file `data/allowed_domains.txt` (xem mẫu `data/allowed_domains.example.txt`).
Khi file này tồn tại, URL ngoài allowlist sẽ trả về `FAILED` với lý do `Not allowed by allowlist ...` để bạn có report rõ ràng.

Tuỳ chọn tôn trọng robots.txt (mặc định tắt):

```bash
export RESPECT_ROBOTS=true
```

### Debug khi fail (screenshot + HTML)

Để debug các lỗi như `Comment box not found`, bật lưu screenshot + HTML:

```bash
export SCREENSHOT_ON_FAIL=true
export FAILSHOT_DIR=logs/failshots
```

Khi một URL fail ở lần attempt cuối, tool sẽ lưu:
- `logs/failshots/<timestamp>_<host>.png`
- `logs/failshots/<timestamp>_<host>.html`
- `logs/failshots/<timestamp>_<host>.txt` (url + reason)

Gợi ý: một số theme WordPress lazy-load phần comment ở cuối trang, tool sẽ tự scroll tới `#respond/#commentform/#comments` và thử mở form theo các từ khóa (EN/ES/PT/RU).

### Biến môi trường hữu ích

| ENV | Mặc định | Ghi chú |
| --- | --- | --- |
| `HEADLESS` | `true` | Tắt đi để debug bằng giao diện |
| `MAX_ATTEMPTS` | `2` | Số lần retry mỗi URL |
| `RETRY_DELAY_SEC` | `3.0` | Delay giữa các lần retry |
| `RETRY_DRIVER_VERSIONS` | `0,141,140` | Danh sách uc major version fallback |
| `REGISTRY_DB` | `data/registry.sqlite3` | Đường dẫn registry |
| `PROXY_URL` | *(trống)* | Proxy cố định dạng `http://user:pass@host:port` |
| `PROXY_LIST` | *(trống)* | Danh sách proxy cách nhau dấu phẩy, worker chọn ngẫu nhiên |
| `PROXY_FILE` | `data/proxies.txt` nếu file tồn tại | Đường dẫn file chứa danh sách proxy (mỗi dòng một proxy, hỗ trợ `#` comment) |
| `PROXY_XLSX` | `data/proxies.xlsx` nếu file tồn tại | File Excel (cột `Proxy` hoặc cột đầu tiên) chứa danh sách proxy |
| `PROXY_HOST` | *(trống)* | Dùng khi file proxy chỉ chứa `PORT` (VD: `proxy.provider.com`) |
| `PROXY_SCHEME` | `http` | Scheme cho proxy khi ghép từ `PROXY_HOST` + `PORT` |
| `PROXY_USER` | *(trống)* | User cho proxy port-only (nếu cần) |
| `PROXY_PASS` | *(trống)* | Pass cho proxy port-only (nếu cần) |

### Kiến trúc

> Thứ tự ưu tiên proxy: `PROXY_LIST` → nội dung `PROXY_XLSX` → nội dung `PROXY_FILE` → `PROXY_URL`. Khi gặp lỗi kết nối, worker tự động thử lại lượt tiếp theo không proxy.

Tạo file `data/proxies.txt` *hoặc* `data/proxies.xlsx` (cột `Proxy`, hoặc chỉ cần một cột đầu tiên chứa proxy) để worker tự động xoay vòng mà không cần chỉnh biến môi trường. Các dòng trống hoặc bắt đầu bằng `#` sẽ bị bỏ qua.

Nếu nhà cung cấp là loại "PORT" (FPT/VNPT/Viettel…), bạn có thể để file proxy chỉ chứa số port (mỗi dòng một port). Khi đó cấu hình thêm `PROXY_HOST` (và nếu cần `PROXY_USER`/`PROXY_PASS`) để tool tự ghép thành `http://user:pass@PROXY_HOST:PORT`.

Nếu nhà cung cấp trả proxy dạng `IP:PORT:USER:PASS` (thường gặp ở một số API proxy), bạn có thể dán trực tiếp dòng đó vào `data/proxies.txt`/`data/proxies.xlsx`; tool sẽ tự chuyển thành dạng `http://USER:PASS@IP:PORT` (scheme lấy từ `PROXY_SCHEME`, mặc định `http`).

> Lưu ý: để ổn định khi chạy song song nhiều worker, mặc định tool ưu tiên Selenium. Chỉ bật UC khi cần bằng `USE_UC=true` và có thể set `UC_CLEAR_CACHE=true` nếu UC bị lỗi cache.


1. `push_jobs_from_excel.py` đọc file Excel, chuẩn hóa header (kể cả alias/không dấu).
2. Mỗi job được đẩy sang task `run_comment` (Celery) hoặc chạy trực tiếp khi dùng `--sync-one`.
3. `worker_lib.run_one_link` kiểm tra registry, khởi tạo trình duyệt UC, gọi `commenter.process_job`, retry khi lỗi tạm thời, phát hiện ngôn ngữ và ghi kết quả + meta vào registry SQLite.
4. Kết quả được gom về Excel output và file log (`push_jobs.log`, `blog_comment_tool.log`, `commenter.log`).

Hệ thống được thiết kế module hóa để dễ dàng bổ sung proxy rotation, sinh nội dung AI hoặc nền tảng bình luận mới trong tương lai.
