"""OMERO.web OMP plugin."""

from .views.index_view import index as index
from .views.job_view import job_progress as job_progress
from .views.job_view import start_job as start_job
from .views.save_keyvaluepairs_view import save_keyvaluepairs as save_keyvaluepairs

__all__ = ["index", "job_progress", "save_keyvaluepairs", "start_job"]
