"""
Job cleanup for RAM-based job storage (redis).
This module handles automatic cleanup of old job files to prevent RAM accumulation in the tmpfs-mounted job directory.
"""

import os
import time
import logging
from ..constants import JOBS_DIR, JOB_MAX_AGE_SECONDS, JOB_CLEANUP_INTERVAL

logger = logging.getLogger(__name__)

# Global state for cleanup tracking
_last_cleanup_time = 0


def cleanup_old_jobs():
    """
    Automatically delete old job files to prevent RAM accumulation.
    
    This is called from the job views to ensure old jobs
    don't accumulate in memory. Since jobs are stored in tmpfs (RAM),
    this prevents memory leaks.
    
    Multiple simultaneous calls are safe (worst case: redundant cleanup requests)
    """
    global _last_cleanup_time
    now = time.time()
    
    # Throttle cleanup to avoid excessive file system operations
    if now - _last_cleanup_time < JOB_CLEANUP_INTERVAL:
        return
    _last_cleanup_time = now
    try:
        if not os.path.exists(JOBS_DIR):
            return
        deleted_count = 0
        error_count = 0
        for filename in os.listdir(JOBS_DIR):
            # Skip lock files
            if filename.endswith('.lock'):
                continue
            # Only process JSON job files
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(JOBS_DIR, filename)
            try:
                # Check file age
                mtime = os.path.getmtime(filepath)
                age = now - mtime
                if age > JOB_MAX_AGE_SECONDS:
                    # Also delete associated lock file if it exists
                    lock_file = filepath.replace('.json', '.lock')
                    os.remove(filepath)
                    deleted_count += 1
                    if os.path.exists(lock_file):
                        try:
                            os.remove(lock_file)
                        except OSError:
                            pass  # Lock file might be in use, ignore
            except OSError as e:
                error_count += 1
                logger.warning(f"Failed to cleanup job file {filename}: {e}")
                continue

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old job file(s) from RAM")

        if error_count > 0:
            logger.warning(f"Encountered {error_count} error(s) during job cleanup")
            
    except Exception as e:
        logger.exception(f"Job cleanup failed: {e}")
