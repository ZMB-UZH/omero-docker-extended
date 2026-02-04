"""OMERO.web OMP plugin."""
default_app_config = "omeroweb_omp_plugin.apps.OMPPluginConfig"

from .views.index_view import index
from .views.job_view import start_job, job_progress
from .views.save_keyvaluepairs_view import save_keyvaluepairs
