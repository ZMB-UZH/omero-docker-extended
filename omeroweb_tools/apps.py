from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class ToolsPluginConfig(AppConfig):
    """Represent tools plugin config."""

    name = "omeroweb_tools"
    label = "omeroweb_tools"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: none. Output: None.
        """
        configure_omero_gateway_logging()
