from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ImarisConnectorConfig(AppConfig):
    name = "omeroweb_imaris_connector"
    label = "omeroweb_imaris_connector"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
