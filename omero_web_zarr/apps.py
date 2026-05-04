#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.apps import AppConfig


class OmeroWebZarrAppConfig(AppConfig):
    """Represent OMERO web Zarr app config."""

    name = "omero_web_zarr"
    label = "zarr"

    @staticmethod
    def ready():
        """Register application startup hooks.

        Inputs: none. Output: None.
        """
        from .integration import install_webgateway_overrides

        install_webgateway_overrides()
