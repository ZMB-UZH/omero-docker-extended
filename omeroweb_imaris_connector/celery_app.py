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

# autodiscover_tasks handles the import properly without circular dependency
app.autodiscover_tasks(["omeroweb_imaris_connector"], force=True)

# REMOVED: The explicit import that caused the circular dependency
# The autodiscover_tasks call above is sufficient to register the task
