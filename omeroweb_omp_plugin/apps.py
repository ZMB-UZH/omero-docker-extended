from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class OMPPluginConfig(AppConfig):
    """Django application configuration for ompplugin config."""

    name = "omeroweb_omp_plugin"
    label = "omeroweb_omp_plugin"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        configure_omero_gateway_logging()
