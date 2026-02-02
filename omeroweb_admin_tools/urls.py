from django.urls import path

from .views.index_view import index, logs_data, logs_view, root_status, internal_log_labels

urlpatterns = [
    path("", index, name="omeroweb_admin_tools_index"),
    path("root-status/", root_status, name="omeroweb_admin_tools_root_status"),
    path("logs/", logs_view, name="omeroweb_admin_tools_logs"),
    path("logs/data/", logs_data, name="omeroweb_admin_tools_logs_data"),
    path("logs/internal-labels/", internal_log_labels, name="omeroweb_admin_tools_internal_labels"),
]
