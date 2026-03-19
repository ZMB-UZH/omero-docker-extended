from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ImportPluginConfig(AppConfig):
    name = "omeroweb_import"
    label = "omeroweb_import"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
