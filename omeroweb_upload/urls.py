from django.urls import path

from .views.index_view import index, import_step, job_status, list_projects, start_upload, upload_files
from .views.user_settings_view import save_settings

urlpatterns = [
    path("", index, name="omeroweb_upload_index"),
    path("start/", start_upload, name="omeroweb_upload_start"),
    path("upload/<str:job_id>/", upload_files, name="omeroweb_upload_files"),
    path("import/<str:job_id>/", import_step, name="omeroweb_upload_import_step"),
    path("status/<str:job_id>/", job_status, name="omeroweb_upload_status"),
    path("projects/", list_projects, name="omeroweb_upload_projects"),
    path("user-settings/save/", save_settings, name="omeroweb_upload_save_user_settings"),
]
