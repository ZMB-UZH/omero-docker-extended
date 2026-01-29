import os

from celery import Celery

BROKER_URL = os.environ.get("OMERO_IMS_CELERY_BROKER_URL", "redis://redis:6379/2")
BACKEND_URL = os.environ.get("OMERO_IMS_CELERY_BACKEND_URL", BROKER_URL)
RESULT_EXPIRES = int(os.environ.get("OMERO_IMS_CELERY_RESULT_EXPIRES", "7200"))
TASK_TIME_LIMIT = int(os.environ.get("OMERO_IMS_CELERY_TIME_LIMIT", "7200"))

app = Celery("omeroweb_imaris_connector", broker=BROKER_URL, backend=BACKEND_URL)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=RESULT_EXPIRES,
    task_time_limit=TASK_TIME_LIMIT,
    task_default_queue=os.environ.get("OMERO_IMS_CELERY_QUEUE", "imaris_export"),
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=int(os.environ.get("OMERO_IMS_CELERY_MAX_RETRIES", "20")),
    worker_prefetch_multiplier=int(os.environ.get("OMERO_IMS_CELERY_PREFETCH", "1")),
    task_acks_late=True,
)

app.autodiscover_tasks(["omeroweb_imaris_connector"])
