import os

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env

BYTES_PER_GB = 1024 * 1024 * 1024
MAX_UPLOAD_BATCH_GB = 1024
MAX_UPLOAD_BATCH_BYTES = MAX_UPLOAD_BATCH_GB * BYTES_PER_GB

# OMERO.web virtualenv (used for CLI and other tooling).
# Override via environment when the venv name changes.
OMERO_WEB_ROOT = get_env("OMERO_WEB_ROOT", env_file=ENV_FILE_OMEROWEB)
OMERO_WEB_VENV = get_env("OMERO_WEB_VENV", env_file=ENV_FILE_OMEROWEB)
OMERO_CLI = os.path.join(OMERO_WEB_ROOT, OMERO_WEB_VENV, "bin", "omero")
