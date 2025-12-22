from django.urls import path
from .views.index_view import index
from .views.job_view import start_job, job_progress, start_acq_job, start_delete_all_job, start_delete_plugin_job
from .views.delete_all_view import delete_all_keyvaluepairs
from .views.delete_plugin_view import delete_plugin_keyvaluepairs
from .views.variable_set_view import list_sets, save_set, load_set, delete_set
from .views.help_view import help_page

urlpatterns = [
    path("", index, name="omeroweb_zmb_plugin_index"),
    path("start_job/", start_job, name="omeroweb_zmb_plugin_start_job"),
    path("progress/<str:job_id>/", job_progress, name="omeroweb_zmb_plugin_job_progress"),
    path("start_acq_job/", start_acq_job, name="omeroweb_zmb_plugin_start_acq_job"),
    path("start_delete_all_job/", start_delete_all_job, name="omeroweb_zmb_plugin_start_delete_all_job"),
    path("start_delete_plugin_job/", start_delete_plugin_job, name="omeroweb_zmb_plugin_start_delete_plugin_job"),
    path("delete_all/", delete_all_keyvaluepairs, name="omeroweb_zmb_plugin_delete_all"),
    path("delete_plugin/", delete_plugin_keyvaluepairs, name="omeroweb_zmb_plugin_delete_plugin"),
    path("varsets/", list_sets, name="omeroweb_zmb_plugin_list_sets"),
    path("varsets/save/", save_set, name="omeroweb_zmb_plugin_save_set"),
    path("varsets/load/", load_set, name="omeroweb_zmb_plugin_load_set"),
    path("varsets/delete/", delete_set, name="omeroweb_zmb_plugin_delete_set"),
    path("help/", help_page, name="omeroweb_zmb_plugin_help"),
]
