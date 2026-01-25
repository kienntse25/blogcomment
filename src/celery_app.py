# src/celery_app.py
import os
from celery import Celery
from kombu import Exchange, Queue

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
    task_default_queue="camp_a",

    # Định nghĩa các queues cho 3 campaigns
    task_queues=(
        Queue("camp_a", Exchange("camp_a"), routing_key="camp_a"),
        Queue("camp_b", Exchange("camp_b"), routing_key="camp_b"),
        Queue("camp_c", Exchange("camp_c"), routing_key="camp_c"),
    ),

    # Serializer: dùng JSON để an toàn hơn
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Ổn định worker
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_retry_on_startup=True,
)

# Đảm bảo tự động nạp module task khi worker khởi động
celery.autodiscover_tasks(["src"])
