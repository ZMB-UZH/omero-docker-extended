from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ToolsPluginConfig(AppConfig):
    name = "omeroweb_tools"
    label = "omeroweb_tools"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
