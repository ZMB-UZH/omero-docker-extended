import os

from django.apps import AppConfig


class OMPPluginConfig(AppConfig):
    name = "omeroweb_omp_plugin"
    label = "omeroweb_omp_plugin"
    verbose_name = os.environ.get("OMP_PLUGIN_DISPLAY_NAME", "OMP plugin")
