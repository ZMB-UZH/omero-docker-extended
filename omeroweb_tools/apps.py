from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ToolsPluginConfig(AppConfig):
    """Django application configuration for tools plugin config."""

    name = "omeroweb_tools"
    label = "omeroweb_tools"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        configure_omero_gateway_logging()
