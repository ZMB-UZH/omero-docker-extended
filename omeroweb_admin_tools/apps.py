from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class AdminToolsPluginConfig(AppConfig):
    """Represent admin tools plugin config."""

    name = "omeroweb_admin_tools"
    label = "omeroweb_admin_tools"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
