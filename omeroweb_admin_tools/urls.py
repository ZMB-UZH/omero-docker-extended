from django.urls import path

from .views.index_view import (
    index,
    internal_log_labels,
    logs_data,
    logs_view,
    grafana_proxy,
    prometheus_proxy,
    resource_monitoring_data,
    resource_monitoring_view,
    root_status,
    storage_data,
    storage_view,
    server_database_testing_view,
    server_database_testing_run,
)

urlpatterns = [
    path("", index, name="omeroweb_admin_tools_index"),
    path("root-status/", root_status, name="omeroweb_admin_tools_root_status"),
    path("logs/", logs_view, name="omeroweb_admin_tools_logs"),
    path("logs/data/", logs_data, name="omeroweb_admin_tools_logs_data"),
    path("logs/internal-labels/", internal_log_labels, name="omeroweb_admin_tools_internal_labels"),
    path("resource-monitoring/", resource_monitoring_view, name="omeroweb_admin_tools_resource_monitoring"),
    path("resource-monitoring/data/", resource_monitoring_data, name="omeroweb_admin_tools_resource_monitoring_data"),
    path("resource-monitoring/grafana-proxy/<path:subpath>", grafana_proxy, name="omeroweb_admin_tools_grafana_proxy"),
    path("resource-monitoring/prometheus-proxy/<path:subpath>", prometheus_proxy, name="omeroweb_admin_tools_prometheus_proxy"),
    path("storage/", storage_view, name="omeroweb_admin_tools_storage"),
    path("storage/data/", storage_data, name="omeroweb_admin_tools_storage_data"),
    path("server-database-testing/", server_database_testing_view, name="omeroweb_admin_tools_server_database_testing"),
    path("server-database-testing/run/", server_database_testing_run, name="omeroweb_admin_tools_server_database_testing_run"),
]
