from __future__ import annotations

from .celery_app import app


@app.task(bind=True, name="omeroweb_tools.run_enhanced_search_scope_sync")
def run_enhanced_search_scope_sync(self, scope_key: str, run_token: str):
    from .services.enhanced_search_service import run_scope_sync_task

    return run_scope_sync_task(scope_key, run_token)
