from django.urls import path

from .views.index_view import (
    confirm_import,
    import_step,
    index,
    job_status,
    list_projects,
    prune_upload,
    root_status,
    start_upload,
    upload_files,
)
from .views.special_method_settings_view import (
    load_settings as load_special_method_settings,
)
from .views.special_method_settings_view import (
    save_settings as save_special_method_settings,
)
from .views.user_settings_view import save_settings
from .views.help_view import help_page

urlpatterns = [
    path("", index, name="omeroweb_import_index"),
    path("start/", start_upload, name="omeroweb_import_start"),
    path("upload/<str:job_id>/", upload_files, name="omeroweb_import_files"),
    path("import/<str:job_id>/", import_step, name="omeroweb_import_import_step"),
    path("confirm/<str:job_id>/", confirm_import, name="omeroweb_import_confirm"),
    path("prune/<str:job_id>/", prune_upload, name="omeroweb_import_prune"),
    path("status/<str:job_id>/", job_status, name="omeroweb_import_status"),
    path("projects/", list_projects, name="omeroweb_import_projects"),
    path("root-status/", root_status, name="omeroweb_import_root_status"),
    path(
        "user-settings/save/", save_settings, name="omeroweb_import_save_user_settings"
    ),
    path(
        "special-method-settings/save/",
        save_special_method_settings,
        name="omeroweb_import_save_special_method_settings",
    ),
    path(
        "special-method-settings/load/",
        load_special_method_settings,
        name="omeroweb_import_load_special_method_settings",
    ),
    path("help/", help_page, name="omeroweb_import_help"),
]
