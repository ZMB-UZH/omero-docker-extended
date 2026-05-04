from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class AdminToolsPluginConfig(AppConfig):
    """Django application configuration for admin tools plugin config."""

    name = "omeroweb_admin_tools"
    label = "omeroweb_admin_tools"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: Django calls it after app loading. Output: registers startup hooks.
        """
        configure_omero_gateway_logging()
