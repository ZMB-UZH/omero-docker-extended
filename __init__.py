default_app_config = "omeroweb_zmb_plugin.apps.ZMBPluginConfig"

from .views.index_view import index
from .views.job_view import start_job, job_progress
from .save_keyvaluepairs_view import save_keyvaluepairs
