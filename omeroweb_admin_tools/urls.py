from django.urls import path

from .views.index_view import index, root_status

urlpatterns = [
    path("", index, name="omeroweb_admin_tools_index"),
    path("root-status/", root_status, name="omeroweb_admin_tools_root_status"),
]
