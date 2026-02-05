from celery import Celery

from .config import (
    get_celery_backend_url,
    get_celery_broker_url,
    get_celery_max_retries,
    get_celery_prefetch_multiplier,
    get_celery_queue,
    get_celery_result_expires,
    get_celery_time_limit,
)

BROKER_URL = get_celery_broker_url()
BACKEND_URL = get_celery_backend_url()
RESULT_EXPIRES = get_celery_result_expires()
TASK_TIME_LIMIT = get_celery_time_limit()

app = Celery("omeroweb_imaris_connector", broker=BROKER_URL, backend=BACKEND_URL)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=RESULT_EXPIRES,
    task_time_limit=TASK_TIME_LIMIT,
    task_default_queue=get_celery_queue(),
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=get_celery_max_retries(),
    worker_prefetch_multiplier=get_celery_prefetch_multiplier(),
    task_acks_late=True,
)

# Force=True ensures import errors are raised, not silently ignored
app.autodiscover_tasks(["omeroweb_imaris_connector"], force=True)

# Explicit import to ensure task is registered even if autodiscover fails
try:
    from .tasks import run_ims_export_task  # noqa: F401
except ImportError as e:
    import logging
    logging.getLogger(__name__).error("Failed to import tasks: %s", e)
    raise
