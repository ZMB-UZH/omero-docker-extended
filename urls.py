from django.urls import path
from .views.index_view import index
from .views.job_view import start_job, job_progress, start_acq_job
from .views.delete_all_view import delete_all_metadata
from .views.delete_plugin_view import delete_plugin_metadata
from .views.variable_set_view import list_sets, save_set, load_set, delete_set

urlpatterns = [
    path("", index, name="omeroweb_filenamemetadata_index"),
    path("start_job/", start_job, name="omeroweb_filenamemetadata_start_job"),
    path("progress/<str:job_id>/", job_progress, name="omeroweb_filenamemetadata_job_progress"),
    path("start_acq_job/", start_acq_job, name="omeroweb_filenamemetadata_start_acq_job"),
    path("delete_all/", delete_all_metadata, name="omeroweb_filenamemetadata_delete_all"),
    path("delete_plugin/", delete_plugin_metadata, name="omeroweb_filenamemetadata_delete_plugin"),
    path("varsets/", list_sets, name="omeroweb_filenamemetadata_list_sets"),
    path("varsets/save/", save_set, name="omeroweb_filenamemetadata_save_set"),
    path("varsets/load/", load_set, name="omeroweb_filenamemetadata_load_set"),
    path("varsets/delete/", delete_set, name="omeroweb_filenamemetadata_delete_set"),
]
