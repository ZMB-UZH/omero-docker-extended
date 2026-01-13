from django.urls import path

from .views.index_view import index

urlpatterns = [
    path("", index, name="omeroweb_admin_tools_index"),
]
