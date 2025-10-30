import sys
import os
sys.path.insert(0, os.path.abspath("src"))

from celery_app import app

job = {
    "url": "https://example.com",
    "anchor": "Example Anchor",
    "content": "Cảm ơn bài viết rất hữu ích!"
}

result = app.send_task("run_comment", args=[job], queue="camp_test")
print("✅ Job sent!", result)
