from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "onco_research",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.analysis"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
