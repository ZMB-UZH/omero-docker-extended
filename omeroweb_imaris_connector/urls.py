from django.urls import path

from . import views

app_name = 'omeroweb_imaris_connector'

urlpatterns = [
    path("imaris-export/", views.imaris_export, name="imaris_export"),
]
