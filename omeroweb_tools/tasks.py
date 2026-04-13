from __future__ import annotations

from .celery_app import app
from .services.enhanced_search_service import run_scope_sync_task
from .task_names import ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME


@app.task(bind=True, name=ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME)
def run_enhanced_search_scope_sync(self, scope_key: str, run_token: str):
    return run_scope_sync_task(scope_key, run_token)
