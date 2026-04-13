from celery import Celery

from .config import build_enhanced_search_celery_config


_config = build_enhanced_search_celery_config()

app = Celery(
    "omeroweb_tools",
    broker=_config.broker_url,
    backend=_config.backend_url,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=_config.result_expires,
    task_time_limit=_config.time_limit,
    task_default_queue=_config.queue,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=_config.max_retries,
    worker_prefetch_multiplier=_config.prefetch_multiplier,
    task_acks_late=True,
)

app.autodiscover_tasks(["omeroweb_tools"], force=True)
