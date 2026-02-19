from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class OMPPluginConfig(AppConfig):
    name = "omeroweb_omp_plugin"
    label = "omeroweb_omp_plugin"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
