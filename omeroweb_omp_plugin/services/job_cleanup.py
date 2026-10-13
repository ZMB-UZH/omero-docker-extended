"""Legacy filesystem job cleanup; not a Redis TTL or an automatically scheduled task."""

import logging
import os
import time
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..constants import JOBS_DIR, JOB_MAX_AGE_SECONDS, JOB_CLEANUP_INTERVAL

logger = logging.getLogger(__name__)

_cleanup_state = {"last_cleanup_time": 0.0}


def cleanup_old_jobs():
    """Automatically delete old job files to prevent RAM accumulation.

    Inputs: no caller arguments. Output: performs the documented action and returns None.

    Callers explicitly opt into age-based removal of legacy JSON job files.
    Current host-side temporary cleanup is configured separately by installation.

    Multiple simultaneous calls are safe (worst case: redundant cleanup requests)
    """
    now = time.time()

    # Throttle cleanup to avoid excessive file system operations
    if now - _cleanup_state["last_cleanup_time"] < JOB_CLEANUP_INTERVAL:
        return
    _cleanup_state["last_cleanup_time"] = now
    try:
        if not os.path.exists(JOBS_DIR):
            return
        deleted_count = 0
        error_count = 0
        for filename in os.listdir(JOBS_DIR):
            # Skip lock files
            if filename.endswith(".lock"):
                continue
            # Only process JSON job files
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(JOBS_DIR, filename)
            try:
                # Check file age
                mtime = os.path.getmtime(filepath)
                age = now - mtime
                if age > JOB_MAX_AGE_SECONDS:
                    # Also delete associated lock file if it exists
                    lock_file = os.path.splitext(filepath)[0] + ".lock"
                    os.remove(filepath)
                    deleted_count += 1
                    if os.path.exists(lock_file):
                        try:
                            os.remove(lock_file)
                        except OSError as exc:
                            logger.debug(
                                "Ignoring lock cleanup error for %s: %s",
                                sanitize_log_value(lock_file),
                                sanitize_log_value(exc),
                            )
            except OSError as e:
                error_count += 1
                logger.warning(
                    "Failed to cleanup job file %s: %s",
                    sanitize_log_value(filename),
                    sanitize_log_value(e),
                )
                continue

        if deleted_count > 0:
            logger.info("Cleaned up %s old job file(s) from RAM", deleted_count)

        if error_count > 0:
            logger.warning("Encountered %s error(s) during job cleanup", error_count)

    except Exception as e:
        logger.error(
            "Job cleanup failed: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
