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

    # Queue mặc định
    task_default_queue="camp_test",
    task_routes={
        "run_comment": {"queue": "camp_test", "routing_key": "camp_test"},
    },

    # Serializer
    task_serializer="pickle",
    result_serializer="pickle",
    accept_content=["pickle", "json"],

    # Ổn định worker
    worker_cancel_long_running_tasks_on_connection_loss=True,
)

# Đảm bảo tự động nạp module task khi worker khởi động
celery.autodiscover_tasks(["src"])
