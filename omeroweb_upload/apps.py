from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class UploadPluginConfig(AppConfig):
    name = "omeroweb_upload"
    label = "omeroweb_upload"

    def ready(self) -> None:
        """Apply plugin-wide runtime configuration."""
        configure_omero_gateway_logging()
