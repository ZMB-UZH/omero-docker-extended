import os

BYTES_PER_GB = 1024 * 1024 * 1024
MAX_UPLOAD_BATCH_GB = 1024
MAX_UPLOAD_BATCH_BYTES = MAX_UPLOAD_BATCH_GB * BYTES_PER_GB

# OMERO.web virtualenv (used for CLI and other tooling).
# Override via environment when the venv name changes.
#
# NOTE: These must remain OPTIONAL. Making them required causes the upload plugin
# to crash on import/page-load in environments that rely on defaults.
OMERO_WEB_ROOT = os.environ.get("OMERO_WEB_ROOT", "/opt/omero/web")
OMERO_WEB_VENV = os.environ.get("OMERO_WEB_VENV", "venv-3.12")

OMERO_CLI = os.path.join(OMERO_WEB_ROOT, OMERO_WEB_VENV, "bin", "omero")
