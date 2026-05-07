from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ImarisConnectorConfig(AppConfig):
    """Django application configuration for imaris connector config."""

    name = "omero_imaris_connector"
    label = "omero_imaris_connector"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        configure_omero_gateway_logging()
