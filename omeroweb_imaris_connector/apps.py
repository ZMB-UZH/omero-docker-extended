from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ImarisConnectorConfig(AppConfig):
    """Represent imaris connector config."""

    name = "omeroweb_imaris_connector"
    label = "omeroweb_imaris_connector"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: none. Output: None.
        """
        configure_omero_gateway_logging()
