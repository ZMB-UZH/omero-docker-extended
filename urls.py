from django.urls import path

from .views.index_view import index
from .views.job_view import start_job, job_progress, start_acq_job
from .views.delete_all_view import delete_all_metadata

urlpatterns = [
    path("", index, name="omeroweb_filenamemetadata_index"),
    path("start_job/", start_job, name="omeroweb_filenamemetadata_start_job"),
    path("progress/<str:job_id>/", job_progress, name="omeroweb_filenamemetadata_job_progress"),
    path("start_acq_job/", start_acq_job, name="omeroweb_filenamemetadata_start_acq_job"),
    path("delete_all/", delete_all_metadata, name="omeroweb_filenamemetadata_delete_all"),
]

