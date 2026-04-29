from __future__ import annotations

from django.http import HttpResponse
from django.urls import path


def _noop_view(_request, *args, **kwargs):
    """Handle noop view."""
    return HttpResponse("")


urlpatterns = [
    path(
        "grafana/<path:subpath>",
        _noop_view,
        name="omeroweb_admin_tools_grafana_proxy",
    ),
    path(
        "prometheus/<path:subpath>",
        _noop_view,
        name="omeroweb_admin_tools_prometheus_proxy",
    ),
]
