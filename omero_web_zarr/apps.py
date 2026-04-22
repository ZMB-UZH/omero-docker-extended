#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.apps import AppConfig


class OmeroWebZarrAppConfig(AppConfig):
    name = "omero_web_zarr"
    label = "zarr"

    @staticmethod
    def ready():
        from .integration import install_webgateway_overrides

        install_webgateway_overrides()
