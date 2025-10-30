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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew services start redis  # hoặc tự khởi chạy redis-server
celery -A src.tasks worker --loglevel=info
python push_jobs_from_excel.py --input data/comments.xlsx --output data/comments_out.xlsx
```

### Biến môi trường hữu ích

| ENV | Mặc định | Ghi chú |
| --- | --- | --- |
| `HEADLESS` | `true` | Tắt đi để debug bằng giao diện |
| `MAX_ATTEMPTS` | `2` | Số lần retry mỗi URL |
| `RETRY_DELAY_SEC` | `3.0` | Delay giữa các lần retry |
| `RETRY_DRIVER_VERSIONS` | `0,141,140` | Danh sách uc major version fallback |
| `REGISTRY_DB` | `data/registry.sqlite3` | Đường dẫn registry |

### Kiến trúc

1. `push_jobs_from_excel.py` đọc file Excel, chuẩn hóa header (kể cả alias/không dấu).
2. Mỗi job được đẩy sang task `run_comment` (Celery) hoặc chạy trực tiếp khi dùng `--sync-one`.
3. `worker_lib.run_one_link` kiểm tra registry, khởi tạo trình duyệt UC, gọi `commenter.process_job`, retry khi lỗi tạm thời, phát hiện ngôn ngữ và ghi kết quả + meta vào registry SQLite.
4. Kết quả được gom về Excel output và file log (`push_jobs.log`, `blog_comment_tool.log`, `commenter.log`).

Hệ thống được thiết kế module hóa để dễ dàng bổ sung proxy rotation, sinh nội dung AI hoặc nền tảng bình luận mới trong tương lai.
