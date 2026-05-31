"""
Celery application instance.

Connects to Redis (broker + result backend) and registers the task module
``app.worker.tasks``. All tasks use JSON serialisation and operate in UTC.

Start a worker with:
    celery -A app.worker.celery_app worker --pool=solo --loglevel=info

On macOS set ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` before starting
to avoid fork-safety warnings from Apple's Objective-C runtime.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "rag_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
