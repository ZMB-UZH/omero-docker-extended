from django.urls import re_path

from . import views


urlpatterns = [
    re_path(r"^$", views.index, name="omero_web_zarr_index"),
    re_path(
        r"^v(?P<version>0\.[3-4]+)/image/(?P<iid>[0-9]+).zarr/.zattrs$",
        views.image_zattrs,
        name="zarr_image_zattrs",
    ),
    re_path(
        r"^v(?P<version>0\.[3-4]+)/image/(?P<iid>[0-9]+).zarr/.zgroup$",
        views.image_zgroup,
        name="zarr_image_zgroup",
    ),
    re_path(
        r"^v(?P<version>0\.[3-4]+)/image/(?P<iid>[0-9]+).zarr/(?P<level>[0-9]+)/.zarray$",
        views.image_zarray,
        name="zarr_image_zarray",
    ),
    re_path(
        r"^v(?P<version>0\.[3-4]+)/image/(?P<iid>[0-9]+).zarr/(?P<level>[0-9]+)/(?P<chunk>[0-9/]+)$",
        views.image_chunk,
        name="zarr_image_chunk",
    ),
    re_path(
        r"^(?P<app>vizarr|validator)/(?P<url>.*)$",
        views.apps,
        name="zarr_app",
    ),
]
