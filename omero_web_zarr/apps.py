#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.apps import AppConfig


class OmeroWebZarrAppConfig(AppConfig):
    """Django application configuration for OMERO web Zarr app config."""

    name = "omero_web_zarr"
    label = "zarr"

    @staticmethod
    def ready():
        """Register application startup hooks.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        from .integration import install_webgateway_overrides

        install_webgateway_overrides()
