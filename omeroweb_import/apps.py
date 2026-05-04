from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ImportPluginConfig(AppConfig):
    """Django application configuration for import plugin config."""

    name = "omeroweb_import"
    label = "omeroweb_import"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        configure_omero_gateway_logging()
