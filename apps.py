from django.apps import AppConfig

from .constants import PLUGIN_DISPLAY_NAME


class OMPPluginConfig(AppConfig):
    name = "omeroweb_omp_plugin"
    label = "omeroweb_omp_plugin"
    verbose_name = PLUGIN_DISPLAY_NAME
