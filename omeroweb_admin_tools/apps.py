from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class AdminToolsPluginConfig(AppConfig):
    name = "omeroweb_admin_tools"
    label = "omeroweb_admin_tools"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
