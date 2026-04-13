from django.urls import path

from .views.help_view import help_page
from .views.index_view import (
    apply_saved_query_view,
    delete_query_view,
    enhanced_search_view,
    index,
    root_status,
    save_query_view,
    start_scope_sync_view,
    sync_state_view,
)


urlpatterns = [
    path("", index, name="omeroweb_tools_index"),
    path("root-status/", root_status, name="omeroweb_tools_root_status"),
    path(
        "enhanced-search/",
        enhanced_search_view,
        name="omeroweb_tools_enhanced_search",
    ),
    path(
        "enhanced-search/sync/",
        start_scope_sync_view,
        name="omeroweb_tools_enhanced_search_sync",
    ),
    path(
        "enhanced-search/sync-state/",
        sync_state_view,
        name="omeroweb_tools_enhanced_search_sync_state",
    ),
    path(
        "enhanced-search/saved-queries/save/",
        save_query_view,
        name="omeroweb_tools_enhanced_search_save_query",
    ),
    path(
        "enhanced-search/saved-queries/delete/",
        delete_query_view,
        name="omeroweb_tools_enhanced_search_delete_query",
    ),
    path(
        "enhanced-search/saved-queries/<int:query_id>/",
        apply_saved_query_view,
        name="omeroweb_tools_enhanced_search_apply_query",
    ),
    path("help/", help_page, name="omeroweb_tools_help"),
]

