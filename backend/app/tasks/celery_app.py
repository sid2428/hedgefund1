"""Celery application factory.

Tasks are sync functions; they wrap async DB / agent calls with `asyncio.run`.
We dedicate two queues:
  - `filings`  -> ingest tasks (EDGAR, raw text storage)
  - `theses`   -> agent pipeline tasks
"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery = Celery(
    "mosaic",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.ingest_tasks",
        "app.tasks.thesis_tasks",
    ],
)

celery.conf.update(
    task_routes={
        "app.tasks.ingest_tasks.*": {"queue": "filings"},
        "app.tasks.thesis_tasks.*": {"queue": "theses"},
    },
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
