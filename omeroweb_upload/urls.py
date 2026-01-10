from django.urls import path

from .views.index_view import index, upload_files

urlpatterns = [
    path("", index, name="omeroweb_upload_index"),
    path("upload/", upload_files, name="omeroweb_upload_files"),
]
