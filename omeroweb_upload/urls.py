from django.urls import path

from .views.index_view import index, import_step, job_status, start_upload, upload_files

urlpatterns = [
    path("", index, name="omeroweb_upload_index"),
    path("start/", start_upload, name="omeroweb_upload_start"),
    path("upload/<str:job_id>/", upload_files, name="omeroweb_upload_files"),
    path("import/<str:job_id>/", import_step, name="omeroweb_upload_import_step"),
    path("status/<str:job_id>/", job_status, name="omeroweb_upload_status"),
]
