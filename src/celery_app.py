# src/celery_app.py
import os
from celery import Celery

# Broker/Backend (đổi qua env trên VPS nếu cần)
BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_URL = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# Xuất biến 'celery' để dùng: celery -A src.celery_app.celery worker ...
celery = Celery(
    "blog_comment_tool",
    broker=BROKER_URL,
    backend=RESULT_URL,
    include=("src.tasks",),
)

celery.conf.update(
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=False,

    # Queue mặc định (có thể override theo campaign bằng apply_async(queue=...))
    task_default_queue="camp_test",

    # Serializer: dùng JSON để an toàn hơn (tránh pickle) và cho phép chạy worker không cần C_FORCE_ROOT.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Ổn định worker
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_retry_on_startup=True,
)

# Đảm bảo tự động nạp module task khi worker khởi động
celery.autodiscover_tasks(["src"])
