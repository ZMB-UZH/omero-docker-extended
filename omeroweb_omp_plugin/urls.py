from django.urls import path
from .views.index_view import index, list_projects, root_status
from .views.job_view import start_job, job_progress, start_acq_job, start_delete_all_job, start_delete_plugin_job
from .views.delete_all_view import delete_all_keyvaluepairs
from .views.delete_plugin_view import delete_plugin_keyvaluepairs
from .views.variable_set_view import list_sets, save_set, load_set, delete_set
from .views.help_view import help_page
from .views.ai_credentials_view import (
    list_credentials,
    save_credentials,
    test_credentials,
    list_models,
)
from .views.user_data_view import delete_api_keys, delete_variable_sets, delete_all_data
from .views.user_settings_view import save_settings

urlpatterns = [
    path("", index, name="omeroweb_omp_plugin_index"),
    path("projects/", list_projects, name="omeroweb_omp_plugin_projects"),
    path("root-status/", root_status, name="omeroweb_omp_plugin_root_status"),
    path("start_job/", start_job, name="omeroweb_omp_plugin_start_job"),
    path("progress/<str:job_id>/", job_progress, name="omeroweb_omp_plugin_job_progress"),
    path("start_acq_job/", start_acq_job, name="omeroweb_omp_plugin_start_acq_job"),
    path("start_delete_all_job/", start_delete_all_job, name="omeroweb_omp_plugin_start_delete_all_job"),
    path("start_delete_plugin_job/", start_delete_plugin_job, name="omeroweb_omp_plugin_start_delete_plugin_job"),
    path("delete_all/", delete_all_keyvaluepairs, name="omeroweb_omp_plugin_delete_all"),
    path("delete_plugin/", delete_plugin_keyvaluepairs, name="omeroweb_omp_plugin_delete_plugin"),
    path("varsets/", list_sets, name="omeroweb_omp_plugin_list_sets"),
    path("varsets/save/", save_set, name="omeroweb_omp_plugin_save_set"),
    path("varsets/load/", load_set, name="omeroweb_omp_plugin_load_set"),
    path("varsets/delete/", delete_set, name="omeroweb_omp_plugin_delete_set"),
    path("ai-credentials/", list_credentials, name="omeroweb_omp_plugin_list_ai_credentials"),
    path("ai-credentials/test/", test_credentials, name="omeroweb_omp_plugin_test_ai_credentials"),
    path("ai-credentials/save/", save_credentials, name="omeroweb_omp_plugin_save_ai_credentials"),
    path("ai-credentials/models/", list_models, name="omeroweb_omp_plugin_list_models"),
    path("user-settings/save/", save_settings, name="omeroweb_omp_plugin_save_user_settings"),
    path("user-data/delete-api-keys/", delete_api_keys, name="omeroweb_omp_plugin_delete_api_keys"),
    path("user-data/delete-variable-sets/", delete_variable_sets, name="omeroweb_omp_plugin_delete_variable_sets"),
    path("user-data/delete-all/", delete_all_data, name="omeroweb_omp_plugin_delete_user_data"),
    path("help/", help_page, name="omeroweb_omp_plugin_help"),
]
