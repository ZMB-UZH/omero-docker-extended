from django.apps import AppConfig

from omero_plugin_common.logging_utils import configure_omero_gateway_logging


class OMPPluginConfig(AppConfig):
    """Represent ompplugin config."""

    name = "omeroweb_omp_plugin"
    label = "omeroweb_omp_plugin"

    @staticmethod
    def ready() -> None:
        """Apply plugin-wide runtime configuration.

        Inputs: none. Output: None.
        """
        configure_omero_gateway_logging()
