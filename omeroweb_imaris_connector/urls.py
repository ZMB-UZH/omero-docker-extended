from django.urls import path

from . import views

urlpatterns = [
    path("imaris-export/", views.imaris_export, name="imaris_export"),
]
