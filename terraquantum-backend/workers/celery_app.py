"""
Celery application — HITO 7 async workers.

Start workers:
    celery -A workers.celery_app worker --loglevel=info --concurrency=4

Monitor:
    celery -A workers.celery_app flower   # pip install flower

Requires a running Redis instance:
    docker run -d -p 6379:6379 redis:7-alpine
    # or: set CELERY_BROKER_URL / CELERY_RESULT_BACKEND env vars for a remote Redis.
"""
from celery import Celery

from core.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "terraquantum",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Track STARTED state so /api/async/tasks/{id} reports "running" immediately.
    task_track_started=True,
    # Ack AFTER task completes — re-enqueues on worker crash.
    task_acks_late=True,
    # One task per worker slot to avoid GIL contention during heavy numpy work.
    worker_prefetch_multiplier=1,
    # Results expire after 24 h (status polling window).
    result_expires=86400,
)
