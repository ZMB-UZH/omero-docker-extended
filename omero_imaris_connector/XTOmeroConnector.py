#
# <CustomTools>
#  <Menu>
#   <Item name="OMERO Connector" icon="OMERO" tooltip="Interact with OMERO">
#    <Command>Python3XT::XTOmeroConnector(%i)</Command>
#   </Item>
#  </Menu>
# </CustomTools>
#

"""
ImarisXT OMERO Connector
Requests server-side IMS conversion and opens the resulting IMS in Imaris.
"""

import contextlib
import datetime
import hashlib
import http.client
import http.cookiejar
import importlib
import io
import ipaddress
import json
import logging
import math
import ntpath
import os
import posixpath
import re
import select
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, List, Optional, Set, Tuple, cast

logger = logging.getLogger(__name__)
_NATIVE_PATH_CLASS = type(Path.cwd())


class _DeferredTkImport:
    """Placeholder for Tk modules until the platform gate has passed."""

    def __init__(self, module_name):
        """Create `_DeferredTkImport` for `module_name`.

        Inputs: `module_name`. Output: None.
        """
        self._module_name = module_name
        self._module = None

    def __setattr__(self, attribute, value):
        """Set attributes on the loaded module when available.

        Inputs: `attribute`, `value`. Output: None.
        """
        if attribute.startswith("_"):
            object.__setattr__(self, attribute, value)
            return
        loaded_module = object.__getattribute__(self, "_module")
        if loaded_module is None:
            object.__setattr__(self, attribute, value)
            return
        setattr(loaded_module, attribute, value)

    def __delattr__(self, attribute):
        """Delete attributes from the loaded module when available.

        Inputs: `attribute`. Output: None.
        """
        loaded_module = object.__getattribute__(self, "_module")
        if loaded_module is not None and hasattr(loaded_module, attribute):
            delattr(loaded_module, attribute)
            return
        object.__delattr__(self, attribute)

    def __getattr__(self, attribute):
        """Reject use before Tk has been imported deliberately.

        Inputs: `attribute`. Output: none. Raises: AttributeError.
        """
        loaded_module = object.__getattribute__(self, "_module")
        if loaded_module is not None:
            return getattr(loaded_module, attribute)
        raise AttributeError(
            f"{self._module_name} is not loaded; call _ensure_tk_loaded() first."
        )

    def is_loaded(self):
        """Return whether the backing Tk module has been imported.

        Inputs: no caller arguments. Output: bool.
        """
        return object.__getattribute__(self, "_module") is not None

    def load(self, loaded_module):
        """Store the imported backing module.

        Inputs: `loaded_module`. Output: None.
        """
        object.__setattr__(self, "_module", loaded_module)


tk: Any = _DeferredTkImport("tkinter")
filedialog: Any = _DeferredTkImport("tkinter.filedialog")
messagebox: Any = _DeferredTkImport("tkinter.messagebox")


class _ConnectorOperationCancelled(RuntimeError):
    """Raised when the user stops the current connector operation."""


# Default timeout/poll values for client-side export polling.
# These must NOT depend on server-side packages (omero_plugin_common)
# because this script runs inside Imaris on the user's machine.
EXPORT_TIMEOUT = 3600  # seconds
EXPORT_POLL_INTERVAL = 2.0  # seconds
DOWNLOAD_CHUNK_SIZE_ENV = "OMERO_IMARIS_DOWNLOAD_CHUNK_BYTES"
UNIQUE_DOWNLOAD_SUFFIX_ENV = "OMERO_IMARIS_UNIQUE_DOWNLOAD_SUFFIX"
DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
MIN_DOWNLOAD_CHUNK_SIZE_BYTES = 64 * 1024
MAX_DOWNLOAD_CHUNK_SIZE_BYTES = 64 * 1024 * 1024
DOWNLOAD_PROGRESS_UNIT_BYTES = 1024 * 1024
UPLOAD_CHUNK_SIZE_ENV = "OMERO_IMARIS_UPLOAD_CHUNK_BYTES"
DEFAULT_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
MIN_UPLOAD_CHUNK_SIZE_BYTES = 64 * 1024
MAX_UPLOAD_CHUNK_SIZE_BYTES = 64 * 1024 * 1024
FOLDER_EXPORT_TIMEOUT = 3600
FOLDER_EXPORT_POLL_INTERVAL = 2.0
FOLDER_EXPORT_CONFIRM_PREVIEW_LIMIT = 10
CANCEL_POLL_INTERVAL = 0.1
CANCELLABLE_HTTP_CONNECT_TIMEOUT_SECONDS = 2.0
CANCELLABLE_HTTP_POLL_INTERVAL_SECONDS = 0.1
CANCELLABLE_HTTP_MAX_HEADER_BYTES = 256 * 1024
HTTP_TRANSIENT_RETRY_ATTEMPTS_ENV = "OMERO_IMARIS_HTTP_RETRY_ATTEMPTS"
HTTP_TRANSIENT_RETRY_DELAY_ENV = "OMERO_IMARIS_HTTP_RETRY_DELAY_SECONDS"
DEFAULT_HTTP_TRANSIENT_RETRY_ATTEMPTS = 3
DEFAULT_HTTP_TRANSIENT_RETRY_DELAY_SECONDS = 2.0
REFRESH_REQUEST_TIMEOUT_ENV = "OMERO_IMARIS_REFRESH_TIMEOUT_SECONDS"
REFRESH_RETRY_ATTEMPTS_ENV = "OMERO_IMARIS_REFRESH_RETRY_ATTEMPTS"
REFRESH_RETRY_DELAY_ENV = "OMERO_IMARIS_REFRESH_RETRY_DELAY_SECONDS"
DEFAULT_REFRESH_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_REFRESH_RETRY_ATTEMPTS = 3
DEFAULT_REFRESH_RETRY_DELAY_SECONDS = 2.0
HEALTH_PING_INTERVAL_ENV = "OMERO_IMARIS_HEALTH_PING_INTERVAL_SECONDS"
HEALTH_PING_TIMEOUT_ENV = "OMERO_IMARIS_HEALTH_PING_TIMEOUT_SECONDS"
HEALTH_PING_RETRY_ATTEMPTS_ENV = "OMERO_IMARIS_HEALTH_PING_RETRY_ATTEMPTS"
HEALTH_PING_RETRY_DELAY_ENV = "OMERO_IMARIS_HEALTH_PING_RETRY_DELAY_SECONDS"
DEFAULT_HEALTH_PING_INTERVAL_SECONDS = 30
DEFAULT_HEALTH_PING_TIMEOUT_SECONDS = 10
DEFAULT_HEALTH_PING_RETRY_ATTEMPTS = 3
DEFAULT_HEALTH_PING_RETRY_DELAY_SECONDS = 1.0
IMARIS_HANDLE_RETRY_ATTEMPTS = 10
IMARIS_HANDLE_RETRY_INTERVAL = 0.25
NATIVE_BRIDGE_RUNNER_TIMEOUT = 600
NATIVE_BRIDGE_PROBE_TIMEOUT = 60
NATIVE_BRIDGE_REVALIDATION_TIMEOUT = 30
NATIVE_BRIDGE_REVALIDATE_AFTER = 30.0
IMARIS_OPEN_VERIFY_TIMEOUT = 10.0
IMARIS_OPEN_VERIFY_INTERVAL = 0.25
OMERO_IMS_EXPORT_CAPABILITY_FLAG = "omero_imaris_connector_v1"
OMERO_IMS_EXPORT_CAPABILITY_KEY = "omero_ims_export_capability"
OMERO_CONNECTOR_WINDOW_WIDTH = 1180
OMERO_CONNECTOR_WINDOW_HEIGHT = 760
MINIMUM_WINDOWS_MAJOR = 10
MINIMUM_WINDOWS_MINOR = 0
CONVERTER_MENU_FONT = ("Arial", 10)
CONVERTER_DROPDOWN_WIDTH = 116
CONVERTER_DROPDOWN_HEIGHT = 36
CONVERTER_DROPDOWN_TEXT_PAD = 10
CONVERTER_DROPDOWN_ARROW_WIDTH = 24
ACTION_ROW_HORIZONTAL_PAD = 10
ACTION_BUTTON_PAD = 0
ACTION_BUTTON_GAP = 4
STATUS_TEXT_PAD = ACTION_ROW_HORIZONTAL_PAD + ACTION_BUTTON_PAD
CONNECTION_LABEL_WIDTH = len("Local path:")
STATUS_NEUTRAL_BG = "#dfe5eb"
CONNECTOR_HELP_ICON_BG = "#b9e4ff"
CONNECTOR_HELP_ICON_ACTIVE_BG = "#9ed7f6"
CONNECTOR_HELP_ICON_FG = "#174a63"
CONNECTOR_INFO_ICON_BG = "#d8dee6"
CONNECTOR_INFO_ICON_ACTIVE_BG = "#c6ced8"
CONNECTOR_INFO_ICON_FG = "#2f3a45"
CONNECTOR_PANEL_ICON_SIZE = 32
CONNECTOR_PANEL_ICON_FRAME_HEIGHT = 42
CONNECTOR_PANEL_ICON_FONT = ("Segoe UI", 13, "bold")
PASSWORD_REVEAL_DURATION_MS = 30000
PASSWORD_REVEAL_BUTTON_SIZE = 18
REVEAL_ICON_BG = "#f8fafc"
REVEAL_ICON_ACTIVE_BG = "#e7f0fb"
REVEAL_ICON_FG = "#425466"
CLEARED_CREDENTIAL_TEXT = str()
AUTOSAVE_SETTINGS_FRAME_WIDTH = 450
AUTOSAVE_SETTINGS_OPTION_GAP = 34
CONVERTER_SLOT_WIDTH = 619
BROWSER_PANEL_DEFAULT_FRACTIONS = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
BROWSER_PANEL_MIN_FRACTION = 0.5 * (1.0 / 3.0)
BROWSER_PANEL_MAX_FRACTION = 1.5 * (1.0 / 3.0)
BROWSER_SPLITTER_WIDTH = 8
BOTTOM_PROGRESS_RESERVED_HEIGHT = 12
ENABLE_NATIVE_IMARIS_BRIDGE_ENV = "IMARIS_OMERO_CONNECTOR_ENABLE_ICEPY"
TEXT_INPUT_WIDGET_CLASSES = {
    "Entry",
    "TEntry",
    "Text",
    "Spinbox",
    "TSpinbox",
    "Combobox",
    "TCombobox",
}
FOLDER_PATH_SELECT_BG = "#718096"
FOLDER_PATH_SELECT_ACTIVE_BG = "#60738a"
FOLDER_PATH_PLACEHOLDER = "Type or select local path..."
FOLDER_PATH_PLACEHOLDER_FG = "#9ca3af"
FOLDER_PATH_TEXT_FG = "#111827"
BROWSER_SEARCH_PLACEHOLDER_FG = "#9ca3af"
BROWSER_SEARCH_TEXT_FG = "#111827"
BROWSER_DISABLED_BG = "#edf0f3"
BROWSER_DISABLED_FG = "#7a828a"
LOCAL_PATH_WRITE_ERROR_TITLE = "Path Not Writable"
LOCAL_PATH_WRITE_ERROR_MESSAGE = (
    "Please select or type an existing folder that Imaris can write to."
)
HOST_FIELD_SCHEME_ERROR_MESSAGE = (
    "Enter the OMERO.web host without http:// or https://. "
    "Use the HTTPS checkbox and Port field instead."
)
HOST_FIELD_PORT_ERROR_MESSAGE = (
    "Enter the OMERO.web host without a port. Use the Port field instead."
)
HOST_FIELD_INVALID_ERROR_MESSAGE = (
    "Enter a valid OMERO.web hostname or IP address only."
)
LOCAL_PATH_WRITE_TEST_PREFIX = ".omero_connector_write_test_"
PRIVATE_DIRECTORY_MODE = stat.S_IRWXU
PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
AUTOSAVE_SETTINGS_DIR_NAME = ".imaris_omero_connector"
AUTOSAVE_SETTINGS_FILE_NAME = "settings.env"
XT_LOG_FILE_NAME = "XTOmeroConnector.log"
XT_LOG_MAX_BYTES = 3 * 1024 * 1024
XT_LOG_BACKUP_COUNT = 3
AUTOSAVE_SETTINGS_ERROR_TITLE = "Settings Not Saved"
AUTOSAVE_SETTINGS_ERROR_MESSAGE = (
    "Autosave settings could not update the OMERO connector settings file."
)
CONNECTOR_INFO_TITLE = "Info"
CONNECTOR_INFO_VERSION = "1.0.0"
CONNECTOR_INFO_AUTHOR = "Efstratios Mitridis"
CONNECTOR_INFO_DISCLAIMER = (
    "This software is provided as-is, without warranty of any kind, express or "
    "implied. Use of the connector is at the user's own risk. No liability can "
    "be assumed for data loss or any other damages arising from its use."
)
CONNECTOR_HELP_TITLE = "Help"
CONNECTOR_HELP_SECTIONS = (
    (
        "Find images",
        (
            "Sign in with your OMERO account.",
            "Choose a project, then a dataset, then one or more images.",
            "Use Search to narrow the visible list and Refresh after OMERO changes.",
        ),
    ),
    (
        "Choose how to open",
        (
            "OMERO creates an IMS file and opens it in the current Imaris session.",
            "Imaris creates an OME-TIFF file and sends it to Imaris File Converter.",
            "Only choices that are ready to use are shown.",
        ),
    ),
    (
        "Save files",
        (
            "Choose the folder where the downloaded files should be saved.",
            "Files keep the selected OMERO image names by default.",
            "If names already exist in that folder, you can replace them, keep both copies, or cancel before anything starts.",
        ),
    ),
    (
        "Open several images",
        (
            "The connector saves every selected image first.",
            "With OMERO, the first IMS opens automatically and the rest stay in the chosen folder.",
            "With Imaris, all selected images are sent together when they are ready.",
        ),
    ),
    (
        "If something changes",
        (
            "If a newly uploaded image is missing, click Refresh.",
            "If Load is disabled, reconnect and choose an available converter.",
            "If a folder cannot be used, choose a different folder and try again.",
        ),
    ),
)
DUPLICATE_DOWNLOAD_POLICY_REPLACE = "replace"
DUPLICATE_DOWNLOAD_POLICY_UNIQUE = "unique"
CONNECTOR_SETTINGS_KEY_PREFIX = "OMERO_CONNECTOR_"
CONNECTOR_SETTINGS_HOST_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "HOST"
CONNECTOR_SETTINGS_PORT_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "PORT"
CONNECTOR_SETTINGS_USERNAME_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "USER" + "NAME"
CONNECTOR_SETTINGS_HTTPS_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "HTTPS"
CONNECTOR_SETTINGS_PATH_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "PATH"
CONNECTOR_SETTINGS_CONVERTER_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "CONVERTER"
CONNECTOR_SETTINGS_AUTOSAVE_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "AUTOSAVE_SETTINGS"
CONNECTOR_SETTINGS_SHOW_LOG_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "SHOW_LOG"
CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY = (
    CONNECTOR_SETTINGS_KEY_PREFIX + "SEARCH_FUNCTION"
)
CONNECTOR_SETTINGS_COLLABORATION_PROJECTS_KEY = (
    CONNECTOR_SETTINGS_KEY_PREFIX + "COLLABORATION_PROJECTS"
)
CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY = (
    CONNECTOR_SETTINGS_KEY_PREFIX + "APPEND_OBSERVED_FOLDERS"
)
CONNECTOR_SETTINGS_IMARIS_EXE_KEY = "IMARIS_EXE"
CONNECTOR_SETTINGS_VERSION_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "VERSION"
IMARIS_ARENA_DATA_MANAGEMENT_SUBKEY = "DataManagementSystem"
IMARIS_ARENA_VENDOR_REGISTRY_ROOT = r"Software\Bitplane"
IMARIS_ARENA_OBSERVED_FOLDERS_LIST_NAME = "Observed Folders"
IMARIS_ARENA_OBSERVED_FOLDERS_VALUE = IMARIS_ARENA_OBSERVED_FOLDERS_LIST_NAME
IMARIS_ARENA_OBSERVED_FOLDERS_TREE_STATE_VALUE = "Observed Folders_TreeState"
CONNECTOR_SETTINGS_KEYS = (
    CONNECTOR_SETTINGS_HOST_KEY,
    CONNECTOR_SETTINGS_PORT_KEY,
    CONNECTOR_SETTINGS_USERNAME_KEY,
    CONNECTOR_SETTINGS_HTTPS_KEY,
    CONNECTOR_SETTINGS_CONVERTER_KEY,
    CONNECTOR_SETTINGS_AUTOSAVE_KEY,
    CONNECTOR_SETTINGS_SHOW_LOG_KEY,
    CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY,
    CONNECTOR_SETTINGS_COLLABORATION_PROJECTS_KEY,
    CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY,
    CONNECTOR_SETTINGS_IMARIS_EXE_KEY,
    CONNECTOR_SETTINGS_VERSION_KEY,
)
CONNECTOR_SETTINGS_DEPRECATED_KEYS = (CONNECTOR_SETTINGS_PATH_KEY,)
OMERO_LOGOMARK_SOURCE_URL = "https://www.openmicroscopy.org/img/logos/ome-logomark.svg"
OMERO_LOGOMARK_SVG_SHA256 = "".join(
    (
        "55646a0742bb001c",
        "6678cbabae8ae939",
        "d88c0f37e074527d",
        "aadc289d8c7ac539",
    )
)
OMERO_LOGOMARK_SVG_BYTES = (
    b'<?xml version="1.0" encoding="utf-8"?>\n<!-- Generator: Adobe Illustrator'
    b" 19.2.1, SVG Export Plug-In . SVG Version: 6.00 Build 0)  -->\n<svg versi"
    b'on="1.1" id="logo_-_color" xmlns="http'
    b'://www.w3.org/2000/svg" xmlns:xlin'
    b'k="http'
    b'://www.w3.org/1999/xlink" x="0px"\n\t y="0px" viewBox="0 0 1024 896'
    b'" style="enable-background:new 0 0 1024 896;" xml:space="preserve">\n<sty'
    b'le type="text/css">\n\t.st0{fill:#DF283F;}\n\t.st1{fill:#1C4A87;}\n\t.st2{fill'
    b':#128669;}\n\t.st3{fill:#1D8DCD;}\n</style>\n<g>\n\t<g>\n\t\t<path class="st0" d='
    b'"M256,448c0,70.7-57.3,128-128,128S0,518.7,0,448s57.3-128,128-128S256,377'
    b'.3,256,448z"/>\n\t\t<path class="st1" d="M1024,448c0,70.7-57.3,128-128,128s'
    b'-128-57.3-128-128s57.3-128,128-128S1024,377.3,1024,448z"/>\n\t\t<path class'
    b'="st2" d="M832,128c0,70.7-57.3,128-128,128s-128-57.3-128-128S633.3,0,704'
    b',0S832,57.3,832,128z"/>\n\t\t<path class="st1" d="M448,128c0,70.7-57.3,128-'
    b'128,128s-128-57.3-128-128S249.3,0,320,0S448,57.3,448,128z"/>\n\t\t<path cla'
    b'ss="st3" d="M832,768c0,70.7-57.3,128-128,128s-128-57.3-128-128s57.3-128,'
    b'128-128S832,697.3,832,768z"/>\n\t\t<path class="st1" d="M448,768c0,70.7-57.'
    b'3,128-128,128s-128-57.3-128-128s57.3-128,128-128S448,697.3,448,768z"/>\n\t'
    b"</g>\n</g>\n</svg>\n"
)
OMERO_LOGOMARK_PNG64_SHA256 = "".join(
    (
        "4bf9098f0cdfb804",
        "2a4a9f6a4f079673",
        "b6a534f2bd0b7b87",
        "a80fc99141595613",
    )
)
OMERO_LOGOMARK_PNG64_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAAA4CAYAAABNGP5yAAAFIElEQVRo3u2aTWxU"
    "VRTHf/PSqgm21IqtJrowceFeERXwa8FCXfiB8YMUNFHUnegGTDDRxLpyCTXqwk+U"
    "aLsBtRJjqNF2IbBm56JkiqFo6Uwi0ARd3HNn7rxO37vn3vemQ+QkTZq27//O+d/X"
    "+879zakQEDc//J79thd4CNgObAJukp//CfwKfA78BFwEOPX9Hi/9wdFXXf0HRX9z"
    "Sv834DNX/683x9S19IQYIDEM7AZGgOvTHgHPAFuAr4B3gTml/pCjv66N/tOifwAY"
    "BaohRVS0F8jqDwNjwOOelx0GXgaqeU+BrP6Qo++T43fATqCqfQqSANN6gT3AY4pr"
    "HgX2Alcp9H2LB3gEeAu4WluMygBZ/buBHYrkbDwHbHb2j2Uhq78hRt/ZP4o3QJLa"
    "CgworwPoB57KuafVvy5Av89DP9qAa4H1AcnZuFOMWCnWFKC/tkwD+jAbVGisy0mw"
    "vwD9fs0FIf8C3R6qHLUGLAJnIpI7KxorRa0A/XNlGlAHjkUkeDwnwTrwe4n60Qb8"
    "C3yrvYlEDfgGuJSjPw4sBOjXJbdLmotUBkgXNwN8Iclq4mvgl6xOULq4GcwZIkT/"
    "aCc6wYuY3v6w4ppJ4B3ggsffLmF6+0MK/R+Btz314wyQFZzD9Pb7yf53WAQ+Al4C"
    "TvnoywqeBl4B9uXo10T/RV/9dMScBueA14AJ4ElMA2NPbWcxG9I4cBTlcdjR3yX6"
    "WzFNzg1t9KeQlQ85Dge/19v09AM0m5BFUhuZsnja9PSZ+iHFRxmQYURLaAv3MKI"
    "lQgtf0YA/br8/84JbT05F3bDs0C5IiwGp4vvkC8xmU+t2I1LFu/nXSXWg1ohKqvA"
    "e4F7gCeAumpvOPKZDm8CwuKVuMsEpvAe4h+ambA9W85gOdgLDKpesCa4BwxgSMwI"
    "MrnCvBeBLhPF1mQFDkv/2nPwPSP5VgIoUPwR8gD/jO4TpA1bdBKf4/ZgnV8UQEwy"
    "nK5PxlR29GHrsWzwYhrgXuCYBHsA8NppXYgXYBmzKe2uUGbL6G4DnlfkDPAtsSTA"
    "AclB5MTQZ32pCkgpmwwthiGuBFxLMJy6hsR4lgys41mDeVqGxMQFujBBQM7iCo4/"
    "mqzoo/4TLg/NlRVT+CeboGRp5jK/sqBPJEBNMZxcax7rAgBiGOJ0AnxLG4GoEMLi"
    "CI4Yh1oBPEuBnIhjfanaCDqMMYYgHgckEQ1NGMe2hb2gYX9kRwhCPSP7/JLKClvG"
    "NUTDjKzvkKbAMMY9R1oCPMQxxFlqZYBXD+MZZzuDmacP4VvsglArLKG3+llFWJP8"
    "TTv4XrHmNd2ibnn4A0+RUxNUF95ddVnwWo6zQZIiNfaIFiLjxv0ZinbihNm55/3j"
    "m72ffuCNKP8qADAa3jCGGGJEqPlM/1IggAzwY3BmaDK7BEH1NcAq3+pZRZuqHmBD"
    "zyVAWg7tNEh/BYYgB+rtpzyuK0AfC5wS1c3wNhpj3FMjqaxlfYw5R+xTEzAlq5v"
    "i0c4JaxhfMKDs1J2gZYuacoKx+KOPbBtyX99aIMoA4Buc7Jxiq37E5wRgG5zMnGK"
    "t/ZU6wTAMuB354ZU6wTAM6MScYo3+ibAMsgwuZE/SZ44udE8ybQ4wzQLq4acIZ4l"
    "RWJyhdXOgc4kHMwJQqYuYENQxRM8cXMod4RPTPl94KO3OCOzH9+t8Zf34O+BDFHJ"
    "8UcBrT2+/z0LdzgrPaWiB+TnAXhhDvADbSOpIyjfnMYRI475in0X8d8/S0058R/R"
    "+sfshx+D8g375eb+s8dAAAAABJRU5ErkJggg=="
)
_ROUNDED_BUTTON_OPTION_ALIASES = {
    "background": "bg",
    "foreground": "fg",
}
_ROUNDED_BUTTON_REDRAW_FIELDS = {
    "activebackground": "_active_bg",
    "activeforeground": "_active_fg",
    "bg": "_bg",
    "fg": "_fg",
    "font": "_font",
    "text": "_text",
}
_XT_DLL_DIR_HANDLES: List[Any] = []
_WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
_WINDOWS_PATH_COMPONENT_INVALID_CHARS = frozenset('<>:"|?*')


@dataclass
class _XtRuntimeState:
    """Data container for XT runtime state."""

    log_path: Optional[str] = None
    console_output_enabled: bool = True


_XT_LOG_LOCK = threading.Lock()


@dataclass
class _WindowsVersion:
    """Detected Windows kernel version details."""

    major: int
    minor: int
    build: int
    source: str


@dataclass
class _WindowsPlatformStatus:
    """Startup platform support result for the standalone XT connector."""

    supported: bool
    message: str
    version: Optional[_WindowsVersion] = None


_XT_RUNTIME_STATE = _XtRuntimeState()


_NATIVE_BRIDGE_OPEN_HELPER = r"""
import json
import os
import sys
import time

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
OPEN_VERIFY_TIMEOUT = 10.0
OPEN_VERIFY_INTERVAL = 0.25


def _iter_imaris_xt_path_candidates(install_root):
    yield install_root
    yield os.path.join(install_root, "XT")
    yield os.path.join(install_root, "XT", "python3")
    yield os.path.join(install_root, "XT", "python3", "DLLs")
    yield os.path.join(install_root, "XT", "bin")
    yield os.path.join(install_root, "XT", "python3", "Lib")
    yield os.path.join(install_root, "XT", "python3", "Lib", "site-packages")
    yield os.path.join(install_root, "XT", "python3", "private")
    yield os.path.join(install_root, "XT", "python3", "private", "Ice")
    yield os.path.join(install_root, "XT", "python")
    yield os.path.join(install_root, "XT", "lib")


def _is_ims_file(file_path):
    if not os.path.isfile(file_path):
        return False
    try:
        with open(file_path, "rb") as handle:
            return handle.read(len(HDF5_SIGNATURE)) == HDF5_SIGNATURE
    except Exception:
        return False


def _prepare_imaris_xt_environment(install_roots):
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    added = []
    for install_root in install_roots:
        for candidate in _iter_imaris_xt_path_candidates(install_root):
            if not os.path.isdir(candidate):
                continue
            normalized = os.path.normpath(candidate)
            if normalized not in sys.path:
                sys.path.insert(0, normalized)
            if normalized not in path_parts:
                path_parts.insert(0, normalized)
            if callable(add_dll_directory):
                try:
                    add_dll_directory(normalized)
                except Exception as exc:
                    print(
                        "BRIDGE_RUNNER_DLL_DIR_WARNING:" + type(exc).__name__,
                        file=sys.stderr,
                    )
                    continue
            added.append(normalized)
    os.environ["PATH"] = os.pathsep.join(path_parts)
    return added


def _get_imaris_application(app_id, retries, retry_interval):
    import ImarisLib

    get_application_methods = []
    lib_factory = getattr(ImarisLib, "ImarisLib", None)
    if callable(lib_factory):
        try:
            lib = lib_factory()
        except Exception:
            lib = None
        if lib is not None:
            get_application = getattr(lib, "GetApplication", None)
            if callable(get_application):
                get_application_methods.append(get_application)

    get_application = getattr(ImarisLib, "GetApplication", None)
    if callable(get_application):
        get_application_methods.append(get_application)

    if not get_application_methods:
        return None

    attempts = max(1, int(retries or 1))
    for attempt in range(attempts):
        for get_application in get_application_methods:
            try:
                app = get_application(app_id)
            except Exception:
                app = None
            if app is not None:
                return app

        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(retry_interval)))

    return None


def _file_open_call_candidates(file_path, verification_mode="current_file"):
    if verification_mode == "current_file":
        return (
            ("FileOpen", (file_path, "")),
            ("FileOpen", (file_path,)),
            ("OpenFile", (file_path, "")),
            ("OpenFile", (file_path,)),
            ("LoadFile", (file_path, "")),
            ("LoadFile", (file_path,)),
        )
    return (
        ("FileOpen", (file_path,)),
        ("FileOpen", (file_path, "")),
        ("OpenFile", (file_path,)),
        ("OpenFile", (file_path, "")),
        ("LoadFile", (file_path,)),
        ("LoadFile", (file_path, "")),
    )


def _data_set_signature(data_set):
    if data_set is None:
        return None
    values = []
    for method_name in ("GetSizeX", "GetSizeY", "GetSizeZ", "GetSizeC", "GetSizeT"):
        method = getattr(data_set, method_name, None)
        if not callable(method):
            values.append(None)
            continue
        try:
            values.append(int(method()))
        except Exception:
            values.append(None)
    return tuple(values) if any(value is not None for value in values) else "present"


def _data_set_has_content(data_set):
    if data_set is None:
        return False
    positive_dimension_seen = False
    for method_name in ("GetSizeX", "GetSizeY", "GetSizeZ", "GetSizeC", "GetSizeT"):
        method = getattr(data_set, method_name, None)
        if not callable(method):
            continue
        try:
            value = int(method())
        except Exception:
            return False
        if value <= 0:
            return False
        positive_dimension_seen = True
    return positive_dimension_seen


def _current_data_set(app):
    get_data_set = getattr(app, "GetDataSet", None)
    if not callable(get_data_set):
        return None
    try:
        return get_data_set()
    except Exception:
        return None


def _ensure_current_dataset_visible(app, data_set=None):
    if data_set is None:
        data_set = _current_data_set(app)
    if not _data_set_has_content(data_set):
        return False
    set_data_set = getattr(app, "SetDataSet", None)
    if callable(set_data_set):
        try:
            if set_data_set(data_set) is not False:
                return True
        except Exception:
            pass
    set_image = getattr(app, "SetImage", None)
    if callable(set_image):
        try:
            if set_image(0, data_set) is not False:
                return True
        except Exception:
            pass
    return False


def _imaris_app_snapshot(app):
    current = ""
    getter = _current_file_getter(app)
    if getter is not None:
        try:
            current = _normalize_path_for_compare(getter())
        except Exception:
            current = ""

    image_count = None
    get_count = getattr(app, "GetNumberOfImages", None)
    if callable(get_count):
        try:
            image_count = int(get_count())
        except Exception:
            image_count = None

    data_set_signature = None
    get_data_set = getattr(app, "GetDataSet", None)
    if callable(get_data_set):
        try:
            data_set_signature = _data_set_signature(get_data_set())
        except Exception:
            data_set_signature = None

    return current, image_count, data_set_signature


def _snapshot_changed_after_open(before, current_snapshot, expected_path):
    current, image_count, data_set_signature = current_snapshot
    before_current, before_image_count, before_data_set_signature = before
    if expected_path and current and current == expected_path:
        return True
    if current and current != before_current:
        return True
    if (
        image_count is not None
        and before_image_count is not None
        and image_count != before_image_count
    ):
        return True
    if (
        data_set_signature is not None
        and before_data_set_signature is not None
        and data_set_signature != before_data_set_signature
    ):
        return True
    return data_set_signature is not None and before_data_set_signature is None


def _wait_for_open_observable_effect(app, before, expected_path):
    expected = _normalize_path_for_compare(expected_path)
    deadline = time.time() + OPEN_VERIFY_TIMEOUT
    while time.time() <= deadline:
        if _snapshot_changed_after_open(before, _imaris_app_snapshot(app), expected):
            return True
        time.sleep(OPEN_VERIFY_INTERVAL)
    return False


def _wait_for_verified_open(app, getter, before, expected_path, before_data_set=None):
    expected = _normalize_path_for_compare(expected_path)
    deadline = time.time() + OPEN_VERIFY_TIMEOUT
    while time.time() <= deadline:
        if getter is not None:
            try:
                current = _normalize_path_for_compare(getter())
            except Exception:
                current = ""
            if expected and current and current == expected:
                _ensure_current_dataset_visible(app)
                return True
        snapshot_changed = _snapshot_changed_after_open(
            before,
            _imaris_app_snapshot(app),
            expected,
        )
        data_set = _current_data_set(app)
        data_set_changed = data_set is not None and data_set is not before_data_set
        if (
            (snapshot_changed or data_set_changed)
            and _data_set_has_content(data_set)
            and _ensure_current_dataset_visible(app, data_set)
        ):
            return True
        time.sleep(OPEN_VERIFY_INTERVAL)
    return False


def _open_file_in_imaris(file_path, app, verification_mode="current_file"):
    getter = _current_file_getter(app)
    for method_name, args in _file_open_call_candidates(
        file_path,
        verification_mode=verification_mode,
    ):
        method = getattr(app, method_name, None)
        if not callable(method):
            continue
        before = _imaris_app_snapshot(app)
        before_data_set = _current_data_set(app)
        try:
            result = method(*args)
        except TypeError:
            continue
        except Exception:
            raise
        if result is False:
            continue
        if verification_mode == "submission_only":
            return True
        if verification_mode == "current_file":
            if _wait_for_verified_open(
                app,
                getter,
                before,
                file_path,
                before_data_set,
            ):
                return True
            continue
        if _wait_for_open_observable_effect(app, before, file_path):
            if verification_mode == "observable_effect":
                _ensure_current_dataset_visible(app)
                return True
    return False


def _open_files_in_imaris(
    file_paths,
    app,
    require_ims=True,
):
    if isinstance(file_paths, (str, bytes, os.PathLike)):
        file_paths = [file_paths]
    if not isinstance(file_paths, list) or not file_paths:
        return False

    validated = []
    for file_path in file_paths:
        try:
            path_text = os.fspath(file_path)
        except TypeError:
            return False
        if isinstance(path_text, bytes) or "\x00" in path_text:
            return False
        if not os.path.isfile(path_text):
            return False
        if not require_ims or not _is_ims_file(path_text):
            return False
        validated.append(path_text)

    if len(validated) == 1:
        return _open_file_in_imaris(
            validated[0],
            app,
            verification_mode="current_file",
        )
    return _open_files_as_imaris_image_slots(validated, app)


def _clone_current_dataset(app):
    get_data_set = getattr(app, "GetDataSet", None)
    if not callable(get_data_set):
        return None
    data_set = get_data_set()
    clone = getattr(data_set, "Clone", None)
    if not callable(clone):
        return None
    return clone()


def _wait_for_image_count(app, expected_count):
    get_count = getattr(app, "GetNumberOfImages", None)
    if not callable(get_count):
        return True
    deadline = time.time() + OPEN_VERIFY_TIMEOUT
    while time.time() <= deadline:
        try:
            if int(get_count()) >= int(expected_count):
                return True
        except Exception:
            return False
        time.sleep(OPEN_VERIFY_INTERVAL)
    return False


def _open_files_as_imaris_image_slots(file_paths, app):
    set_image = getattr(app, "SetImage", None)
    if not callable(set_image):
        return False

    data_sets = []
    for file_path in file_paths:
        if not _open_file_in_imaris(
            file_path,
            app,
            verification_mode="observable_effect",
        ):
            return False
        data_set = _clone_current_dataset(app)
        if data_set is None:
            return False
        data_sets.append(data_set)

    for index, data_set in enumerate(data_sets):
        set_image(index, data_set)
    return _wait_for_image_count(app, len(data_sets))


def _current_file_getter(app):
    for method_name in ("GetCurrentFileName", "GetCurrentFilePath"):
        method = getattr(app, method_name, None)
        if callable(method):
            return method
    return None


def _normalize_path_for_compare(path_value):
    try:
        path_text = os.fspath(path_value)
    except TypeError:
        return ""
    if isinstance(path_text, bytes) or not path_text:
        return ""
    try:
        path_text = os.path.abspath(path_text)
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(path_text))
    return os.path.normcase(os.path.normpath(path_text))


def _has_open_method(app):
    return any(
        callable(getattr(app, method_name, None))
        for method_name in ("FileOpen", "OpenFile", "LoadFile")
    )


def main():
    payload = json.loads(sys.stdin.read())
    global OPEN_VERIFY_TIMEOUT, OPEN_VERIFY_INTERVAL
    try:
        OPEN_VERIFY_TIMEOUT = max(
            0.0,
            float(payload.get("open_verify_timeout", OPEN_VERIFY_TIMEOUT)),
        )
    except (TypeError, ValueError):
        pass
    try:
        OPEN_VERIFY_INTERVAL = max(
            0.0,
            float(payload.get("open_verify_interval", OPEN_VERIFY_INTERVAL)),
        )
    except (TypeError, ValueError):
        pass
    app_id = int(payload["app_id"])
    install_roots = [os.fspath(path) for path in payload.get("install_roots", [])]
    _prepare_imaris_xt_environment(install_roots)
    app = _get_imaris_application(
        app_id,
        payload.get("retry_attempts", 1),
        payload.get("retry_interval", 0.25),
    )
    if app is None:
        print("BRIDGE_RUNNER_HANDLE_UNAVAILABLE")
        return 2
    if payload.get("mode") == "probe":
        if not _has_open_method(app):
            print("BRIDGE_RUNNER_OPEN_METHOD_UNAVAILABLE")
            return 3
        print("BRIDGE_RUNNER_PROBE_OK")
        return 0
    file_paths = payload.get("file_paths")
    if file_paths is None:
        file_paths = [payload["file_path"]]
    if not isinstance(file_paths, list):
        print("BRIDGE_RUNNER_INVALID_FILE_LIST")
        return 64
    if not file_paths:
        print("BRIDGE_RUNNER_INVALID_FILE_LIST")
        return 64
    require_ims = payload.get("require_ims", True) is not False
    if not require_ims:
        print("BRIDGE_RUNNER_INVALID_FILE_LIST")
        return 64
    for file_path in file_paths:
        try:
            file_path = os.fspath(file_path)
        except TypeError:
            print("BRIDGE_RUNNER_INVALID_FILE_LIST")
            return 64
        if isinstance(file_path, bytes) or "\x00" in file_path:
            print("BRIDGE_RUNNER_INVALID_FILE_LIST")
            return 64
        if not os.path.isfile(file_path):
            print("BRIDGE_RUNNER_MISSING_FILE")
            return 64
        if require_ims and not _is_ims_file(file_path):
            print("BRIDGE_RUNNER_INVALID_IMS")
            return 64
    if not _open_files_in_imaris(
        file_paths,
        app,
        require_ims=require_ims,
    ):
        print("BRIDGE_RUNNER_OPEN_UNVERIFIED")
        return 4
    print("BRIDGE_RUNNER_OPENED_MANY" if len(file_paths) > 1 else "BRIDGE_RUNNER_OPENED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("BRIDGE_RUNNER_EXCEPTION:" + type(exc).__name__)
        raise SystemExit(70)
"""


def _coerce_path(value):
    """Coerce the path.

    Inputs: `value` input value. Output: `Path` object.
    """
    try:
        path_text = os.fspath(value)
    except TypeError:
        return None
    if isinstance(path_text, bytes):
        return None
    if not path_text or "\x00" in path_text:
        return None
    try:
        return _NATIVE_PATH_CLASS(path_text)
    except (OSError, TypeError, ValueError, RuntimeError):
        return None


def _native_path_is_absolute(value):
    """Return whether `value` is absolute on the host platform.

    Inputs: `value`. Output: bool.
    """
    candidate = _coerce_path(value)
    return bool(candidate is not None and candidate.is_absolute())


def _existing_regular_file_path(file_path):
    """Return existing regular file path.

    Inputs: `file_path` file path. Output: `Path` or path text.
    """
    candidate = _coerce_path(file_path)
    if candidate is None:
        return None
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _safe_xt_log_file(log_path):
    """Return safe XT log file.

    Inputs: `log_path`. Output: `candidate` or None.
    """
    candidate = _coerce_path(log_path)
    if candidate is None or not candidate.is_absolute():
        return None
    if candidate.name != XT_LOG_FILE_NAME:
        return None
    try:
        expected_parent = _connector_settings_env_path().parent
    except OSError:
        return None
    if candidate.parent != expected_parent:
        return None
    try:
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            return None
        if candidate.parent.is_symlink() or (
            candidate.parent.exists() and not candidate.parent.is_dir()
        ):
            return None
    except OSError:
        return None
    return candidate


def _sanitize_xt_log_message(message):
    """Redact credentials, session material, and local user paths from diagnostics.

    Inputs: `message`. Output: `text`.
    """
    text = str(message)
    redactions = (
        (r"(?i)(sessionid\s*[=:]\s*)[^&\s,;]+", r"\1<redacted>"),
        (r"(?i)(csrftoken\s*[=:]\s*)[^&\s,;]+", r"\1<redacted>"),
        (r"(?i)(csrfmiddlewaretoken\s*[=:]\s*)[^&\s,;]+", r"\1<redacted>"),
        (r"(?i)(x-csrftoken\s*[=:]\s*)[^&\s,;]+", r"\1<redacted>"),
        (r"(?i)(password\s*[=:]\s*)[^&\s,;]+", r"\1<redacted>"),
    )
    for pattern, replacement in redactions:
        text = re.sub(pattern, replacement, text)

    for env_name in ("USERPROFILE", "HOME"):
        home_path = os.environ.get(env_name) or ""
        if home_path:
            normalized = os.path.normpath(home_path)
            text = text.replace(normalized, f"%{env_name}%")
            text = text.replace(home_path, f"%{env_name}%")

    text = re.sub(
        r"(?i)\b([A-Z]:\\Users\\)[^\\\r\n]+",
        r"\1<user>",
        text,
    )
    text = re.sub(r"(?i)\b(/home/)[^/\s]+", r"\1<user>", text)
    text = re.sub(r"(?i)\b(/Users/)[^/\s]+", r"\1<user>", text)
    return text


def _native_imaris_bridge_enabled():
    """Return whether IcePy-backed native Imaris bridge code is enabled.

    Inputs: none. Output: bool.
    """
    value = os.environ.get(ENABLE_NATIVE_IMARIS_BRIDGE_ENV, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


VISIBLE_LOG_QUERY_VALUE_KEYS = {"group", "username"}


def _safe_log_query_key(key):
    """Return a bounded, log-safe query key.

    Inputs: `key`. Output: sanitized key text.
    """
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:64] or "param"


def _safe_visible_log_query_value(value):
    """Return a safe visible query value or None when it must be redacted.

    Inputs: `value`. Output: sanitized visible value or None.
    """
    text = str(value or "")
    if (
        "://" in text
        or "/" in text
        or "\\" in text
        or any(ord(char) < 32 for char in text)
        or len(text) > 128
    ):
        return None
    return re.sub(r"[^A-Za-z0-9 @._:+-]", "_", text) or "<empty>"


def _safe_log_query_pair(key, value):
    """Return a redacted-or-visible log-safe query pair.

    Inputs: `key`, `value`. Output: `(safe_key, safe_value)`.
    """
    safe_key = _safe_log_query_key(key)
    if safe_key.lower() in VISIBLE_LOG_QUERY_VALUE_KEYS:
        safe_value = _safe_visible_log_query_value(value)
        if safe_value is not None:
            return safe_key, safe_value
    return safe_key, "<redacted>"


def _safe_url_for_log(url):
    """Return a diagnostic URL shape without hostnames, IDs, or sensitive query values.

    Inputs: `url` URL. Output: URL string.
    """
    try:
        parsed = urllib.parse.urlparse(str(url))
    except Exception:
        return "<url>"
    path = parsed.path or "/"
    path = re.sub(r"(?<=/)\d+(?=/|$)", "<id>", path)
    if not parsed.query:
        return path

    safe_pairs: List[Tuple[str, str]] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        safe_key, safe_value = _safe_log_query_pair(key, value)
        if any(pair_key == safe_key for pair_key, _pair_value in safe_pairs):
            continue
        safe_pairs.append((safe_key, safe_value))
    if not safe_pairs:
        return path
    query = "&".join(f"{key}={value}" for key, value in safe_pairs)
    return f"{path}?{query}"


def _download_chunk_size_bytes():
    """Return a bounded download buffer size for streaming HTTP responses.

    Inputs: none. Output: `int` size.
    """
    raw_value = os.environ.get(DOWNLOAD_CHUNK_SIZE_ENV, "").strip()
    if not raw_value:
        return DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES
    try:
        value = int(raw_value, 10)
    except ValueError:
        return DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES
    return max(
        MIN_DOWNLOAD_CHUNK_SIZE_BYTES,
        min(value, MAX_DOWNLOAD_CHUNK_SIZE_BYTES),
    )


def _unique_download_suffix_enabled():
    """Return whether duplicate downloads should use timestamped suffixes.

    Inputs: process environment. Output: bool.
    """
    return _connector_settings_bool(os.environ.get(UNIQUE_DOWNLOAD_SUFFIX_ENV), False)


def _bounded_env_int(env_name, default, minimum, maximum):
    """Return a bounded integer from the environment.

    Inputs: `env_name`, `default`, `minimum`, `maximum`. Output: bounded maximum value.
    """
    raw_value = os.environ.get(env_name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value, 10)
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _bounded_env_float(env_name, default, minimum, maximum):
    """Return a bounded float from the environment.

    Inputs: `env_name`, `default`, `minimum`, `maximum`. Output: bounded maximum value.
    """
    raw_value = os.environ.get(env_name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _http_retry_attempts():
    """Return transient HTTP retry attempts for connector requests.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        HTTP_TRANSIENT_RETRY_ATTEMPTS_ENV,
        DEFAULT_HTTP_TRANSIENT_RETRY_ATTEMPTS,
        1,
        10,
    )


def _http_retry_delay_seconds():
    """Return transient HTTP retry delay in seconds.

    Inputs: none. Output: `_bounded_env_float` result.
    """
    return _bounded_env_float(
        HTTP_TRANSIENT_RETRY_DELAY_ENV,
        DEFAULT_HTTP_TRANSIENT_RETRY_DELAY_SECONDS,
        0.0,
        30.0,
    )


def _refresh_request_timeout_seconds():
    """Return bounded timeout for each refresh request.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        REFRESH_REQUEST_TIMEOUT_ENV,
        DEFAULT_REFRESH_REQUEST_TIMEOUT_SECONDS,
        5,
        300,
    )


def _refresh_retry_attempts():
    """Return refresh retry attempts.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        REFRESH_RETRY_ATTEMPTS_ENV,
        DEFAULT_REFRESH_RETRY_ATTEMPTS,
        1,
        10,
    )


def _refresh_retry_delay_seconds():
    """Return refresh retry delay in seconds.

    Inputs: none. Output: `_bounded_env_float` result.
    """
    return _bounded_env_float(
        REFRESH_RETRY_DELAY_ENV,
        DEFAULT_REFRESH_RETRY_DELAY_SECONDS,
        0.0,
        30.0,
    )


def _health_ping_interval_seconds():
    """Return read-only health ping interval in seconds.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        HEALTH_PING_INTERVAL_ENV,
        DEFAULT_HEALTH_PING_INTERVAL_SECONDS,
        5,
        3600,
    )


def _health_ping_timeout_seconds():
    """Return read-only health ping timeout in seconds.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        HEALTH_PING_TIMEOUT_ENV,
        DEFAULT_HEALTH_PING_TIMEOUT_SECONDS,
        2,
        120,
    )


def _health_ping_retry_attempts():
    """Return health ping retry attempts before declaring the connection lost.

    Inputs: none. Output: `_bounded_env_int` result.
    """
    return _bounded_env_int(
        HEALTH_PING_RETRY_ATTEMPTS_ENV,
        DEFAULT_HEALTH_PING_RETRY_ATTEMPTS,
        1,
        10,
    )


def _health_ping_retry_delay_seconds():
    """Return delay between failed health ping attempts.

    Inputs: none. Output: `_bounded_env_float` result.
    """
    return _bounded_env_float(
        HEALTH_PING_RETRY_DELAY_ENV,
        DEFAULT_HEALTH_PING_RETRY_DELAY_SECONDS,
        0.0,
        30.0,
    )


def _is_transient_network_error(error):
    """Return True for network failures that are safe to retry.

    Inputs: `error`. Output: `bool`.
    """
    transient_types = (
        ConnectionResetError,
        TimeoutError,
        socket.timeout,
        http.client.BadStatusLine,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
    )
    if isinstance(error, transient_types):
        return True
    if isinstance(error, urllib.error.URLError):
        reason = getattr(error, "reason", None)
        if isinstance(reason, transient_types):
            return True
        return any(
            marker in str(error).lower()
            for marker in (
                "connection reset",
                "forcibly closed",
                "timed out",
                "temporarily unavailable",
            )
        )
    return False


def _upload_chunk_size_bytes():
    """Return a bounded upload chunk size for streaming multipart requests.

    Inputs: none. Output: `int` size.
    """
    raw_value = os.environ.get(UPLOAD_CHUNK_SIZE_ENV, "").strip()
    if not raw_value:
        return DEFAULT_UPLOAD_CHUNK_SIZE_BYTES
    try:
        value = int(raw_value, 10)
    except ValueError:
        return DEFAULT_UPLOAD_CHUNK_SIZE_BYTES
    return max(
        MIN_UPLOAD_CHUNK_SIZE_BYTES,
        min(value, MAX_UPLOAD_CHUNK_SIZE_BYTES),
    )


def _folder_display_name(folder_path):
    """Return the folder display name.

    Inputs: `folder_path` folder path. Output: `strip` result.
    """
    candidate = _coerce_path(folder_path)
    if candidate is None:
        return ""
    normalized = os.path.normpath(candidate)
    name = os.path.basename(normalized).strip()
    if name:
        return name
    drive, _tail = os.path.splitdrive(normalized)
    return drive.rstrip(":\\/").strip()


def _display_local_path(path_value):
    """Return a local path string using the host platform separator.

    Inputs: `path_value`. Output: display path string.
    """
    candidate = _coerce_path(path_value)
    if candidate is None:
        return ""
    path_text = os.fspath(candidate)
    if os.name == "nt":
        return path_text.replace("/", "\\")
    return path_text


def _is_filesystem_root(folder_path):
    """Return whether filesystem root.

    Inputs: `folder_path`. Output: bool.
    """
    candidate = _coerce_path(folder_path)
    if candidate is None:
        return False

    normalized = os.path.normpath(candidate)
    if os.path.dirname(normalized) == normalized:
        return True

    windows_normalized = ntpath.normpath(candidate)
    windows_drive, windows_tail = ntpath.splitdrive(windows_normalized)
    if windows_drive and windows_tail in {"\\", "/"}:
        return True
    if windows_drive and ntpath.dirname(windows_normalized) == windows_normalized:
        return True
    return False


def _safe_is_directory(path_value):
    """Return whether a path value is an existing directory without raising.

    Inputs: `path_value`. Output: bool.
    """
    try:
        return bool(path_value) and os.path.isdir(path_value)
    except (OSError, TypeError, ValueError):
        return False


def _is_structurally_valid_folder_path(path_value):
    """Return whether a typed folder path is structurally usable.

    Inputs: `path_value`. Output: bool.
    """
    candidate = _coerce_path(path_value)
    if candidate is None:
        return False
    try:
        path_text = os.fspath(candidate)
    except (TypeError, ValueError):
        return False
    if not path_text or path_text != path_text.strip():
        return False

    normalized_windows_path = _normalize_extended_windows_path_for_validation(path_text)
    if normalized_windows_path is None:
        return False
    if _looks_like_windows_path(normalized_windows_path):
        return _is_structurally_valid_windows_folder_path(normalized_windows_path)

    if not os.path.isabs(path_text):
        return False
    return all(part not in {".", ".."} for part in candidate.parts)


def _normalize_extended_windows_path_for_validation(path_text):
    """Return a normal Windows path for validation, or None for device paths.

    Inputs: `path_text`. Output: path string or None.
    """
    upper_text = path_text.upper()
    unc_prefix = "\\\\?\\UNC\\"
    if upper_text.startswith(unc_prefix):
        return "\\\\" + path_text[len(unc_prefix) :]
    extended_prefix = "\\\\?\\"
    if upper_text.startswith(extended_prefix):
        without_prefix = path_text[len(extended_prefix) :]
        if re.match(r"^[A-Za-z]:[\\/]", without_prefix):
            return without_prefix
        return None
    if upper_text.startswith("\\\\.\\"):
        return None
    return path_text


def _looks_like_windows_path(path_text):
    """Return whether path text uses Windows path syntax.

    Inputs: `path_text`. Output: bool.
    """
    drive, _tail = ntpath.splitdrive(path_text)
    return os.name == "nt" or bool(drive) or "\\" in path_text


def _is_valid_windows_path_component(component):
    """Return whether one Windows path component is safe and well formed.

    Inputs: `component`. Output: bool.
    """
    if not component or component in {".", ".."}:
        return False
    if component != component.rstrip(" ."):
        return False
    if any(
        ord(character) < 32 or character in _WINDOWS_PATH_COMPONENT_INVALID_CHARS
        for character in component
    ):
        return False
    base_name = component.split(".", 1)[0].upper()
    return base_name not in _WINDOWS_RESERVED_FILENAMES


def _is_structurally_valid_windows_folder_path(path_text):
    """Return whether path text is an absolute, structurally valid Windows path.

    Inputs: `path_text`. Output: bool.
    """
    if not ntpath.isabs(path_text):
        return False
    drive, tail = ntpath.splitdrive(path_text)
    if drive.startswith("\\\\"):
        server_share = [part for part in drive.split("\\") if part]
        if len(server_share) != 2 or not all(
            _is_valid_windows_path_component(part) for part in server_share
        ):
            return False
    elif not re.match(r"^[A-Za-z]:$", drive):
        return False

    components = [part for part in re.split(r"[\\/]+", tail) if part]
    return all(_is_valid_windows_path_component(part) for part in components)


def _folder_path_write_error(path_value):
    """Return an error message unless `path_value` names a writable folder.

    Inputs: `path_value`. Output: empty string or user-facing error text.
    """
    if not _is_structurally_valid_folder_path(path_value):
        return LOCAL_PATH_WRITE_ERROR_MESSAGE

    candidate = _coerce_path(path_value)
    if candidate is None:
        return LOCAL_PATH_WRITE_ERROR_MESSAGE

    probe_path = None
    descriptor = None
    try:
        if not candidate.exists() or not candidate.is_dir():
            return LOCAL_PATH_WRITE_ERROR_MESSAGE

        probe_path = candidate / f"{LOCAL_PATH_WRITE_TEST_PREFIX}{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(os.fspath(probe_path), flags, 0o600)
        os.close(descriptor)
        descriptor = None
        os.unlink(probe_path)
        probe_path = None
        return ""
    except (OSError, TypeError, ValueError):
        return LOCAL_PATH_WRITE_ERROR_MESSAGE
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if probe_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(probe_path)


def _connector_user_home():
    """Return the current user's home directory for connector settings.

    Inputs: none. Output: `Path`. Raises: OSError when no absolute home exists.
    """
    candidates = []
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE", "").strip()
        if userprofile:
            candidates.append((userprofile, ntpath.isabs))
        home_drive = os.environ.get("HOMEDRIVE", "").strip()
        home_path = os.environ.get("HOMEPATH", "").strip()
        if home_drive and home_path:
            candidates.append((home_drive + home_path, ntpath.isabs))
    with contextlib.suppress(RuntimeError, OSError):
        candidates.append(
            (os.fspath(_NATIVE_PATH_CLASS.home()), _native_path_is_absolute)
        )
    if sys.platform != "win32":
        native_home = os.environ.get("HOME", "").strip()
        if native_home:
            candidates.append((native_home, _native_path_is_absolute))

    for candidate, is_absolute_path in candidates:
        home_text = str(candidate or "").strip()
        if not home_text:
            continue
        if is_absolute_path(home_text):
            return _NATIVE_PATH_CLASS(home_text)
    raise OSError("Unable to detect an absolute user home directory")


def _omero_multi_handoff_notice(download_dir, remaining_count, *, completed=False):
    """Return the OMERO multi-selection handoff notice for Imaris 11.

    Inputs: `download_dir`, `remaining_count`, optional `completed`. Output:
    user-facing notice text.
    """
    folder_text = os.fspath(download_dir)
    first_verb = "was" if completed else "will be"
    remaining_verb = "was" if remaining_count == 1 else "were"
    if not completed:
        remaining_verb = "will be"
    remaining_label = (
        "the other selected IMS export"
        if remaining_count == 1
        else f"the other {remaining_count} selected IMS exports"
    )
    return (
        f"Only the first selected image {first_verb} opened in the current "
        f"Imaris 11 session.\n\n"
        f"{remaining_label} {remaining_verb} saved in the selected folder:\n"
        f"{folder_text}\n\n"
        "Open the saved IMS files from that folder when you need them, or use "
        "them as inputs for an Imaris 11 Workflow/Batch processing pipeline."
    )


def _connector_settings_env_path(home_path=None):
    """Return the connector-owned user settings env path.

    Inputs: optional `home_path`. Output: `Path`.
    """
    home = _coerce_path(home_path) if home_path is not None else _connector_user_home()
    if home is None:
        raise OSError("Connector settings home path is invalid")
    return home / AUTOSAVE_SETTINGS_DIR_NAME / AUTOSAVE_SETTINGS_FILE_NAME


def _current_connector_settings_version():
    """Return the version string persisted in connector settings.

    Inputs: none. Output: `str`.
    """
    version_text = str(CONNECTOR_INFO_VERSION or "").strip()
    match = re.search(r"\b\d+(?:\.\d+)*\b", version_text)
    return match.group(0) if match else version_text


def _default_connector_settings_for_current_version():
    """Return new-user connector settings for the current version.

    Inputs: none. Output: dict.
    """
    return {
        CONNECTOR_SETTINGS_VERSION_KEY: _current_connector_settings_version(),
        CONNECTOR_SETTINGS_AUTOSAVE_KEY: "true",
        CONNECTOR_SETTINGS_SHOW_LOG_KEY: "true",
        CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY: "false",
        CONNECTOR_SETTINGS_COLLABORATION_PROJECTS_KEY: "false",
        CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY: "false",
    }


def _connector_settings_with_current_version(settings):
    """Return normalized settings with the current connector version.

    Inputs: `settings`. Output: dict.
    """
    normalized = {key: str(settings.get(key, "")) for key in CONNECTOR_SETTINGS_KEYS}
    normalized[CONNECTOR_SETTINGS_VERSION_KEY] = _current_connector_settings_version()
    return normalized


def _path_kind_without_follow(path):
    """Classify a path without following symlinks.

    Inputs: `path`. Output: path kind string.
    """
    try:
        candidate = _coerce_path(path)
        if candidate is None:
            return "error"
        mode = candidate.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    except (OSError, TypeError, ValueError):
        return "error"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "dir"
    return "other"


def _connector_settings_target_safety_error(target, allow_missing_file=True):
    """Return an error when a settings target is outside the connector contract.

    Inputs: `target`, `allow_missing_file`. Output: `str` or empty.
    """
    try:
        target = _coerce_path(target)
    except TypeError:
        return "Connector settings path is invalid"
    if target is None:
        return "Connector settings path is invalid"
    if not target.is_absolute():
        return "Connector settings path is not absolute"
    if target.name != AUTOSAVE_SETTINGS_FILE_NAME:
        return "Connector settings path has an unexpected file name"
    if target.parent.name != AUTOSAVE_SETTINGS_DIR_NAME:
        return "Connector settings path has an unexpected directory name"

    parent_kind = _path_kind_without_follow(target.parent)
    if parent_kind not in {"missing", "dir"}:
        return "Connector settings directory is not a regular directory"

    target_kind = _path_kind_without_follow(target)
    if target_kind == "missing" and allow_missing_file:
        return ""
    if target_kind != "file":
        return "Connector settings path is not a regular file"
    return ""


def _connector_settings_backup_path(target, backup_index):
    """Return the generated backup path for a connector settings file.

    Inputs: `target`, `backup_index`. Output: `Path`.
    """
    index = int(backup_index)
    if index < 1:
        raise ValueError("Connector settings backup index must be positive")
    suffix = ".old" if index == 1 else f".old{index}"
    target = _coerce_path(target)
    if target is None:
        raise ValueError("Connector settings backup target is invalid")
    return target.with_name(target.name + suffix)


def _existing_connector_settings_backup_indexes(target):
    """Return contiguous existing safe connector settings backup indexes.

    Inputs: `target`. Output: list of positive integers. Raises: OSError.
    """
    indexes = []  # type: List[int]
    index = 1
    while True:
        backup_path = _connector_settings_backup_path(target, index)
        backup_kind = _path_kind_without_follow(backup_path)
        if backup_kind == "missing":
            return indexes
        if backup_kind != "file":
            raise OSError("Connector settings backup path is not a regular file")
        indexes.append(index)
        index += 1


def _rotate_connector_settings_backups(target):
    """Rotate generated connector settings backups upward without overwriting.

    Inputs: `target`. Output: None. Raises: OSError.
    """
    safety_error = _connector_settings_target_safety_error(
        target, allow_missing_file=False
    )
    if safety_error:
        raise OSError(safety_error)

    for index in reversed(_existing_connector_settings_backup_indexes(target)):
        source_path = _connector_settings_backup_path(target, index)
        destination_path = _connector_settings_backup_path(target, index + 1)
        if _path_kind_without_follow(destination_path) != "missing":
            raise OSError("Connector settings backup destination already exists")
        source_path.rename(destination_path)

    first_backup_path = _connector_settings_backup_path(target, 1)
    if _path_kind_without_follow(first_backup_path) != "missing":
        raise OSError("Connector settings backup destination already exists")
    target_path = _coerce_path(target)
    if target_path is None:
        raise OSError("Connector settings path is invalid")
    target_path.rename(first_backup_path)


def _prepare_connector_settings_for_current_version(settings_path=None):
    """Create or migrate connector settings for the current app version.

    Inputs: optional `settings_path`. Output: bool.
    """
    try:
        target = (
            _coerce_path(settings_path)
            if settings_path is not None
            else _connector_settings_env_path()
        )
        if target is None:
            raise OSError("Connector settings path is invalid")
        safety_error = _connector_settings_target_safety_error(target)
        if safety_error:
            raise OSError(safety_error)
        current_version = _current_connector_settings_version()
        if _path_kind_without_follow(target) == "missing":
            _atomic_write_connector_settings(
                _default_connector_settings_for_current_version(), target
            )
            return True

        settings = _load_connector_settings(target)
        if settings.get(CONNECTOR_SETTINGS_VERSION_KEY) != current_version:
            _rotate_connector_settings_backups(target)
            _atomic_write_connector_settings(
                _default_connector_settings_for_current_version(), target
            )
            _log_connector_settings_event(
                "Connector settings version changed; previous settings archived"
            )
            return True

        settings.setdefault(CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY, "false")
        _atomic_write_connector_settings(settings, target)
        return True
    except (OSError, TypeError, ValueError) as exc:
        _log_connector_settings_event(
            f"Connector settings version preparation failed: {type(exc).__name__}"
        )
        return False


def _log_connector_settings_event(message):
    """Write a settings diagnostic without letting logging affect the UI.

    Inputs: `message`. Output: None.
    """
    with contextlib.suppress(Exception):
        _xt_debug(message)


def _format_connector_settings_env_value(value):
    """Return a quoted env value without shell interpolation.

    Inputs: `value`. Output: `str`.
    """
    return json.dumps("" if value is None else str(value), ensure_ascii=True)


def _parse_connector_settings_env_value(raw_value):
    """Parse one connector settings env value without evaluating shell syntax.

    Inputs: `raw_value`. Output: `str`.
    """
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("Malformed quoted connector settings value") from exc
        return str(value) if value is not None else ""
    return text


def _split_connector_settings_env_line(line):
    """Split one connector settings line into key and raw value.

    Inputs: `line`. Output: `(key, raw_value)` or `(None, None)`.
    """
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", str(line or ""))
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _parse_connector_settings_env_line(line):
    """Parse one connector settings line.

    Inputs: `line`. Output: `(key, value)` or `(None, None)`.
    """
    key, raw_value = _split_connector_settings_env_line(line)
    if key is None:
        return None, None
    return key, _parse_connector_settings_env_value(raw_value)


def _is_sensitive_connector_settings_key(key):
    """Return whether an env key must not be preserved in connector settings.

    Inputs: `key`. Output: bool.
    """
    key_parts = set(re.split(r"[^A-Z0-9]+", str(key or "").upper()))
    return bool(key_parts & {"PASSWORD", "PASS", "SECRET", "TOKEN"}) or {
        "API",
        "KEY",
    }.issubset(key_parts)


def _load_connector_settings(settings_path=None):
    """Load connector-owned settings from the user env file.

    Inputs: optional `settings_path`. Output: dict with allowlisted keys only.
    """
    path = (
        _coerce_path(settings_path)
        if settings_path is not None
        else _connector_settings_env_path()
    )
    if path is None:
        return {}
    try:
        safety_error = _connector_settings_target_safety_error(path)
        if safety_error:
            _log_connector_settings_event(
                "Connector settings load skipped: " + safety_error
            )
            return {}
        if not path.is_file():
            return {}
        settings = {}
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                key, raw_value = _split_connector_settings_env_line(line)
                if key not in CONNECTOR_SETTINGS_KEYS:
                    continue
                try:
                    value = _parse_connector_settings_env_value(raw_value)
                except ValueError:
                    _log_connector_settings_event(
                        "Connector settings parse failed: "
                        f"{key} on line {line_number} ignored"
                    )
                    continue
                if str(value or "").strip():
                    settings[key] = value
        return settings
    except (OSError, TypeError, ValueError) as exc:
        _log_connector_settings_event(
            f"Connector settings load failed: {type(exc).__name__}"
        )
        return {}


def _connector_settings_bool(value, default=False):
    """Return a bool from connector settings text.

    Inputs: `value`, `default`. Output: bool.
    """
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _connector_settings_bool_text(value):
    """Return normalized bool text for connector settings.

    Inputs: `value`. Output: `str`.
    """
    return "true" if bool(value) else "false"


def _load_connector_show_log_preference(settings_path=None):
    """Read only the startup console-log preference without emitting diagnostics.

    Inputs: optional `settings_path`. Output: bool.
    """
    try:
        path = (
            _coerce_path(settings_path)
            if settings_path is not None
            else _connector_settings_env_path()
        )
        if path is None:
            return True
        if _connector_settings_target_safety_error(path) or not path.is_file():
            return True
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                key, raw_value = _split_connector_settings_env_line(line)
                if key != CONNECTOR_SETTINGS_SHOW_LOG_KEY:
                    continue
                try:
                    value = _parse_connector_settings_env_value(raw_value)
                except ValueError:
                    return True
                return _connector_settings_bool(value, True)
    except (OSError, TypeError, ValueError):
        return True
    return True


def _filled_connector_setting(settings, key):
    """Return a non-empty connector setting value.

    Inputs: `settings`, `key`. Output: `str`.
    """
    value = settings.get(key, "")
    text = str(value or "")
    return text if text.strip() else ""


def _is_existing_supported_imaris_executable_path(path_value):
    """Return whether `path_value` is an existing supported Imaris.exe path.

    Inputs: `path_value`. Output: bool.
    """
    candidate = _existing_regular_file_path(path_value)
    if candidate is None:
        return False
    if candidate.name.lower() != "imaris.exe":
        return False
    return _is_supported_imaris_install_path(candidate)


def _connector_settings_imaris_executable_candidate(settings_path=None):
    """Return the saved Imaris.exe path from connector settings when valid.

    Inputs: optional `settings_path`. Output: path text or None.
    """
    settings = _load_connector_settings(settings_path)
    candidate = _filled_connector_setting(settings, CONNECTOR_SETTINGS_IMARIS_EXE_KEY)
    if _is_existing_supported_imaris_executable_path(candidate):
        return str(_coerce_path(candidate))
    return None


def _ensure_connector_settings_imaris_executable(settings_path=None):
    """Persist the discovered Imaris.exe path in connector settings when missing.

    Inputs: optional `settings_path`. Output: path text or empty string.
    """
    path = (
        _coerce_path(settings_path)
        if settings_path is not None
        else _connector_settings_env_path()
    )
    if path is None:
        return ""
    cached = _connector_settings_imaris_executable_candidate(path)
    if cached:
        return cached

    discovered = _find_imaris_executable(settings_path=path)
    if not discovered:
        return ""

    settings = _load_connector_settings(path)
    settings[CONNECTOR_SETTINGS_IMARIS_EXE_KEY] = discovered
    _atomic_write_connector_settings(settings, path)
    return discovered


def _connector_settings_output_lines(existing_lines, settings):
    """Return rewritten connector settings lines with known keys normalized.

    Inputs: `existing_lines`, `settings`. Output: list of lines.
    """
    rendered = {
        key: f"{key}={_format_connector_settings_env_value(settings.get(key, ''))}"
        for key in CONNECTOR_SETTINGS_KEYS
    }
    seen = set()
    output = []
    for line in existing_lines:
        key, _raw_value = _split_connector_settings_env_line(line)
        if key in CONNECTOR_SETTINGS_DEPRECATED_KEYS:
            continue
        if key in CONNECTOR_SETTINGS_KEYS:
            if key not in seen:
                output.append(rendered[key])
                seen.add(key)
            continue
        if key is not None and _is_sensitive_connector_settings_key(key):
            continue
        output.append(str(line))
    for key in CONNECTOR_SETTINGS_KEYS:
        if key not in seen:
            output.append(rendered[key])
    return output


def _close_file_descriptor_suppressing_os_error(descriptor):
    """Close an OS file descriptor while suppressing cleanup errors.

    Inputs: `descriptor` optional int file descriptor. Output: None.
    """
    if descriptor is None:
        return
    with contextlib.suppress(OSError):
        os.close(descriptor)


def _atomic_write_connector_settings(settings, settings_path=None):
    """Atomically write connector settings without storing credentials.

    Inputs: `settings`, optional `settings_path`. Output: None. Raises: OSError.
    """
    descriptor: Optional[int] = None
    temp_path: Optional[Path] = None
    try:
        target = (
            _coerce_path(settings_path)
            if settings_path is not None
            else _connector_settings_env_path()
        )
        if target is None:
            raise OSError("Connector settings path is invalid")
        target_dir = target.parent
        safety_error = _connector_settings_target_safety_error(target)
        if safety_error:
            raise OSError(safety_error)
        target_dir.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(os.fspath(target_dir), PRIVATE_DIRECTORY_MODE)

        existing_lines = []  # type: List[str]
        if target.exists():
            existing_lines = target.read_text(encoding="utf-8").splitlines()

        normalized = _connector_settings_with_current_version(settings)
        content = (
            "\n".join(_connector_settings_output_lines(existing_lines, normalized))
            + "\n"
        )
        temp_path_for_write = target_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
        temp_path = temp_path_for_write
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(os.fspath(temp_path_for_write), flags, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(os.fspath(temp_path_for_write), os.fspath(target))
        with contextlib.suppress(OSError):
            os.chmod(os.fspath(target), PRIVATE_FILE_MODE)
    except (OSError, TypeError, ValueError) as exc:
        _log_connector_settings_event(
            f"Connector settings write failed: {type(exc).__name__}"
        )
        raise
    finally:
        _close_file_descriptor_suppressing_os_error(descriptor)
        with contextlib.suppress(OSError):
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def _stringvar_value(variable):
    """Return the stringvar value.

    Inputs: `variable`. Output: `str`.
    """
    if variable is None:
        return ""
    getter = getattr(variable, "get", None)
    if callable(getter):
        value = getter()
    else:
        value = getattr(variable, "value", "")
    return str(value or "")


def _pluralize(count, singular, plural=None):
    """Return singular or plural text for a numeric count.

    Inputs: `count`, `singular`, `plural`. Output: pluralize result.
    """
    try:
        numeric_count = int(count)
    except (TypeError, ValueError):
        numeric_count = 0
    if numeric_count == 1:
        return singular
    return plural if plural is not None else f"{singular}s"


def _multipart_form_body(fields, file_field_name, file_name, file_bytes):
    """Return the multipart form body.

    Inputs: `fields`, `file_field_name`, `file_name`, `file_bytes`. Output: `tuple`.
    """
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    boundary = f"----OMEROConnector{timestamp}{os.getpid()}{int(time.time() * 1000000)}"
    body = bytearray()

    def append_text(value):
        """Append the text.

        Inputs: `value` input value. Output: None.
        """
        if isinstance(value, bytes):
            body.extend(value)
        else:
            body.extend(str(value).encode("utf-8"))

    for key, value in list(fields.items()):
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            (f'Content-Disposition: form-data; name="{key}"\r\n\r\n').encode("utf-8")
        )
        append_text(value)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("ascii"))
    safe_name = _safe_download_filename(file_name, "upload.bin") or "upload.bin"
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; '
            f'filename="{safe_name}"\r\n'
            "Content-Type: application/octet-stream\r\n"
            "\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("ascii"))
    return boundary, bytes(body)


def _is_windows_reparse_point(stat_result):
    """Return whether windows reparse point.

    Inputs: `stat_result`. Output: `bool` result.
    """
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _collect_local_folder_entries(folder_path):
    """Collect the local folder entries.

    Inputs: `folder_path` folder path. Output: collect local folder entries result.
    Raises: RuntimeError when validation or the called operation fails.
    """
    root = _coerce_path(folder_path)
    if root is None:
        raise RuntimeError("The selected folder path is invalid.")
    root_path = root
    if not root_path.exists():
        raise RuntimeError("The selected folder no longer exists.")
    if not root_path.is_dir():
        raise RuntimeError("The selected path is not a folder.")

    entries = []
    pending = [root_path]

    while pending:
        current_dir = pending.pop()
        try:
            with os.scandir(str(current_dir)) as iterator:
                dir_entries = sorted(
                    list(iterator),
                    key=lambda item: item.name.lower(),
                )
        except OSError as exc:
            raise RuntimeError(
                f"Failed to read the selected folder: {type(exc).__name__}"
            ) from exc

        child_dirs = []
        for item in dir_entries:
            try:
                item_stat = item.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(
                    f"Failed to inspect a selected file or folder: {type(exc).__name__}"
                ) from exc

            item_path = _coerce_path(item.path)
            if item_path is None:
                raise RuntimeError("A selected file or folder path is invalid.")
            relative_path = item_path.relative_to(root_path).as_posix()
            if item.is_symlink() or _is_windows_reparse_point(item_stat):
                raise RuntimeError(
                    "Selected folders must not contain symbolic links or reparse-point entries. "
                    f"Blocked entry: {relative_path}"
                )

            if item.is_dir(follow_symlinks=False):
                child_dirs.append(item_path)
                continue
            if not item.is_file(follow_symlinks=False):
                raise RuntimeError(
                    "Selected folders must contain only regular files and directories. "
                    f"Blocked entry: {relative_path}"
                )

            entries.append(
                {
                    "absolute_path": str(item_path),
                    "relative_path": relative_path,
                    "size": int(getattr(item_stat, "st_size", 0) or 0),
                }
            )

        pending.extend(reversed(child_dirs))

    if not entries:
        raise RuntimeError("The selected folder does not contain any files.")
    return entries


def _configure_xt_console_visibility(show_log_enabled):
    """Apply the connector command-window visibility preference.

    Inputs: `show_log_enabled`. Output: bool indicating whether a Windows console
    was found and updated.
    """
    enabled = bool(show_log_enabled)
    _XT_RUNTIME_STATE.console_output_enabled = enabled
    if os.name != "nt":
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll")
        kernel32 = windll.kernel32
        user32 = windll.user32
        console_window = kernel32.GetConsoleWindow()
        if not console_window:
            return False
        show_command = 5 if enabled else 0
        user32.ShowWindow(console_window, show_command)
        return True
    except Exception as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )
        return False


def _xt_debug(message):
    """Write an XT connector debug message when debug logging is enabled.

    Inputs: `message`. Output: None.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {_sanitize_xt_log_message(message)}"
    _xt_console_log(line)


def _xt_console_log(message="", *, end="\n", flush=False):
    """Write a visible console message and mirror it to the XT rolling log.

    Inputs: `message`, optional `end`, optional `flush`. Output: None.
    """
    text = str(message)
    if _XT_RUNTIME_STATE.console_output_enabled:
        try:
            print(text, end=end, flush=flush)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
            )
    try:
        if not _XT_RUNTIME_STATE.log_path:
            _XT_RUNTIME_STATE.log_path = _xt_log_path()
        if _XT_RUNTIME_STATE.log_path:
            _xt_write_log(_XT_RUNTIME_STATE.log_path, text)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )


def _iter_console_interrupt_signals():
    """Yield console interrupt signals that should not abort Imaris-hosted XT.

    Inputs: none. Output: yielded signal numbers.
    """
    seen = set()
    for name in ("SIGINT", "SIGBREAK"):
        value = getattr(signal, name, None)
        if value is not None and value not in seen:
            seen.add(value)
            yield value


def _ignore_xt_console_interrupt(signum, _frame):
    """Ignore accidental Ctrl+C/Ctrl+Break in the connector log console.

    Inputs: signal number and frame. Output: None.
    """
    _xt_debug(f"Ignored connector command-window interrupt signal {signum}.")


def _install_xt_console_interrupt_guard():
    """Install a scoped guard that prevents console Ctrl+C from aborting XT.

    Inputs: none. Output: previous handler records.
    """
    previous_handlers = []
    for interrupt_signal in _iter_console_interrupt_signals():
        try:
            previous = signal.getsignal(interrupt_signal)
            signal.signal(interrupt_signal, _ignore_xt_console_interrupt)
            previous_handlers.append((interrupt_signal, previous))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
    return previous_handlers


def _restore_xt_console_interrupt_guard(previous_handlers):
    """Restore signal handlers replaced by the XT console interrupt guard.

    Inputs: previous handler records. Output: None.
    """
    for interrupt_signal, previous in reversed(list(previous_handlers or [])):
        try:
            signal.signal(interrupt_signal, previous)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )


def _parse_port(port_value):
    """Validate a port-like value and return it as an integer.

    Inputs: `port_value`. Output: `port`.
    """
    if port_value is None:
        return None
    port_text = str(port_value).strip()
    if not port_text:
        return None
    if not port_text.isdigit():
        return None
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        return None
    if port <= 0 or port > 65535:
        return None
    return port


def _valid_port_entry_text(value):
    """Return whether text is valid while typing the port entry.

    Inputs: proposed entry text. Output: bool.
    """
    text = str(value or "")
    if not text:
        return True
    if not text.isdigit() or len(text) > 5:
        return False
    try:
        return int(text) <= 65535
    except (TypeError, ValueError):
        return False


def _host_text_has_url_scheme(host_text):
    """Return whether host text starts with a URL scheme.

    Inputs: `host_text`. Output: bool.
    """
    return bool(re.match(r"(?i)^[a-z][a-z0-9+.-]*://", host_text))


def _host_text_has_invalid_separator(host_text):
    """Return whether host text contains URL-only separators.

    Inputs: `host_text`. Output: bool.
    """
    return any(char in host_text for char in "/?#@")


def _bracketed_omero_web_host_error(host_text):
    """Return the validation error for a bracketed host.

    Inputs: `host_text`. Output: error text or an empty string.
    """
    try:
        parsed = urllib.parse.urlsplit(f"//{host_text}")
        parsed_port = parsed.port
    except ValueError:
        return HOST_FIELD_INVALID_ERROR_MESSAGE
    if parsed_port is not None:
        return HOST_FIELD_PORT_ERROR_MESSAGE
    return "" if parsed.hostname else HOST_FIELD_INVALID_ERROR_MESSAGE


def _colon_omero_web_host_error(host_text):
    """Return the validation error for host text containing colons.

    Inputs: `host_text`. Output: error text or an empty string.
    """
    try:
        ip_address = ipaddress.ip_address(host_text)
    except ValueError:
        return HOST_FIELD_PORT_ERROR_MESSAGE
    return "" if ip_address.version == 6 else HOST_FIELD_INVALID_ERROR_MESSAGE


def _omero_web_host_input_error(host_value):
    """Return the validation error for the OMERO.web host field.

    Inputs: `host_value`. Output: error text or an empty string.
    """
    host_text = str(host_value or "").strip()
    if not host_text:
        return ""
    if _host_text_has_url_scheme(host_text) or host_text.startswith("//"):
        return HOST_FIELD_SCHEME_ERROR_MESSAGE
    if any(ord(char) < 33 for char in host_text):
        return HOST_FIELD_INVALID_ERROR_MESSAGE
    if _host_text_has_invalid_separator(host_text):
        return HOST_FIELD_INVALID_ERROR_MESSAGE
    if host_text.startswith("["):
        return _bracketed_omero_web_host_error(host_text)
    if ":" in host_text:
        return _colon_omero_web_host_error(host_text)
    return ""


def _normalized_omero_web_host_for_url(host_value):
    """Return host text normalized for use in a URL authority.

    Inputs: `host_value`. Output: host text. Raises: ValueError for invalid host input.
    """
    host_text = str(host_value or "").strip()
    error = _omero_web_host_input_error(host_text)
    if error:
        raise ValueError(error)
    if host_text.startswith("["):
        return host_text
    try:
        ip_address = ipaddress.ip_address(host_text)
    except ValueError:
        return host_text
    if ip_address.version == 6:
        return f"[{host_text}]"
    return host_text


def is_ims_file(file_path):
    """Report whether a filesystem path points to an Imaris IMS file.

    Inputs: `file_path`. Output: bool.
    """
    hdf5_signature = b"\x89HDF\r\n\x1a\n"
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        return False
    try:
        with candidate.open("rb") as f:
            header = f.read(len(hdf5_signature))
        return header == hdf5_signature
    except Exception:
        return False


def is_tiff_file(file_path):
    """Report whether a filesystem path points to a TIFF or BigTIFF file.

    Inputs: `file_path`. Output: bool.
    """
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        return False
    try:
        with candidate.open("rb") as f:
            header = f.read(4)
        return header in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}
    except Exception:
        return False


def _current_imaris_file_getter(imaris_app):
    """Return current imaris file getter.

    Inputs: `imaris_app`. Output: `method` or None.
    """
    for method_name in ("GetCurrentFileName", "GetCurrentFilePath"):
        method = getattr(imaris_app, method_name, None)
        if callable(method):
            return method
    return None


def _normalize_imaris_compare_path(path_value):
    """Normalize an Imaris file path for case-insensitive comparison.

    Inputs: `path_value`. Output: `normcase` result.
    """
    path_text = _coerce_path(path_value)
    if path_text is None:
        return ""
    try:
        path_text = os.path.abspath(path_text)
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(path_text))
    return os.path.normcase(os.path.normpath(path_text))


def _file_open_call_candidates(file_path, verification_mode="current_file"):
    """Return the file open call candidates.

    Inputs: `file_path` file path, `verification_mode`. Output: `tuple`.
    """
    if verification_mode == "current_file":
        return (
            ("FileOpen", (file_path, "")),
            ("FileOpen", (file_path,)),
            ("OpenFile", (file_path, "")),
            ("OpenFile", (file_path,)),
            ("LoadFile", (file_path, "")),
            ("LoadFile", (file_path,)),
        )
    return (
        ("FileOpen", (file_path,)),
        ("FileOpen", (file_path, "")),
        ("OpenFile", (file_path,)),
        ("OpenFile", (file_path, "")),
        ("LoadFile", (file_path,)),
        ("LoadFile", (file_path, "")),
    )


def _imaris_data_set_signature(data_set):
    """Return the Imaris data set signature.

    Inputs: `data_set`. Output: Imaris data set signature result.
    """
    if data_set is None:
        return None
    values: List[Optional[int]] = []
    for method_name in ("GetSizeX", "GetSizeY", "GetSizeZ", "GetSizeC", "GetSizeT"):
        method = getattr(data_set, method_name, None)
        if not callable(method):
            values.append(None)
            continue
        try:
            values.append(int(method()))
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
            values.append(None)
    return tuple(values) if any(value is not None for value in values) else "present"


def _imaris_data_set_has_content(data_set):
    """Return whether an Imaris data set exposes positive dimensions.

    Inputs: `data_set`. Output: bool.
    """
    if data_set is None:
        return False
    positive_dimension_seen = False
    for method_name in ("GetSizeX", "GetSizeY", "GetSizeZ", "GetSizeC", "GetSizeT"):
        method = getattr(data_set, method_name, None)
        if not callable(method):
            continue
        try:
            value = int(method())
        except Exception:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=True,
            )
            return False
        if value <= 0:
            return False
        positive_dimension_seen = True
    return positive_dimension_seen


def _current_imaris_data_set(imaris_app):
    """Return the currently loaded Imaris data set when available.

    Inputs: `imaris_app`. Output: dataset object or None.
    """
    get_data_set = getattr(imaris_app, "GetDataSet", None)
    if not callable(get_data_set):
        return None
    try:
        return get_data_set()
    except Exception:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py",
            exc_info=True,
        )
        return None


def _ensure_imaris_current_dataset_visible(imaris_app, data_set=None):
    """Commit the loaded dataset back through Imaris visibility APIs.

    Inputs: `imaris_app`, optional `data_set`. Output: bool indicating whether a
    visibility API accepted the dataset.
    """
    if data_set is None:
        data_set = _current_imaris_data_set(imaris_app)
    if not _imaris_data_set_has_content(data_set):
        return False
    set_data_set = getattr(imaris_app, "SetDataSet", None)
    if callable(set_data_set):
        try:
            if set_data_set(data_set) is not False:
                return True
        except Exception:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=True,
            )
    set_image = getattr(imaris_app, "SetImage", None)
    if callable(set_image):
        try:
            if set_image(0, data_set) is not False:
                return True
        except Exception:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=True,
            )
    return False


def _imaris_app_snapshot(imaris_app):
    """Return the Imaris app snapshot.

    Inputs: `imaris_app`. Output: `tuple`.
    """
    current = ""
    getter = _current_imaris_file_getter(imaris_app)
    if getter is not None:
        try:
            current = _normalize_imaris_compare_path(getter())
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
            current = ""

    image_count = None
    get_count = getattr(imaris_app, "GetNumberOfImages", None)
    if callable(get_count):
        try:
            image_count = int(get_count())
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
            image_count = None

    data_set_signature = None
    get_data_set = getattr(imaris_app, "GetDataSet", None)
    if callable(get_data_set):
        try:
            data_set_signature = _imaris_data_set_signature(get_data_set())
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
            data_set_signature = None

    return current, image_count, data_set_signature


def _imaris_open_snapshot_changed(before, current_snapshot, expected_path):
    """Return whether an Imaris snapshot proves an open-file effect.

    Inputs: `before`, `current_snapshot`, `expected_path`. Output: bool.
    """
    current, image_count, data_set_signature = current_snapshot
    before_current, before_image_count, before_data_set_signature = before
    if expected_path and current and current == expected_path:
        return True
    if current and current != before_current:
        return True
    image_count_changed = (
        image_count is not None
        and before_image_count is not None
        and image_count != before_image_count
    )
    data_set_changed = data_set_signature is not None and (
        before_data_set_signature is None
        or data_set_signature != before_data_set_signature
    )
    return image_count_changed or data_set_changed


def _wait_for_imaris_verified_open(
    imaris_app,
    current_file_getter,
    before,
    expected_path,
    before_data_set=None,
    timeout=None,
    interval=None,
):
    """Poll until opening a file is verified in the current Imaris session.

    Inputs: `imaris_app`, optional `current_file_getter`, `before`,
    `expected_path`, optional previous dataset and timing values. Output: bool.
    """
    if timeout is None:
        timeout = IMARIS_OPEN_VERIFY_TIMEOUT
    if interval is None:
        interval = IMARIS_OPEN_VERIFY_INTERVAL
    expected = _normalize_imaris_compare_path(expected_path)
    deadline = time.time() + max(0.0, float(timeout))
    while time.time() <= deadline:
        if current_file_getter is not None:
            try:
                current = _normalize_imaris_compare_path(current_file_getter())
            except Exception as exc:
                _xt_debug(f"Imaris current-file verification failed: {exc}")
                current = ""
            if expected and current and current == expected:
                _ensure_imaris_current_dataset_visible(imaris_app)
                return True
        snapshot_changed = _imaris_open_snapshot_changed(
            before,
            _imaris_app_snapshot(imaris_app),
            expected,
        )
        data_set = _current_imaris_data_set(imaris_app)
        data_set_changed = data_set is not None and data_set is not before_data_set
        if (
            (snapshot_changed or data_set_changed)
            and _imaris_data_set_has_content(data_set)
            and _ensure_imaris_current_dataset_visible(imaris_app, data_set)
        ):
            return True
        time.sleep(max(0.0, float(interval)))
    return False


def _wait_for_imaris_open_observable_effect(
    imaris_app,
    before,
    expected_path,
    timeout=None,
    interval=None,
):
    """Poll Imaris until opening a file changes the visible application state.

    Inputs: `imaris_app`, `before`, `expected_path`, `timeout`, `interval`. Output:
    bool.

    bool.
    """
    if timeout is None:
        timeout = IMARIS_OPEN_VERIFY_TIMEOUT
    if interval is None:
        interval = IMARIS_OPEN_VERIFY_INTERVAL
    expected = _normalize_imaris_compare_path(expected_path)
    deadline = time.time() + max(0.0, float(timeout))
    while time.time() <= deadline:
        if _imaris_open_snapshot_changed(
            before,
            _imaris_app_snapshot(imaris_app),
            expected,
        ):
            return True
        time.sleep(max(0.0, float(interval)))
    return False


def _open_file_in_imaris_with_mode(file_path, imaris_app, verification_mode):
    """Open one local file in Imaris using the requested verification mode.

    Inputs: `file_path`, `imaris_app`, `verification_mode`. Output: bool.
    """
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        _xt_debug("Imaris open skipped: file does not exist")
        return False
    if verification_mode == "current_file" and not is_ims_file(candidate):
        _xt_debug("Imaris open skipped: file is not a valid IMS file")
        return False

    if imaris_app is None:
        _xt_debug("Direct Imaris application handle is not available in this Python")
        return False

    last_error: Any = None
    file_path_text = str(candidate)
    current_file_getter = _current_imaris_file_getter(imaris_app)
    for method_name, args in _file_open_call_candidates(
        file_path_text,
        verification_mode=verification_mode,
    ):
        method = getattr(imaris_app, method_name, None)
        if not callable(method):
            continue
        try:
            before = _imaris_app_snapshot(imaris_app)
            before_data_set = _current_imaris_data_set(imaris_app)
            result = method(*args)
            if result is False:
                last_error = f"{method_name} returned False"
                continue
            if verification_mode == "submission_only":
                return True
            if verification_mode == "observable_effect":
                if _wait_for_imaris_open_observable_effect(
                    imaris_app,
                    before,
                    file_path_text,
                ):
                    _ensure_imaris_current_dataset_visible(imaris_app)
                    return True
                last_error = (
                    f"{method_name} returned without an observable Imaris state change"
                )
                continue
            if _wait_for_imaris_verified_open(
                imaris_app,
                current_file_getter,
                before,
                file_path_text,
                before_data_set,
            ):
                return True
            last_error = (
                f"{method_name} returned without making the current Imaris file "
                "match the downloaded file or loading a verified visible dataset"
            )
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        _xt_debug(f"Direct Imaris open failed: {last_error}")
    else:
        _xt_debug("Direct Imaris open failed: no supported API method found")
    return False


def open_file_in_imaris(file_path, imaris_app, require_ims=True):
    """Attempt to open a file in Imaris using the XT file-open API.

    Inputs: `file_path` file path, `imaris_app`, ignored compatibility
    `require_ims`. Output: `_open_file_in_imaris_with_mode` result.
    """
    if not require_ims:
        _xt_debug("Imaris open requested without IMS validation; enforcing IMS only")
    return _open_file_in_imaris_with_mode(file_path, imaris_app, "current_file")


def open_files_in_imaris(file_paths, imaris_app, require_ims=True):
    """Open local IMS files in an existing Imaris application.

    Inputs: `file_paths`, `imaris_app`, ignored compatibility `require_ims`. Output:
    `open_files_as_imaris_image_slots` result.
    """
    if not require_ims:
        _xt_debug(
            "Imaris multi-open requested without IMS validation; enforcing IMS only"
        )
    if isinstance(file_paths, (str, bytes, os.PathLike)):
        file_paths = [file_paths]
    else:
        try:
            file_paths = list(file_paths)
        except TypeError:
            file_paths = []
    if not file_paths:
        _xt_debug("Direct Imaris multi-open skipped: no files were provided")
        return False

    validated_paths = []
    for file_path in file_paths:
        candidate = _existing_regular_file_path(file_path)
        if candidate is None:
            _xt_debug("Direct Imaris multi-open skipped: one input file is missing")
            return False
        if not is_ims_file(candidate):
            _xt_debug(
                "Direct Imaris multi-open skipped: one file is not a valid IMS file"
            )
            return False
        validated_paths.append(str(candidate))

    if len(validated_paths) == 1:
        return open_file_in_imaris(
            validated_paths[0],
            imaris_app,
            require_ims=True,
        )
    return open_files_as_imaris_image_slots(validated_paths, imaris_app)


def _clone_current_imaris_dataset(imaris_app):
    """Clone the current Imaris dataset when the API exposes a clone method.

    Inputs: `imaris_app`. Output: `clone` result or None.
    """
    get_data_set = getattr(imaris_app, "GetDataSet", None)
    if not callable(get_data_set):
        return None
    data_set = get_data_set()
    clone = getattr(data_set, "Clone", None)
    if not callable(clone):
        return None
    return clone()


def _wait_for_imaris_image_count(
    imaris_app,
    expected_count,
    timeout=IMARIS_OPEN_VERIFY_TIMEOUT,
    interval=IMARIS_OPEN_VERIFY_INTERVAL,
):
    """Poll Imaris until the image count reaches the expected value.

    Inputs: `imaris_app`, `expected_count`, `timeout`, `interval`. Output: bool.
    """
    get_count = getattr(imaris_app, "GetNumberOfImages", None)
    if not callable(get_count):
        return True
    deadline = time.time() + max(0.0, float(timeout))
    while time.time() <= deadline:
        try:
            if int(get_count()) >= int(expected_count):
                return True
        except Exception as exc:
            _xt_debug(f"Imaris image-count verification failed: {exc}")
            return False
        time.sleep(max(0.0, float(interval)))
    return False


def open_files_as_imaris_image_slots(file_paths, imaris_app):
    """Open multiple files as image slots in a single Imaris dataset.

    Inputs: `file_paths`, `imaris_app`. Output: `_wait_for_imaris_image_count` result.
    """
    set_image = getattr(imaris_app, "SetImage", None)
    if not callable(set_image):
        _xt_debug("Direct Imaris multi-open failed: SetImage API is unavailable")
        return False

    data_sets = []
    for file_path in file_paths:
        if not _open_file_in_imaris_with_mode(
            file_path,
            imaris_app,
            "observable_effect",
        ):
            return False
        data_set = _clone_current_imaris_dataset(imaris_app)
        if data_set is None:
            _xt_debug("Direct Imaris multi-open failed: dataset clone is unavailable")
            return False
        data_sets.append(data_set)

    for index, data_set in enumerate(data_sets):
        set_image(index, data_set)
    return _wait_for_imaris_image_count(imaris_app, len(data_sets))


def _looks_like_imaris_application(candidate):
    """Return True when the object looks like a live Imaris application handle.

    Inputs: `candidate`. Output: `callable` result.
    """
    if candidate is None:
        return False
    return any(
        callable(getattr(candidate, method_name, None))
        for method_name in ("FileOpen", "OpenFile", "LoadFile")
    )


def _imaris_application_handle_is_live(candidate):
    """Return whether an Imaris handle still responds to cheap read probes.

    Inputs: candidate handle. Output: bool.
    """
    if not _looks_like_imaris_application(candidate):
        return False
    probe_names = (
        "GetCurrentFileName",
        "GetNumberOfImages",
        "GetDataSet",
        "GetFactory",
        "GetVersion",
    )
    for name in probe_names:
        method = getattr(candidate, name, None)
        if not callable(method):
            continue
        try:
            method()
            return True
        except Exception as exc:
            _xt_debug(
                "Cached Imaris handle failed live-session probe "
                f"{name}: {type(exc).__name__}"
            )
            return False
    return True


def _infer_imaris_major_version_from_path(path_value):
    """Infer the Imaris major version from an executable or install path.

    Inputs: `path_value`. Output: `int` result or None.
    """
    path_text = _coerce_path(path_value)
    if path_text is None:
        return None
    for part in reversed(path_text.parts):
        match = re.search(r"(?i)\bimaris\D*(\d+)", part)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
    return None


def _is_supported_imaris_install_path(path_value):
    """Return whether supported imaris install path.

    Inputs: `path_value`. Output: bool.
    """
    major = _infer_imaris_major_version_from_path(path_value)
    return major is not None and major >= 11


def _ensure_tk_loaded():
    """Import Tk modules only after startup platform checks have passed.

    Inputs: no caller arguments. Output: None. Raises: RuntimeError if Tk is unavailable.
    """
    if tk.is_loaded():
        return
    try:
        import tkinter as loaded_tk
        from tkinter import filedialog as loaded_filedialog
        from tkinter import messagebox as loaded_messagebox
    except Exception as exc:
        raise RuntimeError(
            "Tkinter is required to open the OMERO Connector interface."
        ) from exc
    tk.load(loaded_tk)
    filedialog.load(loaded_filedialog)
    messagebox.load(loaded_messagebox)


def _tk_constant(name, fallback):
    """Return the tk constant.

    Inputs: `name` name, `fallback`. Output: `getattr` result.
    """
    return getattr(tk, name, fallback)


def _widget_background(widget):
    """Return the widget background.

    Inputs: `widget`. Output: `cget` result.
    """
    try:
        return widget.cget("bg")
    except Exception:
        return "#f0f0f0"


def _widget_or_ancestor_is_text_input(widget):
    """Return whether a widget or its ancestor is a text-input control.

    Inputs: `widget`. Output: bool.
    """
    current = widget
    while current is not None:
        winfo_class = getattr(current, "winfo_class", None)
        try:
            if callable(winfo_class) and winfo_class() in TEXT_INPUT_WIDGET_CLASSES:
                return True
        except Exception:
            return False
        current = getattr(current, "master", None)
    return False


def _widget_is_or_descendant(widget, ancestor):
    """Return whether `widget` is `ancestor` or one of its descendants.

    Inputs: `widget`, `ancestor`. Output: bool.
    """
    if widget is None or ancestor is None:
        return False
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        current = getattr(current, "master", None)
    return False


def _hex_to_rgb(value, fallback=(128, 128, 128)):
    """Return the hex to rgb.

    Inputs: `value` input value, `fallback`. Output: `fallback`.
    """
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if text.startswith("#") and len(text) == 7:
        try:
            return tuple(int(text[index : index + 2], 16) for index in (1, 3, 5))
        except ValueError:
            return fallback
    return fallback


def _rgb_to_hex(rgb):
    """Return the rgb to hex.

    Inputs: `rgb`. Output: rgb to hex result.
    """
    red = max(0, min(255, int(rgb[0])))
    green = max(0, min(255, int(rgb[1])))
    blue = max(0, min(255, int(rgb[2])))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _resolve_tk_color(widget, value, fallback="#f0f0f0"):
    """Return a Tk color as a PhotoImage-compatible hex value.

    Inputs: `widget`, color `value`, and fallback. Output: hex color.
    """
    text = str(value or "").strip()
    if text.startswith("#") and len(text) == 7:
        return _rgb_to_hex(_hex_to_rgb(text, _hex_to_rgb(fallback)))

    winfo_rgb = getattr(widget, "winfo_rgb", None)
    if callable(winfo_rgb):
        try:
            tk_color_error = tk.TclError
        except (AttributeError, RuntimeError):
            tk_color_error = ValueError
        try:
            red, green, blue = winfo_rgb(text)
            return _rgb_to_hex((red / 257, green / 257, blue / 257))
        except (TypeError, ValueError, RuntimeError, tk_color_error):
            pass
    return _rgb_to_hex(_hex_to_rgb(fallback))


def _blend_colors(first, second, second_weight):
    """Blend the colors.

    Inputs: `first`, `second`, `second_weight`. Output: `_rgb_to_hex` result.
    """
    second_weight = max(0.0, min(1.0, float(second_weight)))
    first_weight = 1.0 - second_weight
    rgb_first = _hex_to_rgb(first)
    rgb_second = _hex_to_rgb(second)
    return _rgb_to_hex(
        (
            rgb_first[0] * first_weight + rgb_second[0] * second_weight,
            rgb_first[1] * first_weight + rgb_second[1] * second_weight,
            rgb_first[2] * first_weight + rgb_second[2] * second_weight,
        )
    )


def _shade_color(value, amount):
    """Shade the color.

    Inputs: `value` input value, `amount`. Output: `_blend_colors` result.
    """
    target = "#ffffff" if amount >= 0 else "#000000"
    return _blend_colors(value, target, abs(amount))


def _circle_coverage(distance, radius):
    """Return antialias coverage for a circle edge.

    Inputs: `distance`, `radius`. Output: float in [0, 1].
    """
    return max(0.0, min(1.0, radius + 0.5 - distance))


def _circle_pixel_color(distance, radius, fill, outline, background):
    """Return one antialiased circle pixel color.

    Inputs: `distance`, `radius`, `fill`, `outline`, `background`. Output: color.
    """
    coverage = _circle_coverage(distance, radius)
    if coverage <= 0:
        return background
    edge_color = outline if distance >= radius - 1.0 else fill
    return _blend_colors(background, edge_color, coverage)


def _antialiased_circle_image(master, width, height, fill, outline):
    """Return a smooth circular button background image.

    Inputs: `master`, dimensions, `fill`, `outline`. Output: Tk PhotoImage.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    background = _resolve_tk_color(master, _widget_background(master))
    fill = _resolve_tk_color(master, fill, fallback=background)
    outline = _resolve_tk_color(master, outline, fallback=fill)
    image = tk.PhotoImage(master=master, width=width, height=height)
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radius = (min(width, height) - 1) / 2.0
    rows = []
    for y_pos in range(height):
        row = []
        for x_pos in range(width):
            distance = math.hypot(x_pos - center_x, y_pos - center_y)
            row.append(_circle_pixel_color(distance, radius, fill, outline, background))
        rows.append("{" + " ".join(row) + "}")
    image.put(" ".join(rows), to=(0, 0, width, height))
    return image


def _omero_logomark_photo_image(master, size=64):
    """Return the embedded OME/OMERO logomark as a Tk PhotoImage.

    Inputs: Tk master and square size. Output: PhotoImage.
    """
    return tk.PhotoImage(
        master=master,
        data=OMERO_LOGOMARK_PNG64_BASE64,
        format="png",
    )


def _apply_omero_window_icon(window, image=None):
    """Apply the OMERO logomark as a Tk window icon when supported.

    Inputs: Tk window and optional cached image. Output: image or None.
    """
    if window is None:
        return image
    try:
        icon = image or _omero_logomark_photo_image(window)
        iconphoto = getattr(window, "iconphoto", None)
        if callable(iconphoto):
            iconphoto(True, icon)
        return icon
    except Exception as exc:
        _xt_debug(f"OMERO window icon setup failed: {type(exc).__name__}")
    return image


def _normalized_tk_state(state):
    """Return the normalized tk state.

    Inputs: `state`. Output: `lower` result.
    """
    return str(state or _tk_constant("NORMAL", "normal")).lower()


def _call_if_available(target, method_name, *args):
    """Call a target method when it exists.

    Inputs: `target`, `method_name`, `*args`. Output: method result or None.
    """
    method = getattr(target, method_name, None)
    if callable(method):
        return method(*args)
    return None


def _safe_widget_dimension(widget, method_name):
    """Return a non-negative integer widget dimension.

    Inputs: `widget`, `method_name`. Output: int.
    """
    try:
        value = _call_if_available(widget, method_name)
    except (TypeError, ValueError):
        return 0
    return max(0, int(value or 0))


def _checkbutton_text_offset(widget):
    """Return the pixel offset from a checkbutton edge to its text.

    Inputs: `widget`. Output: int.
    """
    try:
        text = str(widget.cget("text") or "")
        font_name = widget.cget("font")
        text_width = int(widget.tk.call("font", "measure", font_name, text))
        width = max(
            _safe_widget_dimension(widget, "winfo_width"),
            _safe_widget_dimension(widget, "winfo_reqwidth"),
        )
    except Exception:
        return 0
    return max(0, width - max(0, text_width))


def _current_root_minsize(root):
    """Return the current root minimum size.

    Inputs: `root`. Output: tuple of width and height.
    """
    try:
        values = _call_if_available(root, "minsize") or (0, 0)
        width, height = tuple(values)[:2]
    except (TypeError, ValueError):
        return (0, 0)
    return (max(0, int(width or 0)), max(0, int(height or 0)))


def _normalized_browser_panel_fractions(fractions):
    """Return valid browser-panel fractions that sum to one.

    Inputs: `fractions`. Output: tuple of three floats.
    """
    try:
        values = [float(value) for value in fractions]
    except (TypeError, ValueError):
        values = []
    if len(values) != 3 or any(value <= 0 for value in values):
        return tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)
    total = sum(values)
    if total <= 0:
        return tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)
    normalized = [value / total for value in values]
    minimum = BROWSER_PANEL_MIN_FRACTION
    maximum = BROWSER_PANEL_MAX_FRACTION
    tolerance = 1e-9
    if any(
        value < minimum - tolerance or value > maximum + tolerance
        for value in normalized
    ):
        return tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)
    return tuple(normalized)


def _resize_browser_panel_fractions(fractions, sash_index, sash_fraction):
    """Return panel fractions after dragging one browser splitter.

    Inputs: `fractions`, `sash_index`, `sash_fraction`. Output: tuple of floats.
    """
    current = list(_normalized_browser_panel_fractions(fractions))
    minimum = BROWSER_PANEL_MIN_FRACTION
    maximum = BROWSER_PANEL_MAX_FRACTION
    target = max(0.0, min(1.0, float(sash_fraction)))

    if sash_index == 0:
        pair_total = current[0] + current[1]
        lower = max(minimum, pair_total - maximum)
        upper = min(maximum, pair_total - minimum)
        first = max(lower, min(upper, target))
        current[0] = first
        current[1] = pair_total - first
    elif sash_index == 1:
        first = current[0]
        pair_total = current[1] + current[2]
        second_target = target - first
        lower = max(minimum, pair_total - maximum)
        upper = min(maximum, pair_total - minimum)
        second = max(lower, min(upper, second_target))
        current[1] = second
        current[2] = pair_total - second
    else:
        raise ValueError("sash_index must be 0 or 1")

    total = sum(current)
    return tuple(value / total for value in current)


class _RoundedButton:
    """Canvas-backed button with consistent rounded 3D states."""

    def __init__(
        self,
        master,
        text="",
        command=None,
        bg="#3498db",
        fg="white",
        activebackground=None,
        activeforeground=None,
        font=None,
        width=140,
        height=42,
        state=None,
        compact_height=False,
    ):
        """Create `_RoundedButton` with `master`, `text`, `command`, `bg`, `fg`,
        `activebackground`, `activeforeground`, `font`, `width`, `height`, `state`,
        and `compact_height`.

        Inputs: `master`, `text`, `command`, `bg`, `fg`, `activebackground`,
        `activeforeground`, `font`, `width`, `height`, `state`, `compact_height`.
        Output: None.
        """
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._active_bg = activebackground or _shade_color(bg, -0.08)
        self._active_fg = activeforeground or fg
        self._font = font
        self._width = width
        self._height = height
        self._state = state or _tk_constant("NORMAL", "normal")
        self._pressed = False
        self._hover = False
        self._radius = 7
        self._compact_height = bool(compact_height)
        self._canvas = tk.Canvas(
            master,
            width=width,
            height=height,
            bd=0,
            highlightthickness=0,
            relief=_tk_constant("FLAT", "flat"),
            bg=_resolve_tk_color(master, _widget_background(master)),
        )
        self._canvas.bind("<Configure>", lambda _event: self._redraw())
        self._canvas.bind("<Enter>", self._on_enter)
        self._canvas.bind("<Leave>", self._on_leave)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._sync_cursor()
        self._redraw()

    @staticmethod
    def _canonical_config_key(key):
        """Return the canonical button configuration key.

        Inputs: `key`. Output: normalized key string.
        """
        return _ROUNDED_BUTTON_OPTION_ALIASES.get(str(key), str(key))

    def _set_redraw_option(self, key, value):
        """Set one redraw-triggering option and report whether it changed.

        Inputs: `key`, `value`. Output: bool.
        """
        attribute = _ROUNDED_BUTTON_REDRAW_FIELDS[key]
        if value == getattr(self, attribute):
            return False
        setattr(self, attribute, value)
        return True

    def _set_dimension_option(self, key, value):
        """Set one canvas dimension option and report whether it changed.

        Inputs: `key`, `value`. Output: bool.
        """
        value = int(value)
        attribute = f"_{key}"
        if value == getattr(self, attribute):
            return False
        setattr(self, attribute, value)
        self._canvas.config(**{key: value})
        return True

    def _configure_option(self, key, value):
        """Apply one button option and return redraw/cursor requirements.

        Inputs: `key`, `value`. Output: tuple of bools.
        """
        key = self._canonical_config_key(key)
        if key in _ROUNDED_BUTTON_REDRAW_FIELDS:
            return self._set_redraw_option(key, value), False
        if key == "command":
            self._command = value
            return False, False
        if key == "state":
            return self._set_state_option(value)
        if key in {"width", "height"}:
            return self._set_dimension_option(key, value), False
        self._canvas.config(**{key: value})
        return False, False

    def _set_state_option(self, value):
        """Set the state option and return redraw/cursor requirements.

        Inputs: `value`. Output: tuple of bools.
        """
        if _normalized_tk_state(value) == _normalized_tk_state(self._state):
            return False, False
        self._state = value
        if not self._is_enabled():
            self._pressed = False
            self._hover = False
        return True, True

    def pack(self, *args, **kwargs):
        """Apply pack geometry management.

        Inputs: `*args`, `**kwargs`. Output: `self._canvas.pack` result.
        """
        return self._canvas.pack(*args, **kwargs)

    def grid(self, *args, **kwargs):
        """Apply grid geometry management.

        Inputs: `*args`, `**kwargs`. Output: `self._canvas.grid` result.
        """
        return self._canvas.grid(*args, **kwargs)

    def place(self, *args, **kwargs):
        """Apply place geometry management.

        Inputs: `*args`, `**kwargs`. Output: `self._canvas.place` result.
        """
        return self._canvas.place(*args, **kwargs)

    def pack_forget(self):
        """Remove pack geometry management.

        Inputs: none. Output: `self._canvas.pack_forget` result.
        """
        return self._canvas.pack_forget()

    def grid_remove(self):
        """Remove grid geometry management.

        Inputs: none. Output: `self._canvas.grid_remove` result.
        """
        return self._canvas.grid_remove()

    def config(self, cnf=None, **kwargs):
        """Apply widget configuration.

        Inputs: `cnf`, `**kwargs`. Output: None.
        """
        if cnf:
            kwargs.update(cnf)
        redraw_needed = False
        cursor_needed = False
        for key, value in kwargs.items():
            option_redraw, option_cursor = self._configure_option(key, value)
            redraw_needed = redraw_needed or option_redraw
            cursor_needed = cursor_needed or option_cursor
        if cursor_needed:
            self._sync_cursor()
        if redraw_needed:
            self._redraw()

    configure = config

    def cget(self, key):
        """Return the widget option value.

        Inputs: `key` lookup key. Output: `cget` result.
        """
        if key in {"bg", "background"}:
            return self._bg
        if key == "activebackground":
            return self._active_bg
        if key in {"fg", "foreground"}:
            return self._fg
        if key == "activeforeground":
            return self._active_fg
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return self._canvas.cget(key)

    def invoke(self):
        """Invoke the configured callback.

        Inputs: none. Output: `self._command` result or None.
        """
        if self._is_enabled() and self._command is not None:
            return self._command()
        return None

    def _is_enabled(self):
        """Return whether enabled.

        Inputs: none. Output: bool.
        """
        return _normalized_tk_state(self._state) != _normalized_tk_state(
            _tk_constant("DISABLED", "disabled")
        )

    def _sync_cursor(self):
        """Synchronize the cursor for `_RoundedButton`.

        Inputs: none. Output: None.
        """
        cursor = "hand2" if self._is_enabled() else "arrow"
        self._canvas.config(cursor=cursor)

    def _on_enter(self, _event):
        """Handle enter event.

        Inputs: `_event`. Output: None.
        """
        if self._is_enabled():
            self._hover = True
            self._redraw()

    def _on_leave(self, _event):
        """Handle leave event.

        Inputs: `_event`. Output: None.
        """
        self._hover = False
        self._pressed = False
        self._redraw()

    def _on_press(self, _event):
        """Handle press event.

        Inputs: `_event`. Output: None.
        """
        if self._is_enabled():
            self._pressed = True
            self._redraw()

    def _on_release(self, event):
        """Handle release event.

        Inputs: `event`. Output: `self.invoke` result or None.
        """
        should_invoke = (
            self._is_enabled()
            and self._pressed
            and 0 <= event.x <= self._canvas.winfo_width()
            and 0 <= event.y <= self._canvas.winfo_height()
        )
        self._pressed = False
        self._redraw()
        if should_invoke:
            return self.invoke()
        return None

    def _draw_round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        """Draw the round rect for `_RoundedButton`.

        Inputs: `x1`, `y1`, `x2`, `y2`, `radius`, `**kwargs` keyword arguments. Output:
        `create_polygon` result.
        """
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self._canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=12,
            **kwargs,
        )

    def _redraw(self):
        """Redraw the rounded button after state or size changes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        width = max(int(self._canvas.winfo_width() or self._width), self._width)
        height = max(int(self._canvas.winfo_height() or self._height), self._height)
        self._canvas.delete("all")

        enabled = self._is_enabled()
        pressed = enabled and self._pressed
        if not enabled:
            fill = _blend_colors(self._bg, "#edf1f4", 0.72)
            text_fill = _blend_colors(self._fg, "#6f7b84", 0.62)
            shadow = _blend_colors(self._bg, "#d7dde2", 0.82)
        elif pressed:
            fill = self._active_bg
            text_fill = self._active_fg
            shadow = _shade_color(self._bg, -0.45)
        elif self._hover:
            fill = _shade_color(self._bg, 0.08)
            text_fill = self._fg
            shadow = _shade_color(self._bg, -0.38)
        else:
            fill = self._bg
            text_fill = self._fg
            shadow = _shade_color(self._bg, -0.35)

        surface_offset = 2 if pressed else 0
        if self._compact_height:
            shadow_offset = 1 if pressed else 2
            left = 2
            top = surface_offset
            right = width - 3
            bottom = height - 3 + surface_offset
            radius = min(self._radius, max(3, (height - 4) // 2))
        else:
            shadow_offset = 1 if pressed else 3
            left = 3
            top = 2 + surface_offset
            right = width - 4
            bottom = height - 6 + surface_offset
            radius = min(self._radius, max(3, (height - 10) // 2))

        self._draw_round_rect(
            left + 1,
            top + shadow_offset,
            right + 1,
            bottom + shadow_offset,
            radius,
            fill=shadow,
            outline="",
        )
        self._draw_round_rect(
            left,
            top,
            right,
            bottom,
            radius,
            fill=fill,
            outline=_shade_color(fill, -0.23),
            width=1,
        )
        self._canvas.create_text(
            width / 2 + surface_offset / 2,
            height / 2 + surface_offset / 2 - 1,
            text=self._text,
            fill=text_fill,
            font=self._font,
        )


class _CircularIconButton(_RoundedButton):
    """Canvas-backed circular icon button with the same interaction model."""

    def _redraw(self):
        """Redraw the circular icon button after state or size changes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        width = max(int(self._canvas.winfo_width() or self._width), self._width)
        height = max(int(self._canvas.winfo_height() or self._height), self._height)
        self._canvas.delete("all")

        enabled = self._is_enabled()
        pressed = enabled and self._pressed
        if not enabled:
            fill = _blend_colors(self._bg, "#edf1f4", 0.72)
            outline = _blend_colors(self._bg, "#d7dde2", 0.82)
            text_fill = _blend_colors(self._fg, "#6f7b84", 0.62)
        elif pressed:
            fill = self._active_bg
            outline = _shade_color(self._bg, -0.28)
            text_fill = self._active_fg
        elif self._hover:
            fill = _shade_color(self._bg, 0.1)
            outline = _shade_color(fill, -0.16)
            text_fill = self._fg
        else:
            fill = self._bg
            outline = _shade_color(fill, -0.18)
            text_fill = self._fg

        surface_offset = 1 if pressed else 0
        image = _antialiased_circle_image(self._canvas, width, height, fill, outline)
        self._circle_image = image
        self._canvas.create_image(0, surface_offset, anchor=tk.NW, image=image)
        self._canvas.create_text(
            width / 2 + surface_offset / 2,
            height / 2 + surface_offset / 2 - 1,
            text=self._text,
            fill=text_fill,
            font=self._font,
        )


class _StopSignButton(_RoundedButton):
    """Canvas-backed hexagonal stop button with the shared button behavior."""

    @staticmethod
    def _hexagon_points(left, top, right, bottom):
        """Return traffic-stop-sign polygon coordinates.

        Inputs: bounding box. Output: list of point coordinates.
        """
        width = right - left
        cut = min(width * 0.23, (bottom - top) * 0.45)
        return [
            left + cut,
            top,
            right - cut,
            top,
            right,
            (top + bottom) / 2,
            right - cut,
            bottom,
            left + cut,
            bottom,
            left,
            (top + bottom) / 2,
        ]

    def _redraw(self):
        """Redraw the stop-sign button after state or size changes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        width = max(int(self._canvas.winfo_width() or self._width), self._width)
        height = max(int(self._canvas.winfo_height() or self._height), self._height)
        self._canvas.delete("all")

        enabled = self._is_enabled()
        pressed = enabled and self._pressed
        if not enabled:
            fill = _blend_colors(self._bg, "#edf1f4", 0.65)
            text_fill = _blend_colors(self._fg, "#6f7b84", 0.55)
            border = _blend_colors("#ffffff", "#d7dde2", 0.5)
            shadow = _blend_colors(self._bg, "#d7dde2", 0.8)
        elif pressed:
            fill = self._active_bg
            text_fill = self._active_fg
            border = "#ffffff"
            shadow = _shade_color(self._bg, -0.45)
        elif self._hover:
            fill = _shade_color(self._bg, 0.08)
            text_fill = self._fg
            border = "#ffffff"
            shadow = _shade_color(self._bg, -0.38)
        else:
            fill = self._bg
            text_fill = self._fg
            border = "#ffffff"
            shadow = _shade_color(self._bg, -0.35)

        surface_offset = 2 if pressed else 0
        left = 4
        top = 3 + surface_offset
        right = width - 5
        bottom = height - 6 + surface_offset
        shadow_points = self._hexagon_points(left + 1, top + 3, right + 1, bottom + 3)
        sign_points = self._hexagon_points(left, top, right, bottom)
        self._canvas.create_polygon(shadow_points, fill=shadow, outline="")
        self._canvas.create_polygon(
            sign_points,
            fill=fill,
            outline=border,
            width=3,
            joinstyle=_tk_constant("ROUND", "round"),
        )
        self._canvas.create_text(
            width / 2 + surface_offset / 2,
            height / 2 + surface_offset / 2 - 1,
            text=self._text,
            fill=text_fill,
            font=self._font,
        )


class _ConverterDropdown:
    """Fixed-pixel dropdown whose popup matches the closed selector width."""

    def __init__(
        self,
        master,
        variable,
        command=None,
        on_open=None,
        width=CONVERTER_DROPDOWN_WIDTH,
        height=CONVERTER_DROPDOWN_HEIGHT,
        font=CONVERTER_MENU_FONT,
        bg="#f8f9fa",
        fg="#2c3e50",
        activebackground="#e9eef3",
        activeforeground="#2c3e50",
    ):
        """Create the converter dropdown.

        Inputs: widget options. Output: None.
        """
        self._variable = variable
        self._command = command
        self._on_open = on_open
        self._width = int(width)
        self._height = int(height)
        self._font = font
        self._bg = bg
        self._fg = fg
        self._active_bg = activebackground
        self._active_fg = activeforeground
        self._text_pad = CONVERTER_DROPDOWN_TEXT_PAD
        self._options = []
        self._popup = None
        self._root_click_bind_id = None
        self._root_escape_bind_id = None
        self._hover = False
        self._open = False
        self._border = "#aeb8c2"
        self._active_border = "#7f95aa"
        self._frame = tk.Frame(
            master,
            width=self._width,
            height=self._height,
            bg=self._border,
            bd=0,
            highlightthickness=0,
        )
        self._frame.grid_propagate(False)
        self._frame.pack_propagate(False)
        self._surface = tk.Frame(self._frame, bg=self._bg, bd=0)
        self._surface.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._label = tk.Label(
            self._surface,
            textvariable=self._variable,
            bg=self._bg,
            fg=self._fg,
            font=self._font,
            anchor=tk.W,
            justify=tk.LEFT,
            padx=self._text_pad,
            pady=0,
        )
        self._label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._arrow = tk.Canvas(
            self._surface,
            width=CONVERTER_DROPDOWN_ARROW_WIDTH,
            height=self._height,
            bg=self._bg,
            bd=0,
            highlightthickness=0,
            relief=_tk_constant("FLAT", "flat"),
        )
        self._arrow.pack(side=tk.RIGHT, fill=tk.Y)
        for widget in (self._frame, self._surface, self._label, self._arrow):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._toggle_popup)
        self._arrow.bind("<Configure>", lambda _event: self._draw_arrow())
        self._apply_style()

    def pack(self, *args, **kwargs):
        """Apply pack geometry management.

        Inputs: `*args`, `**kwargs`. Output: frame pack result.
        """
        return self._frame.pack(*args, **kwargs)

    def grid(self, *args, **kwargs):
        """Apply grid geometry management.

        Inputs: `*args`, `**kwargs`. Output: frame grid result.
        """
        return self._frame.grid(*args, **kwargs)

    def pack_forget(self):
        """Remove pack geometry management.

        Inputs: none. Output: frame pack forget result.
        """
        return self._frame.pack_forget()

    def config(self, cnf=None, **kwargs):
        """Apply fixed dropdown configuration.

        Inputs: `cnf`, `**kwargs`. Output: None.
        """
        if cnf:
            kwargs.update(cnf)
        redraw_needed = False
        if "width" in kwargs:
            self._width = int(kwargs.pop("width"))
            self._frame.config(width=self._width)
        if "height" in kwargs:
            self._height = int(kwargs.pop("height"))
            self._frame.config(height=self._height)
            self._arrow.config(height=self._height)
            redraw_needed = True
        if kwargs:
            self._frame.config(**kwargs)
        if redraw_needed:
            self._draw_arrow()

    configure = config

    def cget(self, key):
        """Return fixed dropdown configuration values.

        Inputs: `key`. Output: option value.
        """
        if key == "width":
            return self._width
        if key == "height":
            return self._height
        return self._frame.cget(key)

    def set_options(self, options):
        """Replace dropdown options and close any stale popup.

        Inputs: `options`. Output: None.
        """
        self._options = [str(option) for option in options or []]
        if not self._options:
            self.close_popup()

    def _apply_style(self):
        """Apply normal, hover, or open visual state.

        Inputs: none. Output: None.
        """
        highlighted = self._open or self._hover
        bg = self._active_bg if highlighted else self._bg
        fg = self._active_fg if highlighted else self._fg
        border = self._active_border if highlighted else self._border
        self._frame.config(bg=border)
        self._surface.config(bg=bg)
        self._arrow.config(bg=bg)
        for widget in (self._label,):
            widget.config(bg=bg, fg=fg)
        self._draw_arrow(fg)

    def _draw_arrow(self, color=None):
        """Draw the dropdown arrow as a clean chevron.

        Inputs: optional `color`. Output: None.
        """
        color = color or (self._active_fg if self._open or self._hover else self._fg)
        width = max(
            int(self._arrow.winfo_width() or CONVERTER_DROPDOWN_ARROW_WIDTH),
            CONVERTER_DROPDOWN_ARROW_WIDTH,
        )
        height = max(int(self._arrow.winfo_height() or self._height), self._height)
        center_x = width / 2
        center_y = height / 2
        self._arrow.delete("all")
        self._arrow.create_line(
            center_x - 4,
            center_y - 2,
            center_x,
            center_y + 2,
            center_x + 4,
            center_y - 2,
            fill=color,
            width=1.7,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
        )

    def _on_enter(self, _event):
        """Handle pointer enter.

        Inputs: event. Output: None.
        """
        self._hover = True
        self._apply_style()

    def _on_leave(self, _event):
        """Handle pointer leave.

        Inputs: event. Output: None.
        """
        self._hover = False
        self._apply_style()

    def _toggle_popup(self, _event=None):
        """Toggle the dropdown popup.

        Inputs: optional event. Output: Tk break marker.
        """
        if self._open:
            self.close_popup()
        else:
            self.open_popup()
        return "break"

    def open_popup(self):
        """Open the fixed-width popup below the selector.

        Inputs: none. Output: None.
        """
        if not self._options:
            return
        self.close_popup()
        if callable(self._on_open):
            self._on_open()
        self._open = True
        self._apply_style()
        self._frame.update_idletasks()
        width = max(self._width, _safe_widget_dimension(self._frame, "winfo_width"))
        item_height = max(28, self._height - 4)
        height = max(item_height, len(self._options) * item_height + 2)
        popup = tk.Toplevel(self._frame)
        popup.overrideredirect(True)
        popup.configure(bg=self._border)
        popup.geometry(
            f"{width}x{height}+{self._frame.winfo_rootx()}+"
            f"{self._frame.winfo_rooty() + self._frame.winfo_height()}"
        )
        popup.bind("<Escape>", lambda _event: self.close_popup())
        container = tk.Frame(popup, bg=self._border, bd=0)
        container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        for option in self._options:
            item = tk.Label(
                container,
                text=option,
                bg=self._bg,
                fg=self._fg,
                font=self._font,
                anchor=tk.W,
                justify=tk.LEFT,
                padx=self._text_pad,
                pady=0,
            )
            item.pack(fill=tk.X, ipady=(item_height - 16) // 2)
            item.bind(
                "<Enter>",
                lambda _event, widget=item: widget.config(
                    bg=self._active_bg,
                    fg=self._active_fg,
                ),
            )
            item.bind(
                "<Leave>",
                lambda _event, widget=item: widget.config(bg=self._bg, fg=self._fg),
            )
            item.bind(
                "<ButtonRelease-1>",
                lambda _event, value=option: self._choose(value),
            )
        self._popup = popup
        self._bind_root_click_close()
        popup.lift()

    def _bind_root_click_close(self):
        """Close the popup on the next click outside the selector and popup.

        Inputs: none. Output: None.
        """
        root = self._frame.winfo_toplevel()
        bind = getattr(root, "bind", None)
        if callable(bind):
            self._root_click_bind_id = bind(
                "<ButtonPress-1>",
                self._close_on_root_click_outside,
                add="+",
            )
            self._root_escape_bind_id = bind(
                "<Escape>",
                lambda _event: self.close_popup(),
                add="+",
            )

    def _unbind_root_click_close(self):
        """Remove the temporary outside-click binding.

        Inputs: none. Output: None.
        """
        root = self._frame.winfo_toplevel()
        unbind = getattr(root, "unbind", None)
        if callable(unbind):
            for sequence, bind_id in (
                ("<ButtonPress-1>", self._root_click_bind_id),
                ("<Escape>", self._root_escape_bind_id),
            ):
                if bind_id:
                    with contextlib.suppress(Exception):
                        unbind(sequence, bind_id)
        self._root_click_bind_id = None
        self._root_escape_bind_id = None

    def _close_on_root_click_outside(self, event):
        """Close the dropdown when the root receives an outside click.

        Inputs: Tk event. Output: None.
        """
        event_widget = getattr(event, "widget", None)
        if _widget_is_or_descendant(event_widget, self._frame):
            return None
        if _widget_is_or_descendant(event_widget, self._popup):
            return None
        self.close_popup()
        return None

    def close_popup(self):
        """Close the dropdown popup and restore selector state.

        Inputs: none. Output: None.
        """
        popup = self._popup
        self._popup = None
        self._open = False
        self._apply_style()
        self._unbind_root_click_close()
        if popup is None:
            return
        try:
            if popup.winfo_exists():
                popup.destroy()
        except Exception:
            return

    def _choose(self, value):
        """Choose a dropdown value.

        Inputs: `value`. Output: command result or None.
        """
        self.close_popup()
        if callable(self._command):
            return self._command(value)
        self._variable.set(value)
        return None


class _PasswordRevealButton(_RoundedButton):
    """Canvas-backed password visibility indicator with a timed reveal state."""

    def __init__(self, *args, **kwargs):
        """Create the password reveal button.

        Inputs: forwarded button arguments. Output: None.
        """
        self._visible = False
        super().__init__(*args, **kwargs)

    def set_visible(self, visible):
        """Update whether the button should draw the revealed-password state.

        Inputs: `visible`. Output: None.
        """
        visible = bool(visible)
        if visible != self._visible:
            self._visible = visible
            self._redraw()

    def _redraw(self):
        """Redraw the password reveal indicator.

        Inputs: no caller arguments. Output: None.
        """
        width = max(int(self._canvas.winfo_width() or self._width), self._width)
        height = max(int(self._canvas.winfo_height() or self._height), self._height)
        self._canvas.delete("all")

        enabled = self._is_enabled()
        pressed = enabled and self._pressed
        visible = self._visible
        if not enabled:
            icon = "#94a3b8"
        elif pressed:
            icon = self._fg
        elif self._hover:
            icon = _shade_color(self._fg, -0.12)
        else:
            icon = self._fg

        self._circle_image = None
        center_x = width / 2
        center_y = height / 2
        left = max(3.0, center_x - 6.2)
        right = min(width - 3.0, center_x + 6.2)
        top = center_y - 4.0
        bottom = center_y + 4.0
        self._canvas.create_polygon(
            left,
            center_y,
            center_x - 3.4,
            top,
            center_x,
            top + 0.5,
            center_x + 3.4,
            top,
            right,
            center_y,
            center_x + 3.4,
            bottom,
            center_x,
            bottom - 0.5,
            center_x - 3.4,
            bottom,
            smooth=True,
            fill="",
            outline=icon,
            width=1.3,
        )
        radius = 2.0 if visible else 1.45
        self._canvas.create_oval(
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
            fill=icon,
            outline=icon,
        )
        if not visible:
            self._canvas.create_line(
                right - 1.0,
                top - 1.0,
                left + 1.0,
                bottom + 1.0,
                fill=icon,
                width=1.5,
                capstyle=tk.ROUND,
            )


def _unique_path_candidate(path, seen):
    """Return a normalized candidate path once.

    Inputs: `path`, `seen`. Output: normalized path or None.
    """
    normalized = os.path.normpath(path)
    if normalized in seen:
        return None
    seen.add(normalized)
    return normalized


def _iter_unique_path_candidates(candidates, seen):
    """Yield normalized path candidates that have not been seen.

    Inputs: `candidates`, `seen`. Output: yielded normalized path strings.
    """
    for candidate in candidates:
        normalized = _unique_path_candidate(candidate, seen)
        if normalized is not None:
            yield normalized


def _import_winreg_module():
    """Return the Windows registry module when available.

    Inputs: none. Output: module or None.
    """
    winreg_module: Any = None
    try:
        winreg_module = importlib.import_module("winreg")
    except ImportError:
        return None
    return winreg_module


def _imaris_arena_registry_version_from_executable(imaris_executable):
    """Return the major.minor Imaris registry version for an executable path.

    Inputs: `imaris_executable`. Output: version text or None.
    """
    candidate = _coerce_path(imaris_executable)
    if candidate is None:
        return None
    path_parts = []
    with contextlib.suppress(Exception):
        path_parts.append(candidate.parent.name)
    with contextlib.suppress(Exception):
        path_parts.append(candidate.parent.parent.name)
    for path_part in path_parts:
        match = re.search(
            r"\bImaris(?:\s+x64)?\s*(\d+)(?:\.(\d+))?",
            str(path_part or ""),
            flags=re.IGNORECASE,
        )
        if match:
            return f"{match.group(1)}.{match.group(2) or '0'}"
    return None


def _imaris_arena_registry_key_from_executable(imaris_executable):
    """Return the HKCU Imaris Arena DataManagementSystem registry key path.

    Inputs: `imaris_executable`. Output: registry key path or None.
    """
    version = _imaris_arena_registry_version_from_executable(imaris_executable)
    if not version:
        return None
    return (
        rf"{IMARIS_ARENA_VENDOR_REGISTRY_ROOT}\Imaris x64 {version}"
        rf"\{IMARIS_ARENA_DATA_MANAGEMENT_SUBKEY}"
    )


def _imaris_arena_registry_version_tuple(version_text):
    """Return a sortable version tuple from an Imaris registry version string.

    Inputs: `version_text`. Output: version tuple or None.
    """
    match = re.match(r"^\s*(\d+)(?:\.(\d+))?\s*$", str(version_text or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _imaris_arena_registry_version_from_key_name(key_name):
    """Return the Imaris major.minor registry version from a subkey name.

    Inputs: `key_name`. Output: version text or None.
    """
    match = re.match(
        r"^Imaris(?:\s+x64)?(?:\s+(\d+)(?:\.(\d+))?)?$",
        str(key_name or "").strip(),
        flags=re.IGNORECASE,
    )
    if not match or not match.group(1):
        return None
    return f"{match.group(1)}.{match.group(2) or '0'}"


def _imaris_arena_close_registry_key(key):
    """Close a registry key object when it exposes a close method.

    Inputs: `key`. Output: None.
    """
    close = getattr(key, "Close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _iter_existing_imaris_arena_registry_key_paths(winreg_module):
    """Yield existing HKCU Imaris Arena DataManagementSystem registry keys.

    Inputs: `winreg_module`. Output: yielded `(version_tuple, key_path)` values.
    """
    if winreg_module is None:
        return
    root_key = None
    try:
        root_key = winreg_module.OpenKey(
            winreg_module.HKEY_CURRENT_USER,
            IMARIS_ARENA_VENDOR_REGISTRY_ROOT,
            0,
            getattr(winreg_module, "KEY_READ", 0),
        )
        index = 0
        while True:
            try:
                subkey_name = winreg_module.EnumKey(root_key, index)
            except OSError:
                break
            index += 1
            version = _imaris_arena_registry_version_from_key_name(subkey_name)
            version_tuple = _imaris_arena_registry_version_tuple(version)
            if version_tuple is None:
                continue
            key_path = (
                rf"{IMARIS_ARENA_VENDOR_REGISTRY_ROOT}\{subkey_name}"
                rf"\{IMARIS_ARENA_DATA_MANAGEMENT_SUBKEY}"
            )
            arena_key = None
            try:
                arena_key = winreg_module.OpenKey(
                    winreg_module.HKEY_CURRENT_USER,
                    key_path,
                    0,
                    getattr(winreg_module, "KEY_READ", 0),
                )
            except OSError:
                continue
            finally:
                _imaris_arena_close_registry_key(arena_key)
            yield version_tuple, key_path
    except OSError:
        return
    finally:
        _imaris_arena_close_registry_key(root_key)


def _imaris_arena_registry_key_candidates(imaris_executable, winreg_module):
    """Return candidate HKCU Arena registry key paths for the current Imaris.

    Inputs: optional `imaris_executable`, `winreg_module`. Output: tuple of paths.
    """
    expected_version = _imaris_arena_registry_version_from_executable(imaris_executable)
    candidates = []
    expected_path = _imaris_arena_registry_key_from_executable(imaris_executable)
    if expected_path:
        candidates.append(expected_path)

    existing_paths = tuple(
        _iter_existing_imaris_arena_registry_key_paths(winreg_module)
    )
    if expected_version:
        expected_tuple = _imaris_arena_registry_version_tuple(expected_version)
        for version_tuple, key_path in existing_paths:
            if version_tuple == expected_tuple:
                candidates.append(key_path)
    elif len(existing_paths) == 1:
        candidates.append(existing_paths[0][1])
    elif len(existing_paths) > 1:
        _xt_debug(
            "Imaris Arena observed-folder append skipped: ambiguous registry version"
        )

    unique_candidates = []
    seen = set()
    for key_path in candidates:
        if key_path and key_path not in seen:
            seen.add(key_path)
            unique_candidates.append(key_path)
    return tuple(unique_candidates)


def _folder_path_identity(path_value):
    """Return a normalized identity for folder path comparisons.

    Inputs: `path_value`. Output: normalized path text or empty string.
    """
    try:
        path_text = os.fspath(path_value)
    except TypeError:
        return ""
    if isinstance(path_text, bytes):
        return ""
    path_text = str(path_text or "").strip()
    if not path_text:
        return ""
    normalizer = ntpath if _looks_like_windows_path(path_text) else os.path
    try:
        return normalizer.normcase(normalizer.normpath(path_text))
    except (TypeError, ValueError):
        return ""


def _expand_windows_environment_variables(path_value):
    """Expand Windows-style environment variables in a local path string.

    Inputs: `path_value`. Output: expanded path text.
    """
    try:
        path_text = os.fspath(path_value)
    except TypeError:
        return ""
    if isinstance(path_text, bytes):
        return ""
    path_text = str(path_text or "").strip()
    if not path_text:
        return ""

    def replace_percent_var(match):
        """Return the environment replacement for a `%VAR%` match.

        Inputs: `match`. Output: replacement path fragment.
        """
        name = match.group(1)
        for env_name, env_value in os.environ.items():
            if env_name.upper() == name.upper():
                return env_value
        return match.group(0)

    expanded = re.sub(r"%([^%]+)%", replace_percent_var, path_text)
    return os.path.expanduser(os.path.expandvars(expanded))


def _normalize_imaris_arena_folder_path(path_value):
    """Return the folder path text written to Imaris Arena settings.

    Inputs: `path_value`. Output: normalized folder path text.
    """
    expanded = _expand_windows_environment_variables(path_value)
    normalizer = ntpath if _looks_like_windows_path(expanded) else os.path
    return normalizer.normpath(expanded)


def _iter_imaris_arena_tree_state_tokens(tree_state):
    """Yield `(node_name, value)` pairs from an Imaris Arena tree state string.

    Inputs: `tree_state`. Output: yielded Arena node tuples.
    """
    text = str(tree_state or "")
    matches = list(re.finditer(r"\[(Observed|Selected)\]", text))
    for index, match in enumerate(matches):
        value_start = match.end()
        value_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(text)
        )
        yield match.group(1), text[value_start:value_end]


def _imaris_arena_tree_state_has_observed_folder(tree_state, folder_path):
    """Return whether a tree state already observes `folder_path`.

    Inputs: `tree_state`, `folder_path`. Output: bool.
    """
    target = _folder_path_identity(folder_path)
    if not target:
        return False
    for node_name, node_value in _iter_imaris_arena_tree_state_tokens(tree_state):
        if node_name != "Observed":
            continue
        if _folder_path_identity(node_value) == target:
            return True
    return False


def _append_imaris_arena_tree_state_observed_folder(tree_state, folder_path):
    """Return tree state text with `folder_path` present as an observed folder.

    Inputs: `tree_state`, `folder_path`. Output: updated tree state text.
    """
    text = str(tree_state or "")
    folder_text = str(folder_path or "").strip()
    if not folder_text:
        return text
    if _imaris_arena_tree_state_has_observed_folder(text, folder_text):
        return text
    observed_token = f"[Observed]{folder_text}"
    if not text:
        return f"{observed_token}[Selected]{folder_text}"
    selected_index = text.find("[Selected]")
    if selected_index >= 0:
        return text[:selected_index] + observed_token + text[selected_index:]
    return text + observed_token


def _imaris_arena_folder_list_has_folder(folder_list, folder_path):
    """Return whether an Arena folder list value already contains `folder_path`.

    Inputs: `folder_list`, `folder_path`. Output: bool.
    """
    target = _folder_path_identity(folder_path)
    if not target:
        return False
    parts = re.split(r"[;\r\n]+", str(folder_list or ""))
    return any(_folder_path_identity(part) == target for part in parts if part.strip())


def _append_imaris_arena_folder_list_value(folder_list, folder_path):
    """Return an Arena folder-list value with `folder_path` appended once.

    Inputs: `folder_list`, `folder_path`. Output: updated folder-list text.
    """
    text = str(folder_list or "")
    folder_text = str(folder_path or "").strip()
    if not folder_text:
        return text
    if _imaris_arena_folder_list_has_folder(text, folder_text):
        return text
    if not text:
        return folder_text
    separator = "\n" if "\n" in text and ";" not in text else ";"
    return text.rstrip() + separator + folder_text


def _query_registry_string_value(winreg_module, key, value_name):
    """Return a registry string value or empty string when absent.

    Inputs: `winreg_module`, opened `key`, `value_name`. Output: string value.
    """
    try:
        value, _value_type = winreg_module.QueryValueEx(key, value_name)
    except OSError:
        return ""
    return str(value or "")


def _append_imaris_arena_observed_folder(
    folder_path, imaris_executable=None, winreg_module=None
):
    """Append an existing folder to Imaris Arena observed folders.

    Inputs: `folder_path`, optional `imaris_executable`, optional `winreg_module`.
    Output: bool indicating whether the folder is present or was written.
    """
    key = None
    try:
        if os.name != "nt":
            _xt_debug("Imaris Arena observed-folder append skipped: not Windows")
            return False
        folder_text = _normalize_imaris_arena_folder_path(folder_path)
        if not _is_structurally_valid_folder_path(folder_text):
            _xt_debug(
                "Imaris Arena observed-folder append skipped: invalid folder path"
            )
            return False
        if not _safe_is_directory(folder_text):
            _xt_debug(
                "Imaris Arena observed-folder append skipped: folder does not exist"
            )
            return False

        winreg_module = winreg_module or _import_winreg_module()
        if winreg_module is None:
            _xt_debug("Imaris Arena observed-folder append skipped: winreg unavailable")
            return False

        imaris_executable = imaris_executable or _find_imaris_executable()
        key_paths = _imaris_arena_registry_key_candidates(
            imaris_executable,
            winreg_module,
        )
        if not key_paths:
            _xt_debug("Imaris Arena observed-folder append skipped: no registry key")
            return False

        last_error = None
        access = getattr(winreg_module, "KEY_READ", 0) | getattr(
            winreg_module, "KEY_WRITE", 0
        )
        for key_path in key_paths:
            key = None
            try:
                key = winreg_module.OpenKey(
                    winreg_module.HKEY_CURRENT_USER,
                    key_path,
                    0,
                    access,
                )
                tree_state = _query_registry_string_value(
                    winreg_module,
                    key,
                    IMARIS_ARENA_OBSERVED_FOLDERS_TREE_STATE_VALUE,
                )
                folder_list = _query_registry_string_value(
                    winreg_module,
                    key,
                    IMARIS_ARENA_OBSERVED_FOLDERS_VALUE,
                )
                if _imaris_arena_tree_state_has_observed_folder(
                    tree_state, folder_text
                ) or _imaris_arena_folder_list_has_folder(folder_list, folder_text):
                    _xt_debug(
                        "Imaris Arena observed-folder setting already contains "
                        f"selected path; no registry write needed: {folder_text}"
                    )
                    return True
                new_tree_state = _append_imaris_arena_tree_state_observed_folder(
                    tree_state,
                    folder_text,
                )
                new_folder_list = _append_imaris_arena_folder_list_value(
                    folder_list,
                    folder_text,
                )
                value_type = getattr(winreg_module, "REG_SZ", 1)
                if new_tree_state != tree_state:
                    winreg_module.SetValueEx(
                        key,
                        IMARIS_ARENA_OBSERVED_FOLDERS_TREE_STATE_VALUE,
                        0,
                        value_type,
                        new_tree_state,
                    )
                if new_folder_list != folder_list:
                    winreg_module.SetValueEx(
                        key,
                        IMARIS_ARENA_OBSERVED_FOLDERS_VALUE,
                        0,
                        value_type,
                        new_folder_list,
                    )
                verified_tree_state = _query_registry_string_value(
                    winreg_module,
                    key,
                    IMARIS_ARENA_OBSERVED_FOLDERS_TREE_STATE_VALUE,
                )
                verified_folder_list = _query_registry_string_value(
                    winreg_module,
                    key,
                    IMARIS_ARENA_OBSERVED_FOLDERS_VALUE,
                )
                if _imaris_arena_tree_state_has_observed_folder(
                    verified_tree_state, folder_text
                ) or _imaris_arena_folder_list_has_folder(
                    verified_folder_list, folder_text
                ):
                    _xt_debug(
                        "Imaris Arena observed-folder setting contains selected path: "
                        f"{folder_text}"
                    )
                    return True
                last_error = OSError("registry write did not persist")
            except OSError as exc:
                last_error = exc
            finally:
                _imaris_arena_close_registry_key(key)
        if last_error is not None:
            _xt_debug(
                "Imaris Arena observed-folder append failed: "
                f"{type(last_error).__name__}: {last_error}"
            )
        else:
            _xt_debug("Imaris Arena observed-folder append failed: no key opened")
        return False
    except OSError as exc:
        _xt_debug(
            f"Imaris Arena observed-folder append failed: {type(exc).__name__}: {exc}"
        )
        return False
    except Exception as exc:
        _xt_debug(
            f"Imaris Arena observed-folder append failed: {type(exc).__name__}: {exc}"
        )
        return False


def _imaris_registry_locations(winreg_module):
    """Return registry locations that may define the Imaris executable.

    Inputs: `winreg_module`. Output: tuple of registry location pairs.
    """
    return (
        (
            winreg_module.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Imaris.exe",
        ),
        (
            winreg_module.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Imaris.exe",
        ),
    )


def _iter_imaris_registry_executable_candidates(winreg_module):
    """Yield Imaris executable candidates from the Windows registry.

    Inputs: `winreg_module`. Output: yielded path strings.
    """
    if winreg_module is None:
        return
    for hive, subkey in _imaris_registry_locations(winreg_module):
        try:
            with winreg_module.OpenKey(hive, subkey) as key:
                value, _ = winreg_module.QueryValueEx(key, None)
        except (OSError, ValueError):
            continue
        if value:
            yield value


def _iter_imaris_vendor_roots():
    """Yield installation vendor roots under Windows program directories.

    Inputs: none. Output: yielded directory strings.
    """
    base_dirs = [
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    vendor_dirs = [
        "Bitplane",
        "Oxford Instruments",
    ]
    for base_dir in base_dirs:
        if not base_dir:
            continue
        for vendor_dir in vendor_dirs:
            vendor_root = os.path.join(base_dir, vendor_dir)
            if os.path.isdir(vendor_root):
                yield vendor_root


def _safe_sorted_directory_entries(path, *, reverse=False):
    """Return sorted directory entries or an empty tuple when unavailable.

    Inputs: `path`, optional `reverse`. Output: tuple of entry names.
    """
    try:
        return tuple(sorted(os.listdir(path), reverse=reverse))
    except Exception:
        return ()


def _imaris_vendor_entry_executable_path(vendor_root, entry):
    """Return the supported Imaris executable path for a vendor entry.

    Inputs: `vendor_root`, `entry`. Output: path string or None.
    """
    if not entry.lower().startswith("imaris"):
        return None
    candidate = os.path.join(vendor_root, entry, "Imaris.exe")
    if not _is_supported_imaris_install_path(candidate):
        return None
    return candidate


def _iter_imaris_vendor_executable_candidates():
    """Yield supported Imaris executable candidates from vendor directories.

    Inputs: none. Output: yielded path strings.
    """
    for vendor_root in _iter_imaris_vendor_roots():
        for entry in _safe_sorted_directory_entries(vendor_root, reverse=True):
            candidate = _imaris_vendor_entry_executable_path(vendor_root, entry)
            if candidate is not None:
                yield candidate


def _iter_imaris_home_executable_candidates():
    """Yield Imaris.exe candidates from the configured Imaris install root.

    Inputs: none. Output: yielded path strings.
    """
    env_root = os.environ.get("IMARIS_HOME", "").strip()
    if not env_root:
        return
    yield os.path.join(os.path.normpath(env_root), "Imaris.exe")


def _iter_imaris_executable_candidates(settings_path=None):
    """Yield plausible Imaris executable paths without requiring admin access.

    Inputs: optional `settings_path`. Output: yielded values.
    """
    seen: Set[str] = set()
    settings_candidate = _connector_settings_imaris_executable_candidate(settings_path)
    if settings_candidate:
        yield from _iter_unique_path_candidates((settings_candidate,), seen)
    env_candidate = os.environ.get("IMARIS_EXE", "").strip()
    if env_candidate:
        yield from _iter_unique_path_candidates((env_candidate,), seen)
    yield from _iter_unique_path_candidates(
        _iter_imaris_home_executable_candidates(),
        seen,
    )
    yield from _iter_unique_path_candidates(
        _iter_imaris_registry_executable_candidates(_import_winreg_module()),
        seen,
    )
    yield from _iter_unique_path_candidates(
        _iter_imaris_vendor_executable_candidates(),
        seen,
    )


def _find_imaris_executable(settings_path=None):
    """Return a launchable Imaris.exe path if present.

    Inputs: optional `settings_path`. Output: `candidate` or None.
    """
    if os.name != "nt":
        return None
    for candidate in _iter_imaris_executable_candidates(settings_path):
        if _is_existing_supported_imaris_executable_path(candidate):
            return candidate
    return None


def _imaris_file_converter_executable_path(imaris_executable):
    """Return the sibling Imaris File Converter executable path.

    Inputs: `imaris_executable`. Output: path text or None.
    """
    candidate = _existing_regular_file_path(imaris_executable)
    if candidate is None:
        return None
    converter = candidate.with_name("ImarisFileConverter.exe")
    if converter.is_file() and _is_supported_imaris_install_path(converter):
        return str(converter)
    return None


def _iter_imaris_file_converter_executable_candidates():
    """Yield Imaris File Converter executable candidates.

    Inputs: none. Output: yielded path strings.
    """
    seen: Set[str] = set()
    imaris_executable = _find_imaris_executable()
    if imaris_executable:
        converter = _imaris_file_converter_executable_path(imaris_executable)
        if converter:
            yield from _iter_unique_path_candidates((converter,), seen)
    for install_root in _iter_imaris_install_roots():
        converter = os.path.join(install_root, "ImarisFileConverter.exe")
        yield from _iter_unique_path_candidates((converter,), seen)


def _find_imaris_file_converter_executable():
    """Return a launchable ImarisFileConverter.exe path if present.

    Inputs: none. Output: `candidate` or None.
    """
    if os.name != "nt":
        return None
    for candidate in _iter_imaris_file_converter_executable_candidates():
        path = _existing_regular_file_path(candidate)
        if path is not None and path.name.lower() == "imarisfileconverter.exe":
            if _is_supported_imaris_install_path(path):
                return str(path)
    return None


def _submit_files_to_imaris_file_converter(file_paths):
    """Submit existing files to the installed Imaris File Converter.

    Inputs: `file_paths`. Output: bool indicating whether the GUI launch
    request was accepted by the OS.
    """
    candidates = _existing_regular_file_path_list(file_paths)
    if candidates is None:
        _xt_debug("Imaris File Converter handoff skipped: file does not exist")
        return False
    file_converter_executable = _find_imaris_file_converter_executable()
    if not file_converter_executable:
        _xt_debug(
            "Imaris File Converter handoff skipped: "
            "ImarisFileConverter.exe was not found"
        )
        return False
    try:
        subprocess.Popen(
            [file_converter_executable] + [str(candidate) for candidate in candidates],
            cwd=os.path.dirname(file_converter_executable) or None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as exc:
        _xt_debug(f"Imaris File Converter handoff failed: {type(exc).__name__}: {exc}")
        return False
    _xt_debug(
        "Imaris converter: submitted selected Image export"
        f"{'s' if len(candidates) != 1 else ''} to Imaris File Converter"
    )
    return True


def submit_selected_image_export_to_imaris_converter(file_path):
    """Submit one connector-selected Image export to Imaris' own converter.

    Inputs: `file_path`. Output: bool.
    """
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        _xt_debug("Selected-image export handoff skipped: file does not exist")
        return False
    if not is_tiff_file(candidate):
        _xt_debug(
            "Selected-image export handoff skipped: file is not a readable TIFF file"
        )
        return False
    return _submit_files_to_imaris_file_converter([candidate])


def submit_selected_image_exports_to_imaris_converter(file_paths):
    """Submit connector-selected Image exports to Imaris' own converter.

    Inputs: `file_paths`. Output: bool.
    """
    if isinstance(file_paths, (str, bytes, os.PathLike)):
        file_paths = [file_paths]
    else:
        try:
            file_paths = list(file_paths)
        except TypeError:
            file_paths = []
    if not file_paths:
        _xt_debug("Selected-image export batch handoff skipped: no files provided")
        return False

    for file_path in file_paths:
        candidate = _existing_regular_file_path(file_path)
        if candidate is None:
            _xt_debug("Selected-image export batch handoff skipped: file is missing")
            return False
        if not is_tiff_file(candidate):
            _xt_debug(
                "Selected-image export batch handoff skipped: one file is not a "
                "readable TIFF file"
            )
            return False

    return _submit_files_to_imaris_file_converter(file_paths)


def _existing_regular_file_path_list(file_paths):
    """Return existing regular file path list.

    Inputs: `file_paths`. Output: `candidates` or None.
    """
    if isinstance(file_paths, (str, bytes, os.PathLike)):
        file_paths = [file_paths]
    else:
        try:
            file_paths = list(file_paths)
        except TypeError:
            file_paths = []
    if not file_paths:
        return None

    candidates = []
    for file_path in file_paths:
        candidate = _existing_regular_file_path(file_path)
        if candidate is None:
            return None
        candidates.append(candidate)
    return candidates


def _iter_imaris_install_roots():
    """Yield plausible Imaris installation roots.

    Inputs: none. Output: yielded values.
    """
    seen = set()

    env_root = os.environ.get("IMARIS_HOME", "").strip()
    if env_root:
        normalized = os.path.normpath(env_root)
        if _is_supported_imaris_install_path(normalized) and normalized not in seen:
            seen.add(normalized)
            yield normalized

    exe_path = _find_imaris_executable()
    if exe_path:
        install_root = os.path.dirname(exe_path)
        normalized = os.path.normpath(install_root)
        if _is_supported_imaris_install_path(normalized) and normalized not in seen:
            seen.add(normalized)
            yield normalized


def _iter_imaris_xt_path_candidates(install_root):
    """Yield native Imaris XT directories that may contain modules or DLLs.

    Inputs: `install_root`. Output: yielded values.
    """
    yield install_root
    yield os.path.join(install_root, "XT")
    yield os.path.join(install_root, "XT", "python3")
    yield os.path.join(install_root, "XT", "python3", "DLLs")
    yield os.path.join(install_root, "XT", "bin")
    yield os.path.join(install_root, "XT", "python3", "Lib")
    yield os.path.join(install_root, "XT", "python3", "Lib", "site-packages")
    yield os.path.join(install_root, "XT", "python3", "private")
    yield os.path.join(install_root, "XT", "python3", "private", "Ice")
    yield os.path.join(install_root, "XT", "python")
    yield os.path.join(install_root, "XT", "lib")


def _parse_python_launcher_paths(output):
    """Parse and validate the python launcher paths input.

    Inputs: `output`. Output: `paths`.
    """
    paths = []
    for line in str(output or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        candidate = parts[1].strip()
        if candidate.endswith("*"):
            candidate = candidate[:-1].strip()
        if candidate:
            paths.append(candidate)
    return paths


def _resolve_python_executable_candidate(candidate):
    """Resolve the python executable candidate.

    Inputs: `candidate`. Output: `str`.
    """
    path = _existing_regular_file_path(candidate)
    if path is None:
        return None
    if path.name.lower() not in {"python.exe", "pythonw.exe"}:
        return None
    try:
        return str(path.resolve(strict=True))
    except OSError:
        return None


def _iter_windows_python_launchers():
    """Windows python launchers.

    Inputs: none. Output: yielded values.
    """
    seen = set()
    for env_name in ("SystemRoot", "WINDIR"):
        root = os.environ.get(env_name, "").strip()
        if not root:
            continue
        candidate = os.path.join(root, "py.exe")
        path = _existing_regular_file_path(candidate)
        if path is None or path.name.lower() != "py.exe":
            continue
        try:
            resolved = str(path.resolve(strict=True))
        except OSError:
            continue
        normalized = os.path.normcase(os.path.normpath(resolved))
        if normalized in seen:
            continue
        seen.add(normalized)
        yield resolved


def _iter_native_bridge_python_executables():
    """Yield installed Python executables other than the current process.

    Inputs: none. Output: yielded values.
    """
    if os.name != "nt":
        return

    import subprocess

    current = _resolve_python_executable_candidate(sys.executable)
    current_key = os.path.normcase(os.path.normpath(current)) if current else ""
    seen = set()
    for launcher in _iter_windows_python_launchers():
        try:
            completed = subprocess.run(
                [launcher, "-0p"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=10,
            )
        except Exception as exc:
            _xt_debug(f"Python launcher probe failed for {launcher}: {exc}")
            continue
        if completed.returncode != 0:
            _xt_debug(
                "Python launcher probe returned "
                f"{completed.returncode} for {launcher}: {completed.stderr[:4000]}"
            )
            continue
        for candidate in _parse_python_launcher_paths(completed.stdout):
            resolved = _resolve_python_executable_candidate(candidate)
            if not resolved:
                continue
            normalized = os.path.normcase(os.path.normpath(resolved))
            if normalized == current_key or normalized in seen:
                continue
            seen.add(normalized)
            yield resolved


def _native_bridge_payload(
    imaris_id,
    mode,
    file_path=None,
    file_paths=None,
    require_ims=True,
):
    """Return the native bridge payload.

    Inputs: `imaris_id`, `mode`, `file_path` file path, `file_paths`,
    `require_ims`. Output: ID value.
    """
    app_id = _coerce_imaris_id(imaris_id)
    if app_id is None:
        _xt_debug("Native bridge runner skipped: missing Imaris application id")
        return None

    payload = {
        "mode": mode,
        "app_id": app_id,
        "install_roots": list(_iter_imaris_install_roots()),
        "retry_attempts": IMARIS_HANDLE_RETRY_ATTEMPTS,
        "retry_interval": IMARIS_HANDLE_RETRY_INTERVAL,
        "open_verify_timeout": IMARIS_OPEN_VERIFY_TIMEOUT,
        "open_verify_interval": IMARIS_OPEN_VERIFY_INTERVAL,
    }
    if file_path is not None:
        payload["file_path"] = str(file_path)
        payload["require_ims"] = bool(require_ims)
    if file_paths is not None:
        payload["file_paths"] = [str(path) for path in file_paths]
        payload["require_ims"] = bool(require_ims)
    return payload


def _write_native_bridge_helper_file():
    """Write the native bridge helper file.

    Inputs: none. Output: `name`.
    """
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".py",
        prefix="omero_imaris_bridge_",
        encoding="utf-8",
        delete=False,
    ) as helper_file:
        helper_file.write(_NATIVE_BRIDGE_OPEN_HELPER)
        return helper_file.name


def _cleanup_native_bridge_helper_file(helper_path):
    """A temporary native bridge helper script.

    Inputs: `helper_path`. Output: None.
    """
    if not helper_path:
        return
    try:
        os.unlink(helper_path)
    except OSError as exc:
        _xt_debug(f"Native bridge helper cleanup failed: {type(exc).__name__}: {exc}")


def _native_bridge_open_action(stdout, payload):
    """Return a log phrase for successful native bridge open output.

    Inputs: `stdout`, `payload` payload. Output: `str`.
    """
    return "completed IMS open request in the current Imaris session"


def _log_native_bridge_stdout(stdout, context, payload):
    """Log sanitized native bridge stdout.

    Inputs: `stdout`, `context`, `payload`. Output: None.
    """
    if not stdout:
        return
    if stdout == "BRIDGE_RUNNER_PROBE_OK":
        _xt_debug(
            f"Native bridge runner ({context}) resolved the current Imaris session"
        )
    elif stdout in {"BRIDGE_RUNNER_OPENED", "BRIDGE_RUNNER_OPENED_MANY"}:
        _xt_debug(
            f"Native bridge runner ({context}) "
            f"{_native_bridge_open_action(stdout, payload)}"
        )
    elif stdout == "BRIDGE_RUNNER_HANDLE_UNAVAILABLE":
        _xt_debug(
            f"Native bridge runner ({context}) could not resolve the current Imaris session"
        )
    elif stdout == "BRIDGE_RUNNER_OPEN_METHOD_UNAVAILABLE":
        _xt_debug(
            f"Native bridge runner ({context}) resolved Imaris but file-open API is unavailable"
        )
    elif stdout in {
        "BRIDGE_RUNNER_INVALID_FILE_LIST",
        "BRIDGE_RUNNER_MISSING_FILE",
        "BRIDGE_RUNNER_INVALID_IMS",
        "BRIDGE_RUNNER_OPEN_FAILED",
        "BRIDGE_RUNNER_OPEN_UNVERIFIED",
    }:
        _xt_debug(f"Native bridge runner ({context}) result: {stdout}")
    elif stdout.startswith("BRIDGE_RUNNER_EXCEPTION:"):
        _xt_debug(f"Native bridge runner ({context}) result: {stdout[:4000]}")
    else:
        _xt_debug(f"Native bridge runner ({context}) stdout: {stdout[:4000]}")


def _log_native_bridge_stderr(stderr, context):
    """Log sanitized native bridge stderr.

    Inputs: `stderr`, `context`. Output: None.
    """
    if not stderr:
        return
    stderr_lines = [
        line
        for line in stderr.splitlines()
        if (
            "communicator not destroyed during global destruction" not in line
            and "communicators not destroyed during global destruction" not in line
        )
    ]
    if stderr_lines:
        _xt_debug(
            f"Native bridge runner ({context}) stderr: "
            f"{os.linesep.join(stderr_lines)[:4000]}"
        )
        return
    _xt_debug(
        f"Native bridge runner ({context}) suppressed benign Ice shutdown warning"
    )


def _run_native_bridge_helper(python_executable, payload, context, timeout):
    """A fixed native bridge helper under a candidate Python executable.

    Inputs: `python_executable`, `payload`, `context`, `timeout`. Output: bool.
    """
    if payload is None:
        return False

    resolved_python = _resolve_python_executable_candidate(python_executable)
    if resolved_python is None:
        return False

    import subprocess

    _xt_debug(f"Trying native Imaris bridge runner ({context}) with {resolved_python}")
    helper_path = None
    try:
        helper_path = _write_native_bridge_helper_file()
        completed = subprocess.run(
            [resolved_python, helper_path],
            check=False,
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _xt_debug(
            f"Native Imaris bridge runner ({context}) timed out after {timeout} seconds"
        )
        return False
    except Exception as exc:
        _xt_debug(
            "Native Imaris bridge runner "
            f"({context}) failed to start: {type(exc).__name__}: {exc}"
        )
        return False
    finally:
        _cleanup_native_bridge_helper_file(helper_path)

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    _log_native_bridge_stdout(stdout, context, payload)
    _log_native_bridge_stderr(stderr, context)
    _xt_debug(f"Native bridge runner ({context}) exit code: {completed.returncode}")
    return completed.returncode == 0


def _run_native_bridge_probe_helper(python_executable, imaris_id):
    """Whether a candidate Python can load ImarisLib and resolve the app.

    Inputs: `python_executable`, `imaris_id`. Output: `_run_native_bridge_helper`
    """
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(imaris_id, "probe"),
        "probe",
        NATIVE_BRIDGE_PROBE_TIMEOUT,
    )


def _run_native_bridge_open_helper(
    python_executable,
    file_path,
    imaris_id,
    require_ims=True,
):
    """Run the native bridge open helper.

    Inputs: `python_executable`, `file_path` file path, `imaris_id`,
    `require_ims`. Output: `_run_native_bridge_helper` result.
    """
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        return False
    if require_ims and not is_ims_file(candidate):
        return False
    if not require_ims:
        return False
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(
            imaris_id,
            "open",
            file_path=candidate,
            require_ims=bool(require_ims),
        ),
        "open",
        NATIVE_BRIDGE_RUNNER_TIMEOUT,
    )


def _run_native_bridge_open_many_helper(
    python_executable,
    file_paths,
    imaris_id,
    require_ims=True,
):
    """Run the native bridge open many helper.

    Inputs: `python_executable`, `file_paths`, `imaris_id`, `require_ims`.
    Output: `_run_native_bridge_helper` result.
    """
    candidates = _existing_regular_file_path_list(file_paths)
    if candidates is None:
        return False
    if require_ims and any(not is_ims_file(candidate) for candidate in candidates):
        return False
    if not require_ims:
        return False
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(
            imaris_id,
            "open",
            file_paths=candidates,
            require_ims=bool(require_ims),
        ),
        "open_many",
        NATIVE_BRIDGE_RUNNER_TIMEOUT,
    )


def _find_compatible_native_bridge_python(imaris_id):
    """Return an installed Python executable that can use Imaris' native bridge.

    Inputs: `imaris_id`. Output: `python_executable` or None.
    """
    if not _native_imaris_bridge_enabled():
        return None
    if _coerce_imaris_id(imaris_id) is None:
        return None
    for python_executable in _iter_native_bridge_python_executables():
        if _run_native_bridge_probe_helper(python_executable, imaris_id):
            return python_executable
    return None


def _open_file_in_imaris_with_native_bridge_runner(
    file_path,
    imaris_id,
    preferred_python_executable=None,
    require_ims=True,
    allow_when_disabled=False,
):
    """Try compatible installed Python runtimes while staying on Imaris file-open APIs.

    Inputs: `file_path`, `imaris_id`, `preferred_python_executable`, `require_ims`,
    `allow_when_disabled`. Output: bool.
    """
    if not allow_when_disabled and not _native_imaris_bridge_enabled():
        return False
    if os.name != "nt":
        return False
    if _coerce_imaris_id(imaris_id) is None:
        _xt_debug("Native bridge runner unavailable: no numeric Imaris application id")
        return False

    attempted = False
    candidates = []
    if preferred_python_executable:
        candidates.append(preferred_python_executable)
    candidates.extend(_iter_native_bridge_python_executables())

    seen = set()
    for python_executable in candidates:
        resolved = _resolve_python_executable_candidate(python_executable)
        if not resolved:
            continue
        normalized = os.path.normcase(os.path.normpath(resolved))
        if normalized in seen:
            continue
        seen.add(normalized)
        attempted = True
        if _run_native_bridge_open_helper(
            resolved,
            file_path,
            imaris_id,
            require_ims=require_ims,
        ):
            return True
    if not attempted:
        _xt_debug("Native bridge runner unavailable: no alternate Python found")
    return False


def _open_files_in_imaris_with_native_bridge_runner(
    file_paths,
    imaris_id,
    preferred_python_executable=None,
    require_ims=True,
    allow_when_disabled=False,
):
    """Try compatible installed Python runtimes while staying on Imaris file-open APIs.

    Inputs: `file_paths`, `imaris_id`, `preferred_python_executable`,
    `require_ims`, `allow_when_disabled`. Output: `bool`.
    """
    if not allow_when_disabled and not _native_imaris_bridge_enabled():
        return False
    if os.name != "nt":
        return False
    if _coerce_imaris_id(imaris_id) is None:
        _xt_debug("Native bridge runner unavailable: no numeric Imaris application id")
        return False

    candidates = _existing_regular_file_path_list(file_paths)
    if candidates is None:
        return False
    if len(candidates) == 1:
        return _open_file_in_imaris_with_native_bridge_runner(
            candidates[0],
            imaris_id,
            preferred_python_executable=preferred_python_executable,
            require_ims=require_ims,
            allow_when_disabled=allow_when_disabled,
        )

    attempted = False
    python_candidates = []
    if preferred_python_executable:
        python_candidates.append(preferred_python_executable)
    python_candidates.extend(_iter_native_bridge_python_executables())

    seen = set()
    for python_executable in python_candidates:
        resolved = _resolve_python_executable_candidate(python_executable)
        if not resolved:
            continue
        normalized = os.path.normcase(os.path.normpath(resolved))
        if normalized in seen:
            continue
        seen.add(normalized)
        attempted = True
        if _run_native_bridge_open_many_helper(
            resolved,
            candidates,
            imaris_id,
            require_ims=require_ims,
        ):
            return True
    if not attempted:
        _xt_debug("Native bridge runner unavailable: no alternate Python found")
    return False


def _prepend_unique_path(values, candidate):
    """Prepend the unique path.

    Inputs: `values`, `candidate`. Output: `bool`.
    """
    normalized = os.path.normpath(candidate)
    if normalized in values:
        return False
    values.insert(0, normalized)
    return True


def _prepare_imaris_xt_environment():
    """Add bundled Imaris XT Python paths and DLL directories so ImarisLib/IcePy can load.

    Inputs: none. Output: dict.
    """
    if os.name != "nt":
        return {"paths": [], "dll_dirs": []}

    path_parts = (
        os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
    )
    added = []
    dll_dirs = []
    add_dll_directory = getattr(os, "add_dll_directory", None)
    for install_root in _iter_imaris_install_roots():
        for candidate in _iter_imaris_xt_path_candidates(install_root):
            if not os.path.isdir(candidate):
                continue
            normalized = os.path.normpath(candidate)
            if normalized not in sys.path:
                sys.path.insert(0, normalized)
                added.append(normalized)
            _prepend_unique_path(path_parts, normalized)
            if callable(add_dll_directory):
                try:
                    handle = add_dll_directory(normalized)
                    _XT_DLL_DIR_HANDLES.append(handle)
                    dll_dirs.append(normalized)
                except Exception:
                    logger.debug("Failed to add DLL directory: %s", normalized)

    if path_parts:
        os.environ["PATH"] = os.pathsep.join(path_parts)
    return {"paths": added, "dll_dirs": dll_dirs}


def _safe_path_exists(path_value):
    """Return safe path exists.

    Inputs: `path_value`. Output: bool.
    """
    try:
        return bool(path_value) and os.path.exists(path_value)
    except Exception:
        return False


def _probe_module_import(module_name):
    """Probe the module import.

    Inputs: `module_name`. Output: `dict`.
    """
    try:
        __import__(module_name)
        return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _probe_loaded_bridge_module_import(module_name):
    """Probe a native bridge module only when it is already loaded.

    Inputs: `module_name`. Output: `dict`.
    """
    if module_name not in sys.modules:
        return {"ok": False, "error": "not loaded; in-process import skipped"}
    return _probe_module_import(module_name)


def _set_process_window_title(title):
    """Best-effort Windows console title update without shelling out.

    Inputs: `title`. Output: `bool`.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        kernel32 = getattr(windll, "kernel32", None)
        set_console_title = getattr(kernel32, "SetConsoleTitleW", None)
        if not callable(set_console_title):
            return False
        return bool(set_console_title(str(title)))
    except Exception:
        return False


def _read_windows_version_via_rtl_get_version():
    """Read the running Windows kernel version through `RtlGetVersion`.

    Inputs: no caller arguments. Output: `_WindowsVersion` or None.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        class _OSVERSIONINFOEXW(ctypes.Structure):
            """Windows OS version structure used by `RtlGetVersion`."""

            _fields_ = [
                ("dwOSVersionInfoSize", ctypes.c_ulong),
                ("dwMajorVersion", ctypes.c_ulong),
                ("dwMinorVersion", ctypes.c_ulong),
                ("dwBuildNumber", ctypes.c_ulong),
                ("dwPlatformId", ctypes.c_ulong),
                ("szCSDVersion", ctypes.c_wchar * 128),
                ("wServicePackMajor", ctypes.c_ushort),
                ("wServicePackMinor", ctypes.c_ushort),
                ("wSuiteMask", ctypes.c_ushort),
                ("wProductType", ctypes.c_ubyte),
                ("wReserved", ctypes.c_ubyte),
            ]

        windll = getattr(ctypes, "windll", None)
        ntdll = getattr(windll, "ntdll", None)
        rtl_get_version = getattr(ntdll, "RtlGetVersion", None)
        if not callable(rtl_get_version):
            return None
        version_info = _OSVERSIONINFOEXW(ctypes.sizeof(_OSVERSIONINFOEXW))
        status = int(rtl_get_version(ctypes.byref(version_info)))
        if status != 0:
            return None
        return _WindowsVersion(
            major=int(version_info.dwMajorVersion),
            minor=int(version_info.dwMinorVersion),
            build=int(version_info.dwBuildNumber),
            source="RtlGetVersion",
        )
    except Exception:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=True
        )
        return None


def _windows_platform_status():
    """Return the startup platform support status for the XT connector.

    Inputs: no caller arguments. Output: `_WindowsPlatformStatus`.
    """
    minimum = f"{MINIMUM_WINDOWS_MAJOR}.{MINIMUM_WINDOWS_MINOR}"
    if os.name != "nt":
        return _WindowsPlatformStatus(
            supported=False,
            message=(
                "OMERO Connector requires Windows 10 or later. "
                "Detected a non-Windows platform."
            ),
        )

    version = _read_windows_version_via_rtl_get_version()
    if version is None:
        return _WindowsPlatformStatus(
            supported=False,
            message=(
                "OMERO Connector requires Windows 10 or later, but the "
                "running Windows version could not be determined reliably."
            ),
        )

    detected_version = f"{version.major}.{version.minor}.{version.build}"
    if (version.major, version.minor) >= (
        MINIMUM_WINDOWS_MAJOR,
        MINIMUM_WINDOWS_MINOR,
    ):
        return _WindowsPlatformStatus(
            supported=True,
            message=(
                f"Detected supported Windows {detected_version} "
                f"via {version.source}; minimum is {minimum}."
            ),
            version=version,
        )
    return _WindowsPlatformStatus(
        supported=False,
        message=(
            "OMERO Connector requires Windows 10 or later. "
            f"Detected Windows {detected_version} via {version.source}; "
            f"minimum is {minimum}."
        ),
        version=version,
    )


def _extract_content_disposition_filename(content_disposition):
    """Extract an HTTP Content-Disposition filename without trusting path parts.

    Inputs: `content_disposition`. Output: `unquote` result.
    """
    header = str(content_disposition or "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", header, flags=re.IGNORECASE)
    if match:
        return urllib.parse.unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="([^"]+)"', header, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"filename=([^;]+)", header, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"')
    return None


def _safe_download_filename(filename, fallback_name, default_extension=None):
    """Return a single safe filename for connector-managed downloads.

    Inputs: `filename`, `fallback_name`, `default_extension`. Output: `safe`.
    """
    fallback = str(fallback_name or "download")
    if default_extension and not fallback.lower().endswith(default_extension.lower()):
        fallback += default_extension

    raw = str(filename or "").replace("\x00", "")
    # Treat both URL and Windows separators as path separators even when tests
    # run on a non-Windows host.
    raw = raw.replace("\\", "/")
    basename = posixpath.basename(raw).strip()
    if not basename:
        basename = fallback

    safe = re.sub(r"[^A-Za-z0-9 ._-]", "_", basename).strip(" .")
    if not safe:
        safe = re.sub(r"[^A-Za-z0-9 ._-]", "_", fallback).strip(" .")
    if not safe:
        safe = "download"

    root_name = os.path.splitext(safe)[0].upper()
    if root_name in _WINDOWS_RESERVED_FILENAMES:
        safe = f"_{safe}"

    if default_extension and not safe.lower().endswith(default_extension.lower()):
        safe += default_extension

    if len(safe) > 180:
        stem, ext = os.path.splitext(safe)
        keep = max(1, 180 - len(ext))
        safe = stem[:keep].rstrip(" .") + ext
    return safe


def _unique_download_path(download_dir, filename):
    """A download path inside download_dir without overwriting locked files.

    Inputs: `download_dir`, `filename`. Output: `Path` or path text. Raises:
    RuntimeError when validation or the called operation fails.
    """
    safe_filename = _safe_download_filename(filename, "download")
    candidate = os.path.join(download_dir, safe_filename)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(safe_filename)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for index in range(1, 1000):
        suffix = f"__{timestamp}" if index == 1 else f"__{timestamp}_{index}"
        candidate = os.path.join(download_dir, f"{stem}{suffix}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("Could not allocate a unique download filename.")


def _download_path_for_policy(download_dir, filename, duplicate_policy=None):
    """Return the final connector download path for the selected duplicate policy.

    Inputs: `download_dir`, `filename`, `duplicate_policy`. Output: local path.
    """
    safe_filename = _safe_download_filename(filename, "download")
    use_unique = duplicate_policy == DUPLICATE_DOWNLOAD_POLICY_UNIQUE
    if duplicate_policy is None:
        use_unique = _unique_download_suffix_enabled()
    if use_unique:
        return _unique_download_path(download_dir, safe_filename)
    return os.path.join(download_dir, safe_filename)


def _raise_if_cancelled(cancel_event, context="Operation"):
    """Raise when a user stop request has been signaled.

    Inputs: optional cancel event and context. Output: None. Raises:
    _ConnectorOperationCancelled.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise _ConnectorOperationCancelled(f"{context} stopped by user.")


def _safe_remove_partial_download(path_value):
    """Remove a partial connector download file after cancellation.

    Inputs: path. Output: None.
    """
    if not path_value:
        return
    try:
        candidate = _coerce_path(path_value)
        if candidate is not None and candidate.is_file():
            candidate.unlink()
    except OSError:
        _xt_debug("Could not remove partial stopped download.")


def _wait_for_cancel_or_timeout(cancel_event, seconds, context="Operation"):
    """Sleep in small increments so a stop request is observed quickly.

    Inputs: optional cancel event, seconds, context. Output: None. Raises:
    _ConnectorOperationCancelled when stopped.
    """
    deadline = time.time() + max(0.0, float(seconds or 0))
    while time.time() < deadline:
        _raise_if_cancelled(cancel_event, context)
        remaining = deadline - time.time()
        time.sleep(min(CANCEL_POLL_INTERVAL, max(0.0, remaining)))
    _raise_if_cancelled(cancel_event, context)


def _header_value_is_safe(value):
    """Return whether an outbound HTTP header value is safe to emit.

    Inputs: header name or value. Output: bool.
    """
    text = str(value or "")
    return "\r" not in text and "\n" not in text


def _socket_wait(
    sock, *, readable=False, writable=False, cancel_event=None, deadline=0
):
    """Wait for a socket readiness state while observing connector cancellation.

    Inputs: socket, readiness flags, optional cancel event, deadline. Output: None.
    Raises: _ConnectorOperationCancelled or socket.timeout.
    """
    while True:
        _raise_if_cancelled(cancel_event, "HTTP request")
        remaining = deadline - time.time()
        if remaining <= 0:
            raise socket.timeout("Timed out waiting for OMERO.web response.")
        wait_time = min(CANCELLABLE_HTTP_POLL_INTERVAL_SECONDS, remaining)
        read_list = [sock] if readable else []
        write_list = [sock] if writable else []
        ready_read, ready_write, _ready_error = select.select(
            read_list,
            write_list,
            [],
            wait_time,
        )
        if (readable and ready_read) or (writable and ready_write):
            return


def _socket_send_all(sock, payload, cancel_event, deadline):
    """Send HTTP request bytes while observing connector cancellation.

    Inputs: socket, payload bytes, cancel event, deadline. Output: None.
    """
    view = memoryview(payload)
    sent = 0
    while sent < len(view):
        _socket_wait(sock, writable=True, cancel_event=cancel_event, deadline=deadline)
        try:
            chunk_sent = sock.send(view[sent:])
        except (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
            continue
        if chunk_sent <= 0:
            raise OSError("Socket closed while sending OMERO.web request.")
        sent += chunk_sent


def _socket_recv(sock, max_bytes, cancel_event, deadline):
    """Receive HTTP response bytes while observing connector cancellation.

    Inputs: socket, max bytes, cancel event, deadline. Output: bytes.
    """
    while True:
        _socket_wait(sock, readable=True, cancel_event=cancel_event, deadline=deadline)
        try:
            return sock.recv(max_bytes)
        except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
            continue


def _close_socket_quietly(sock):
    """Close a socket without surfacing cleanup errors.

    Inputs: socket. Output: None.
    """
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        logger.debug(
            "Suppressed non-fatal socket close failure in XT cancellable HTTP.",
            exc_info=True,
        )


class _CancellableHTTPResponse:
    """Small response wrapper for cancellable OMERO.web downloads."""

    def __init__(
        self,
        sock,
        url,
        status,
        reason,
        headers,
        body_prefix,
        cancel_event,
        timeout,
    ):
        """Create a cancellable HTTP response wrapper.

        Inputs: socket, URL, status, headers, buffered body, cancellation state.
        Output: response object compatible with the download paths.
        """
        self._sock = sock
        self._url = url
        self.status = status
        self.reason = reason
        self.headers = headers
        self._buffer = bytearray(body_prefix or b"")
        self._cancel_event = cancel_event
        self._deadline = time.time() + max(1.0, float(timeout or 1.0))
        self._closed = False
        transfer_encoding = str(headers.get("Transfer-Encoding") or "").lower()
        self._chunked = "chunked" in transfer_encoding
        self._chunk_remaining = 0
        self._chunk_done = False
        content_length = headers.get("Content-Length") or headers.get("content-length")
        try:
            self._remaining = int(content_length) if content_length else None
        except (TypeError, ValueError):
            self._remaining = None

    def __enter__(self):
        """Enter response context.

        Inputs: none. Output: self.
        """
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        """Close response context.

        Inputs: exception context. Output: bool false.
        """
        self.close()
        return False

    def geturl(self):
        """Return the final response URL.

        Inputs: none. Output: URL string.
        """
        return self._url

    def close(self):
        """Close the response socket.

        Inputs: none. Output: None.
        """
        if self._closed:
            return
        self._closed = True
        _close_socket_quietly(self._sock)

    def _read_wire(self, size):
        """Read undecoded bytes from the wire.

        Inputs: byte count. Output: bytes.
        """
        if self._closed:
            return b""
        if self._buffer:
            data = bytes(self._buffer[:size])
            del self._buffer[:size]
            return data
        try:
            data = _socket_recv(self._sock, size, self._cancel_event, self._deadline)
        except _ConnectorOperationCancelled:
            self.close()
            raise
        if not data:
            self.close()
        return data

    def _read_wire_exact(self, size):
        """Read exactly size undecoded bytes unless EOF occurs.

        Inputs: byte count. Output: bytes.
        """
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = self._read_wire(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_wire_line(self):
        """Read one undecoded HTTP line.

        Inputs: none. Output: line bytes including newline when present.
        """
        line = bytearray()
        while True:
            if self._buffer:
                newline_index = self._buffer.find(b"\n")
                if newline_index >= 0:
                    line.extend(self._buffer[: newline_index + 1])
                    del self._buffer[: newline_index + 1]
                    return bytes(line)
                line.extend(self._buffer)
                self._buffer.clear()
            chunk = self._read_wire(1)
            if not chunk:
                return bytes(line)
            line.extend(chunk)
            if chunk == b"\n":
                return bytes(line)

    def _read_plain(self, size):
        """Read a non-chunked response body.

        Inputs: requested size. Output: bytes.
        """
        if self._remaining == 0:
            return b""
        if size is None or size < 0:
            chunks = []
            while self._remaining != 0:
                next_size = (
                    min(DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES, self._remaining)
                    if self._remaining is not None
                    else DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES
                )
                chunk = self._read_plain(next_size)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        read_size = int(size)
        if self._remaining is not None:
            read_size = min(read_size, self._remaining)
        if read_size <= 0:
            return b""
        data = self._read_wire(read_size)
        if self._remaining is not None:
            self._remaining = max(0, self._remaining - len(data))
        return data

    def _consume_chunk_trailers(self):
        """Consume chunked-response trailers.

        Inputs: none. Output: None.
        """
        while True:
            line = self._read_wire_line()
            if line in {b"", b"\r\n", b"\n"}:
                return

    def _read_chunked(self, size):
        """Read a chunked response body and return decoded bytes.

        Inputs: requested size. Output: decoded bytes.
        """
        if self._chunk_done:
            return b""
        if size is None or size < 0:
            chunks = []
            while True:
                chunk = self._read_chunked(DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)

        wanted = int(size)
        if wanted <= 0:
            return b""
        output = bytearray()
        while len(output) < wanted and not self._chunk_done:
            if self._chunk_remaining <= 0:
                line = self._read_wire_line()
                if not line:
                    self._chunk_done = True
                    break
                chunk_size_text = line.split(b";", 1)[0].strip()
                try:
                    self._chunk_remaining = int(chunk_size_text, 16)
                except ValueError as exc:
                    raise http.client.HTTPException(
                        "Invalid chunked response from OMERO.web."
                    ) from exc
                if self._chunk_remaining == 0:
                    self._consume_chunk_trailers()
                    self._chunk_done = True
                    break

            next_size = min(wanted - len(output), self._chunk_remaining)
            chunk = self._read_wire_exact(next_size)
            if not chunk:
                self._chunk_done = True
                break
            output.extend(chunk)
            self._chunk_remaining -= len(chunk)
            if self._chunk_remaining == 0:
                self._read_wire_exact(2)
        return bytes(output)

    def read(self, size=-1):
        """Read response body bytes.

        Inputs: optional size. Output: bytes.
        """
        _raise_if_cancelled(self._cancel_event, "HTTP response")
        if self._chunked:
            return self._read_chunked(size)
        return self._read_plain(size)


def _collect_imaris_xt_diagnostics():
    """Collect imaris XT diagnostics.

    Inputs: none. Output: dict.
    """
    native_bridge_enabled = _native_imaris_bridge_enabled()
    saved_settings = _load_connector_settings()
    exe_path = _find_imaris_executable()
    file_converter_path = _find_imaris_file_converter_executable()
    install_roots = list(_iter_imaris_install_roots())
    xt_paths = []
    for install_root in install_roots:
        xt_paths.extend(_iter_imaris_xt_path_candidates(install_root))
    deduped_xt_paths = []
    seen = set()
    for candidate in xt_paths:
        normalized = os.path.normpath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped_xt_paths.append(normalized)

    python_version_short = ".".join(str(part) for part in sys.version_info[:3])
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "python_version_short": python_version_short,
        "imaris_exe_env": os.environ.get("IMARIS_EXE", ""),
        "imaris_exe_settings": _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_IMARIS_EXE_KEY
        ),
        "imaris_home_env": os.environ.get("IMARIS_HOME", ""),
        "imaris_executable": exe_path or "",
        "imaris_executable_exists": _safe_path_exists(exe_path),
        "imaris_file_converter": file_converter_path or "",
        "imaris_file_converter_exists": (
            bool(file_converter_path) and _safe_path_exists(file_converter_path)
        ),
        "install_roots": install_roots,
        "xt_candidate_paths": [
            {"path": candidate, "exists": _safe_path_exists(candidate)}
            for candidate in deduped_xt_paths
        ],
        "has_add_dll_directory": callable(getattr(os, "add_dll_directory", None)),
        "native_bridge_enabled": native_bridge_enabled,
        "imarislib_import": (
            _probe_loaded_bridge_module_import("ImarisLib")
            if native_bridge_enabled
            else {"ok": False, "error": ""}
        ),
        "icepy_import": (
            _probe_loaded_bridge_module_import("IcePy")
            if native_bridge_enabled
            else {"ok": False, "error": ""}
        ),
    }


def _log_imaris_xt_diagnostics():
    """Write environment diagnostics for the Imaris XT startup path.

    Inputs: configured runtime state. Output: writes diagnostics and returns None.
    """
    diagnostics = _collect_imaris_xt_diagnostics()
    _xt_debug(
        "XT diagnostics: "
        f"python_executable={diagnostics['python_executable']} "
        f"python_version={diagnostics['python_version_short']} "
        f"imaris_exe={diagnostics['imaris_executable'] or '<not found>'} "
        f"imaris_exe_exists={diagnostics['imaris_executable_exists']} "
        "imaris_file_converter="
        f"{diagnostics['imaris_file_converter'] or '<not found>'} "
        "imaris_file_converter_exists="
        f"{diagnostics['imaris_file_converter_exists']}"
    )
    _xt_debug(
        "XT diagnostics env: "
        f"IMARIS_HOME={diagnostics['imaris_home_env'] or '<unset>'} "
        f"IMARIS_EXE={diagnostics['imaris_exe_env'] or '<unset>'} "
        "settings_IMARIS_EXE="
        f"{diagnostics['imaris_exe_settings'] or '<unset>'}"
    )
    for install_root in diagnostics["install_roots"]:
        _xt_debug(f"XT diagnostics install_root={install_root}")
    for entry in diagnostics["xt_candidate_paths"]:
        _xt_debug(f"XT diagnostics path={entry['path']} exists={entry['exists']}")
    if diagnostics["native_bridge_enabled"]:
        _xt_debug(
            "XT diagnostics imports: "
            f"has_add_dll_directory={diagnostics['has_add_dll_directory']} "
            f"ImarisLib_ok={diagnostics['imarislib_import']['ok']} "
            f"ImarisLib_error={diagnostics['imarislib_import']['error'] or '<none>'} "
            f"IcePy_ok={diagnostics['icepy_import']['ok']} "
            f"IcePy_error={diagnostics['icepy_import']['error'] or '<none>'}"
        )


def _coerce_imaris_id(aImarisId):
    """Coerce imaris ID.

    Inputs: `aImarisId`. Output: `aImarisId`.
    """
    if aImarisId is None or _looks_like_imaris_application(aImarisId):
        return None
    if isinstance(aImarisId, int):
        return aImarisId
    try:
        text_value = str(aImarisId).strip()
    except Exception:
        text_value = ""
    if text_value.isdigit():
        try:
            return int(text_value)
        except Exception:
            return None
    try:
        return int(aImarisId)
    except Exception:
        return None


def _resolve_imaris_application(
    aImarisId,
    retries=1,
    retry_interval=IMARIS_HANDLE_RETRY_INTERVAL,
):
    """Resolve an Imaris application handle from an ID with bounded retries.

    Inputs: `aImarisId`, `retries`, `retry_interval`. Output: `aImarisId`.
    """
    if _looks_like_imaris_application(aImarisId):
        return aImarisId

    app_id = _coerce_imaris_id(aImarisId)
    if app_id is None:
        return None

    attempts = max(1, int(retries or 1))
    for attempt in range(attempts):
        try:
            ImarisLib = sys.modules.get("ImarisLib")
            if ImarisLib is None:
                if _native_imaris_bridge_enabled():
                    _xt_debug(
                        "Direct in-process ImarisLib import skipped because the "
                        "module is not already loaded; using the compatible native "
                        "bridge runner for numeric XT application ids."
                    )
                else:
                    _xt_debug(
                        "Direct in-process ImarisLib import skipped because the "
                        "module is not already loaded."
                    )
                return None

            lib_factory = getattr(ImarisLib, "ImarisLib", None)
            if callable(lib_factory):
                lib = lib_factory()
                get_application = getattr(lib, "GetApplication", None)
                if callable(get_application):
                    app = get_application(app_id)
                    if app is not None:
                        return app

            get_application = getattr(ImarisLib, "GetApplication", None)
            if callable(get_application):
                app = get_application(app_id)
                if app is not None:
                    return app
        except Exception as exc:
            _log_direct_imaris_resolution_failure(exc)
            break

        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(retry_interval)))

    return None


def _log_direct_imaris_resolution_failure(exc):
    """Log direct Imaris handle resolution failure without disabled IcePy noise.

    Inputs: `exc`. Output: None.
    """
    version_info = ".".join(str(part) for part in sys.version_info[:3])
    if not _native_imaris_bridge_enabled():
        _xt_debug(
            "Direct Imaris XT handle is unavailable in this Python. "
            f"Current Python={version_info}."
        )
        return
    _xt_debug(
        "Direct Imaris XT bridge is unavailable in this Python: "
        f"{exc}. Current Python={version_info}. "
        "The connector will use the compatible native bridge runner if available."
    )


# =============================================================================
# OMERO WEB CLIENT
# =============================================================================


class OMEROWebClient:
    """Client for OMERO.web API."""

    def __init__(self, host, port, username, password, scheme="http"):
        """Create `OMEROWebClient` with `host`, `port`, `username`, `password`, and `scheme`.

        Inputs: `host`, `port`, `username`, `password`, `scheme`. Output: None.
        """
        self.base_url = self._build_base_url(host, port, scheme)
        self.api_url = f"{self.base_url}/api/v0"
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.session = None
        self.scheme = scheme
        # Initialize cookie/session attributes
        self.cookie_jar = None
        self.opener: Any = None
        self.csrf_token = None
        self.session_id = None
        self.session_key = None
        self.user_id = None

    @staticmethod
    def _build_base_url(host, port, scheme):
        """Build the base URL for `OMEROWebClient`.

        Inputs: `host`, `port`, `scheme`. Output: URL string.
        """
        safe_scheme = str(scheme or "").strip().lower()
        if safe_scheme not in {"http", "https"}:
            raise ValueError("Unsupported OMERO.web URL scheme.")
        safe_port = _parse_port(port)
        if safe_port is None:
            raise ValueError("Invalid OMERO.web port.")
        safe_host = _normalized_omero_web_host_for_url(host)
        return f"{safe_scheme}://{safe_host}:{safe_port}"

    def _create_request_with_cookies(self, url, data=None, method=None):
        """Create the request with cookies for `OMEROWebClient`.

        Inputs: `url` URL, `data` payload, `method`. Output: `req`.
        """
        req = urllib.request.Request(url, data=data, method=method)

        # Add CSRF token header for POST requests
        if method == "POST" or data is not None:
            if self.csrf_token:
                req.add_header("X-CSRFToken", self.csrf_token)
            req.add_header("Referer", self.base_url)

        # Add common headers to prevent caching issues
        req.add_header("Cache-Control", "no-cache")
        req.add_header("Pragma", "no-cache")
        req.add_header("User-Agent", "OMERO-ImarisXT/1.0")

        return req

    def _cookie_header_for_url(self, url):
        """Return the cookie header that urllib would attach for URL.

        Inputs: URL. Output: Cookie header or empty string.
        """
        if not self.cookie_jar:
            return ""
        cookie_request = urllib.request.Request(url)
        try:
            self.cookie_jar.add_cookie_header(cookie_request)
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
            return ""
        return cookie_request.get_header("Cookie") or ""

    @staticmethod
    def _host_header_for_url(parsed_url):
        """Return a Host header value for parsed URL.

        Inputs: parsed URL. Output: host header.
        """
        host = parsed_url.hostname or ""
        port = parsed_url.port
        default_port = 443 if parsed_url.scheme == "https" else 80
        if port and port != default_port:
            return f"{host}:{port}"
        return host

    def _open_cancellable_http_request(self, req, timeout, cancel_event):
        """Open a request with a socket that can be closed by Stop.

        Inputs: urllib request, timeout, cancel event. Output: response object.
        Raises: urllib errors or _ConnectorOperationCancelled.
        """
        method = str(req.get_method() or "GET").upper()
        if method != "GET":
            return self.opener.open(req, timeout=timeout)

        parsed = urllib.parse.urlparse(req.full_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return self.opener.open(req, timeout=timeout)

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.params:
            path = f"{path};{parsed.params}"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = None
        deadline = time.time() + max(1.0, float(timeout or 1.0))
        try:
            _raise_if_cancelled(cancel_event, "HTTP request")
            sock = socket.create_connection(
                (parsed.hostname, port),
                timeout=CANCELLABLE_HTTP_CONNECT_TIMEOUT_SECONDS,
            )
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                sock = context.wrap_socket(sock, server_hostname=parsed.hostname)
            sock.setblocking(False)

            request_headers = {
                "Host": self._host_header_for_url(parsed),
                "Connection": "close",
            }
            for key, value in req.header_items():
                if _header_value_is_safe(key) and _header_value_is_safe(value):
                    request_headers[str(key)] = str(value)
            cookie_header = req.get_header("Cookie") or self._cookie_header_for_url(
                req.full_url
            )
            if cookie_header and _header_value_is_safe(cookie_header):
                request_headers["Cookie"] = cookie_header

            request_lines = [f"{method} {path} HTTP/1.1"]
            request_lines.extend(
                f"{key}: {value}" for key, value in request_headers.items()
            )
            request_payload = ("\r\n".join(request_lines) + "\r\n\r\n").encode(
                "iso-8859-1"
            )
            _socket_send_all(sock, request_payload, cancel_event, deadline)

            raw_response = bytearray()
            while b"\r\n\r\n" not in raw_response:
                _raise_if_cancelled(cancel_event, "HTTP request")
                if len(raw_response) > CANCELLABLE_HTTP_MAX_HEADER_BYTES:
                    raise http.client.HTTPException(
                        "OMERO.web response headers were too large."
                    )
                chunk = _socket_recv(sock, 65536, cancel_event, deadline)
                if not chunk:
                    break
                raw_response.extend(chunk)

            header_bytes, separator, body_prefix = bytes(raw_response).partition(
                b"\r\n\r\n"
            )
            if not separator:
                raise http.client.HTTPException(
                    "OMERO.web closed the response before sending headers."
                )
            header_lines = header_bytes.split(b"\r\n")
            status_line = header_lines[0].decode("iso-8859-1", errors="replace")
            status_parts = status_line.split(" ", 2)
            if len(status_parts) < 2 or not status_parts[1].isdigit():
                raise http.client.HTTPException(
                    f"Invalid OMERO.web status line: {status_line}"
                )
            status = int(status_parts[1])
            reason = status_parts[2] if len(status_parts) > 2 else ""
            headers_payload = b"\r\n".join(header_lines[1:]) + b"\r\n\r\n"
            response_headers = http.client.parse_headers(io.BytesIO(headers_payload))
            response = _CancellableHTTPResponse(
                sock,
                req.full_url,
                status,
                reason,
                response_headers,
                body_prefix,
                cancel_event,
                timeout,
            )
            sock = None
            if status >= 400:
                raise urllib.error.HTTPError(
                    req.full_url,
                    status,
                    reason,
                    response_headers,
                    cast(BinaryIO, response),
                )
            return response
        except _ConnectorOperationCancelled:
            _close_socket_quietly(sock)
            raise
        except OSError as exc:
            _close_socket_quietly(sock)
            raise urllib.error.URLError(exc) from exc

    def _open_request_response(self, req, timeout, cancel_event=None):
        """Open a urllib request, using cancellable sockets for live GETs.

        Inputs: request, timeout, optional cancel event. Output: response object.
        """
        if cancel_event is None or not isinstance(
            self.opener,
            urllib.request.OpenerDirector,
        ):
            return self.opener.open(req, timeout=timeout)
        return self._open_cancellable_http_request(req, timeout, cancel_event)

    @staticmethod
    def _build_direct_opener(cookie_jar):
        """Build an OMERO.web opener that ignores process proxy settings.

        Inputs: `cookie_jar`. Output: urllib opener.
        """
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(cookie_jar),
        )

    def _extract_cookies_from_jar(self):
        """Extract session and CSRF cookies from the cookie jar.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if not self.cookie_jar:
            return

        for cookie in self.cookie_jar:
            if cookie.name == "sessionid":
                self.session_id = cookie.value
                self.session_key = cookie.value
                _xt_debug("Extracted sessionid cookie")
            elif cookie.name == "csrftoken":
                self.csrf_token = cookie.value
                _xt_debug("Extracted csrftoken cookie")

    @staticmethod
    def _check_login_redirect(response, context="request"):
        """Verify login redirect for `OMEROWebClient`.

        Inputs: `response` response object, `context`. Output: `bool`.
        """
        final_url = getattr(response, "geturl", lambda: "")()
        redirect_location = ""
        headers = getattr(response, "headers", None)
        if headers is not None:
            redirect_location = headers.get("Location") or ""
        if "/webclient/login/" in str(final_url) or "/webclient/login/" in str(
            redirect_location
        ):
            _xt_debug(
                "Authentication failed during "
                f"{context}: redirected to "
                f"{_safe_url_for_log(redirect_location or final_url)}"
            )
            return True
        return False

    @staticmethod
    def _looks_like_login_page(raw_body):
        """Best-effort detection for HTML login content returned with 200.

        Inputs: `raw_body`. Output: bool.
        """
        if not raw_body:
            return False
        try:
            text = raw_body[:4096].decode("utf-8", errors="ignore").lower()
        except Exception:
            return False
        return (
            "csrfmiddlewaretoken" in text
            and 'name="username"' in text
            and "/webclient/login/" in text
        )

    @staticmethod
    def _extract_event_context_user_id(payload):
        """Return the current OMERO experimenter id from an API login payload.

        Inputs: decoded login payload. Output: user id or None.
        """
        if not isinstance(payload, dict):
            return None
        event_context = payload.get("eventContext")
        if not isinstance(event_context, dict):
            return None
        user_id = event_context.get("userId")
        if user_id is None:
            return None
        try:
            return int(user_id)
        except (TypeError, ValueError):
            return None

    def _refresh_current_user_context(self, password):
        """Record the authenticated OMERO user id from the documented JSON API.

        Inputs: current login password. Output: bool.
        """
        if not password or not self.csrf_token:
            return False
        login_url = f"{self.api_url}/login/"
        data = urllib.parse.urlencode(
            {
                "username": self.username,
                "password": password,
                "server": 1,
                "csrfmiddlewaretoken": self.csrf_token,
            }
        ).encode()
        req = self._create_request_with_cookies(login_url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            response = self.opener.open(req, timeout=30)
            raw_body = response.read()
            self._extract_cookies_from_jar()
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            _xt_debug(
                f"Current OMERO user context lookup failed: {type(exc).__name__}: {exc}"
            )
            return False
        user_id = self._extract_event_context_user_id(payload)
        if user_id is None:
            _xt_debug("Current OMERO user context lookup returned no user id")
            return False
        self.user_id = user_id
        return True

    @staticmethod
    def _with_all_groups(endpoint):
        """Return an API endpoint that queries all groups accessible to the user.

        Inputs: `endpoint`. Output: endpoint with the all-groups query flag.
        """
        if "group=" in endpoint:
            return endpoint
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}group=-1"

    @staticmethod
    def _project_endpoint(include_collaboration_projects, user_id=None):
        """Return the project endpoint for the requested collaboration scope.

        Inputs: `include_collaboration_projects`, `user_id`. Output: API endpoint.
        """
        endpoint = "m/projects/"
        if include_collaboration_projects:
            return OMEROWebClient._with_all_groups(endpoint)
        try:
            owner_id = int(user_id)
        except (TypeError, ValueError):
            raise RuntimeError(
                "Cannot restrict projects to the current OMERO user because the "
                "session did not report a user id."
            ) from None
        return f"{endpoint}?owner={owner_id}&group=-1"

    def _extract_items(self, payload, collection_keys=None):
        """Extract list payloads from common API response wrappers.

        Inputs: `payload` payload, `collection_keys`. Output: `list`.
        """
        if collection_keys is None:
            collection_keys = ("data", "results", "items", "objects")
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        for key in collection_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = self._extract_items(value, collection_keys=collection_keys)
                if nested:
                    return nested
        return []

    @staticmethod
    def _build_named_entities(rows, default_prefix):
        """API rows into [{'id': ..., 'name': ...}] objects.

        Inputs: `rows`, `default_prefix`. Output: `out`.
        """
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entity_id = (
                row.get("@id") or row.get("id") or row.get("Id") or row.get("ID")
            )
            if entity_id is None:
                continue
            name = (
                row.get("Name")
                or row.get("name")
                or row.get("label")
                or f"{default_prefix} {entity_id}"
            )
            out.append({"id": entity_id, "name": name})
        return out

    def _attempt_reauth(self, context):
        """Attempt to re-authenticate and return True on success.

        Inputs: `context`. Output: bool.
        """
        if not self.password:
            _xt_debug(
                f"Re-authentication skipped during {context}: password is not retained"
            )
            return False
        _xt_debug(f"Attempting to re-authenticate during {context}")
        # Clear existing session
        self.session_id = None
        self.csrf_token = None
        self.session_key = None

        if self.connect():
            _xt_debug("Re-authentication succeeded.")
            return True
        _xt_debug("Re-authentication failed.")
        return False

    def reauthenticate(self, context):
        """Attempt to re-authenticate through the public client API.

        Inputs: `context`. Output: `self._attempt_reauth` result.
        """
        return self._attempt_reauth(context)

    def connect(self):
        """Authenticate with OMERO.web.

        Inputs: none. Output: bool.
        """
        password = self.password
        if not password:
            _xt_debug("Login failed: password is not available for authentication")
            return False
        try:
            # Create fresh cookie jar
            self.cookie_jar = http.cookiejar.CookieJar()
            self.opener = self._build_direct_opener(self.cookie_jar)

            login_url = f"{self.base_url}/webclient/login/"
            _xt_debug(
                f"Connecting to OMERO.web login endpoint {_safe_url_for_log(login_url)}"
            )

            # First GET to obtain CSRF token
            req = urllib.request.Request(login_url)
            req.add_header("User-Agent", "OMERO-ImarisXT/1.0")
            response = self.opener.open(req, timeout=30)
            _xt_debug(f"Login GET response={getattr(response, 'status', 'unknown')}")

            # Extract CSRF token from cookies
            self._extract_cookies_from_jar()

            if not self.csrf_token:
                _xt_debug("Login failed: CSRF token missing after GET")
                return False

            # POST login credentials
            pre_auth_session = self.session_id
            data = urllib.parse.urlencode(
                {
                    "username": self.username,
                    "password": password,
                    "server": 1,
                    "csrfmiddlewaretoken": self.csrf_token,
                }
            ).encode()

            req = urllib.request.Request(login_url, data=data, method="POST")
            req.add_header("Referer", login_url)
            req.add_header("X-CSRFToken", self.csrf_token)
            req.add_header("User-Agent", "OMERO-ImarisXT/1.0")

            response = self.opener.open(req, timeout=30)
            _xt_debug(f"Login POST response={getattr(response, 'status', 'unknown')}")
            raw_body = response.read()
            post_url = getattr(response, "geturl", lambda: "")()
            if post_url:
                _xt_debug(f"Login POST final endpoint={_safe_url_for_log(post_url)}")

            # Extract session cookie from response
            self._extract_cookies_from_jar()

            if self._check_login_redirect(
                response, "login POST"
            ) or self._looks_like_login_page(raw_body):
                _xt_debug("Login failed: still on login page after POST")
                return False

            if not self.session_id:
                _xt_debug("Login failed: session cookie missing after POST")
                return False

            self._refresh_current_user_context(password)

            if pre_auth_session and self.session_id == pre_auth_session:
                _xt_debug("Login warning: session cookie unchanged after POST")

            # Verify authenticated JSON API access; do not require actual project data.
            probe = self._api_request(self._with_all_groups("m/projects/?limit=1"))
            if probe is None:
                _xt_debug("Login failed: authenticated API probe did not return JSON")
                return False

            _xt_debug("Login succeeded; session cookie received")
            return True

        except urllib.error.HTTPError as e:
            _xt_debug(f"Login HTTP error {e.code}: {e.reason}")
            return False
        except urllib.error.URLError as e:
            _xt_debug(f"Login URL error: {e}")
            return False
        except Exception as e:
            _xt_debug(f"Connection error: {e}")
            return False
        finally:
            self.password = CLEARED_CREDENTIAL_TEXT

    @staticmethod
    def _api_auth_failure(raise_on_error):
        """Raise the standard API authentication failure when requested.

        Inputs: `raise_on_error`. Output: None. Raises: RuntimeError when validation or
        external operations fail.
        """
        if raise_on_error:
            raise RuntimeError("Not authenticated to OMERO.web. Please connect again.")

    @staticmethod
    def _should_retry_transient(attempt, attempts, retry_transient, error):
        """Return whether a transient request failure should be retried.

        Inputs: `attempt`, `attempts`, `retry_transient`, `error`. Output: bool.
        """
        return (
            attempt < attempts
            and retry_transient
            and _is_transient_network_error(error)
        )

    def _api_request_once(self, url, *, timeout, raise_on_error):
        """Perform one OMERO.web API GET and decode JSON.

        Inputs: `url`, `timeout`, `raise_on_error`. Output: `json.loads` result or None.
        """
        req = self._create_request_with_cookies(url)
        response = self.opener.open(req, timeout=timeout)
        if self._check_login_redirect(response, "API request"):
            self._api_auth_failure(raise_on_error)
            return None
        _xt_debug(f"API GET response={getattr(response, 'status', 'unknown')}")
        content_type = (response.headers.get("Content-Type") or "").lower()
        raw = response.read()
        if "text/html" in content_type and self._looks_like_login_page(raw):
            _xt_debug("API request returned login HTML instead of JSON")
            self._api_auth_failure(raise_on_error)
            return None
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _api_error_result(error, *, raise_on_error):
        """Return or raise the standard API error result.

        Inputs: `error`, `raise_on_error`. Output: None. Raises: RuntimeError when validation or
        the called operation fails.
        """
        if isinstance(error, json.JSONDecodeError):
            _xt_debug(f"API error: invalid JSON response ({error})")
            if raise_on_error:
                raise RuntimeError(
                    "OMERO.web returned an invalid JSON response."
                ) from error
            return None
        if isinstance(error, urllib.error.HTTPError):
            _xt_debug(f"API error ({error.code}): {error.reason}")
            if raise_on_error:
                raise RuntimeError(
                    f"OMERO.web API request failed: HTTP {error.code}."
                ) from error
            return None
        _xt_debug(f"API error: {error}")
        if raise_on_error:
            raise RuntimeError(f"OMERO.web API request failed: {error}") from error
        return None

    def _api_request(
        self,
        endpoint,
        *,
        timeout=30,
        raise_on_error=False,
        retry_transient=False,
    ):
        """Make API request with explicit cookie handling.

        Inputs: `endpoint`, `timeout` timeout seconds, `raise_on_error`,
        `retry_transient`. Output: `_api_request_once` result.
        """
        if not self.session_id:
            _xt_debug("API request skipped: no session")
            self._api_auth_failure(raise_on_error)
            return None

        url = f"{self.api_url}/{endpoint}"
        _xt_debug(f"API GET endpoint={_safe_url_for_log(url)}")
        attempts = _http_retry_attempts() if retry_transient else 1
        delay = _http_retry_delay_seconds()

        for attempt in range(1, attempts + 1):
            try:
                return self._api_request_once(
                    url,
                    timeout=timeout,
                    raise_on_error=raise_on_error,
                )
            except Exception as exc:
                if self._should_retry_transient(
                    attempt, attempts, retry_transient, exc
                ):
                    _xt_debug(
                        "API request transient failure "
                        f"(attempt {attempt}/{attempts}): {exc}"
                    )
                    time.sleep(delay)
                    continue
                return self._api_error_result(exc, raise_on_error=raise_on_error)

        return None

    def _api_post(self, endpoint, payload=None):
        """POST JSON to OMERO.web API with explicit cookie handling.

        Inputs: `endpoint`, `payload`. Output: `json.loads` result or None.
        """
        if not self.session_id:
            _xt_debug("API POST skipped: no session")
            return None

        url = f"{self.api_url}/{endpoint}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = self._create_request_with_cookies(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            response = self.opener.open(req, timeout=30)

            if self._check_login_redirect(response, "API POST"):
                return None

            _xt_debug(
                "API POST endpoint="
                f"{_safe_url_for_log(url)} response={getattr(response, 'status', 'unknown')}"
            )
            raw = response.read()
            if not raw:
                return None
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return None
        except urllib.error.HTTPError as e:
            _xt_debug(f"API POST error ({e.code}): {e.reason}")
            try:
                body_length = len(e.read())
                _xt_debug(f"API POST error body omitted length={body_length}")
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            return None
        except Exception as e:
            _xt_debug(f"API POST error: {e}")
            return None

    @staticmethod
    def _payload_error_message(payload, raw_text, default_message):
        """Return the payload error message for `OMEROWebClient`.

        Inputs: `payload` payload, `raw_text`, `default_message`. Output:
        `default_message`.
        """
        if isinstance(payload, dict):
            for key in ("error", "detail", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(raw_text, str):
            normalized = " ".join(raw_text.strip().split())
            lowered = normalized.lower()
            if (
                normalized
                and len(normalized) <= 500
                and not any(
                    marker in lowered
                    for marker in ("<html", "<!doctype", "<body", "<head", "<title")
                )
            ):
                return normalized
        return default_message

    @staticmethod
    def _json_request_data(payload, raw_data, content_type):
        """Return request body bytes and content type for JSON URL requests.

        Inputs: `payload`, `raw_data`, `content_type`. Output: tuple.
        """
        data = raw_data
        if data is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
            if content_type is None:
                content_type = "application/json"
        return data, content_type

    @staticmethod
    def _decode_json_response(raw_body):
        """Decode optional JSON response body.

        Inputs: `raw_body`. Output: tuple.
        """
        raw_text = raw_body.decode("utf-8", errors="replace") if raw_body else ""
        decoded = None
        if raw_text.strip():
            try:
                decoded = json.loads(raw_text)
            except json.JSONDecodeError:
                decoded = None
        return decoded, raw_text

    def _open_json_request_once(
        self,
        url,
        *,
        request_method,
        data,
        content_type,
        headers,
        timeout,
        context,
    ):
        """Open the JSON request once for `OMEROWebClient`.

        Inputs: `url` URL, `request_method`, `data` payload, `content_type`, `headers`,
        `timeout` timeout seconds, `context`. Output: `tuple`. Raises: RuntimeError when
        validation or the called operation fails.
        """
        req = self._create_request_with_cookies(url, data=data, method=request_method)
        if content_type:
            req.add_header("Content-Type", content_type)
        for key, value in list((headers or {}).items()):
            req.add_header(key, value)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                if self._check_login_redirect(response, context):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web. Please connect again."
                    )
                raw_body = response.read()
                if self._looks_like_login_page(raw_body):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web. Please connect again."
                    )
                return getattr(response, "status", 200), raw_body
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            except Exception:
                return exc.code, b""

    def _request_json_url(
        self,
        url,
        *,
        method=None,
        payload=None,
        raw_data=None,
        content_type=None,
        headers=None,
        timeout=30,
        context="request",
        retry_transient=False,
    ):
        """Request the JSON URL for `OMEROWebClient`.

        Inputs: `url` URL, `method`, `payload` payload, `raw_data` raw payload,
        `content_type`, `headers`, `timeout` timeout seconds, `context`,
        `retry_transient`. Output: `tuple`. Raises: RuntimeError when validation or
        external operations fail.
        """
        if not self.session_id:
            raise RuntimeError("Not authenticated to OMERO.web. Please connect again.")

        data, content_type = self._json_request_data(payload, raw_data, content_type)
        request_method = method or ("POST" if data is not None else "GET")
        attempts = _http_retry_attempts() if retry_transient else 1
        delay = _http_retry_delay_seconds()
        for attempt in range(1, attempts + 1):
            try:
                status_code, raw_body = self._open_json_request_once(
                    url,
                    request_method=request_method,
                    data=data,
                    content_type=content_type,
                    headers=headers,
                    timeout=timeout,
                    context=context,
                )
                decoded, raw_text = self._decode_json_response(raw_body)
                return status_code, decoded, raw_text
            except Exception as exc:
                if self._should_retry_transient(
                    attempt, attempts, retry_transient, exc
                ):
                    _xt_debug(
                        f"{context} transient failure "
                        f"(attempt {attempt}/{attempts}): {exc}"
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"{context} failed: {exc}") from exc

        raise RuntimeError(f"{context} failed after {attempts} attempts")

    def get_image_metadata(self, image_id):
        """Return image metadata.

        Inputs: `image_id` OMERO image ID. Output: metadata mapping.
        """
        data = self._api_request(self._with_all_groups(f"m/images/{image_id}/"))
        if not data:
            return {}

        result = {
            "id": image_id,
            "name": data.get("Name") or data.get("name") or "",
        }
        return result

    def list_scripts(self):
        """Return the scripts for `OMEROWebClient`.

        Inputs: none. Output: `list`.
        """
        data = self._api_request("scripts/")
        if data and isinstance(data, dict):
            scripts = data.get("data") or data.get("scripts") or []
            if isinstance(scripts, dict):
                scripts = scripts.get("data") or scripts.get("scripts") or []
            return scripts
        return []

    def find_script_id(self, script_name):
        """Find the script ID for `OMEROWebClient`.

        Inputs: `script_name`. Output: `sid`.
        """
        scripts_list = self.list_scripts()
        normalized_name = os.path.splitext(script_name)[0]
        for item in scripts_list:
            name = item.get("name") or item.get("Name") or item.get("scriptName")
            path = item.get("path") or item.get("Path")
            sid = item.get("id") or item.get("@id")
            if not sid:
                continue
            if script_name in (name, path):
                return sid
            if name and os.path.basename(name) == script_name:
                return sid
            if path and os.path.basename(path) == script_name:
                return sid
            if normalized_name:
                if (
                    name
                    and os.path.splitext(os.path.basename(name))[0] == normalized_name
                ):
                    return sid
                if (
                    path
                    and os.path.splitext(os.path.basename(path))[0] == normalized_name
                ):
                    return sid
        return None

    def run_script(self, script_id, inputs):
        """A script with.

        Inputs: `script_id`, `inputs`. Output: `response` or None.
        """
        payloads = [
            {"inputs": inputs},
            {"inputs": {key: {"value": value} for key, value in inputs.items()}},
        ]
        for payload in payloads:
            response = self._api_post(f"scripts/{script_id}/run/", payload)
            if response:
                return response
        return None

    def has_omero_ims_export_capability(self, *, log_unavailable=False):
        """Return True when this OMERO.web instance exposes server-side IMS export.

        Inputs: optional `log_unavailable`. Output: `available`.
        """
        if not self.session_id:
            return False
        base = self.base_url.rstrip("/")
        capability_url = f"{base}/omero_imaris_connector/imaris-export/?capabilities=1"
        req = self._create_request_with_cookies(capability_url)
        try:
            with self.opener.open(req, timeout=30) as response:
                if self._check_login_redirect(
                    response, "OMERO converter capability check"
                ):
                    return False
                raw_body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw_body)
        except urllib.error.HTTPError as exc:
            if log_unavailable:
                _xt_debug(
                    "OMERO converter: custom server-side capability not advertised "
                    f"(HTTP {exc.code})"
                )
            return False
        except Exception as exc:
            if log_unavailable:
                _xt_debug(
                    "OMERO converter: custom server-side capability probe failed: "
                    f"{type(exc).__name__}"
                )
            return False
        if not isinstance(payload, dict):
            if log_unavailable:
                _xt_debug(
                    "OMERO converter: custom server-side capability response was "
                    "not an object"
                )
            return False
        capability_flag = payload.get(OMERO_IMS_EXPORT_CAPABILITY_KEY)
        if capability_flag != OMERO_IMS_EXPORT_CAPABILITY_FLAG:
            if log_unavailable:
                _xt_debug(
                    "OMERO converter: custom server-side capability flag is missing "
                    "or unsupported"
                )
            return False
        converters = payload.get("converters")
        converter_available = (
            isinstance(converters, dict) and converters.get("OMERO") is True
        )
        available = payload.get("omero_ims_export") is True and converter_available
        if available:
            _xt_debug("OMERO converter: custom server-side IMS export is available")
        elif log_unavailable:
            _xt_debug("OMERO converter: custom server-side IMS export is disabled")
        return available

    def get_folder_export_capability(self):
        """Detect whether OMERO.web exposes the folder export workflow.

        Inputs: none. Output: dict.
        """
        if not self.session_id:
            return {
                "available": False,
                "reason": "Not authenticated to OMERO.web.",
            }

        capability_url = f"{self.base_url.rstrip('/')}/omeroweb_import/start/"
        _xt_debug(
            "Checking OMERO folder export capability endpoint="
            f"{_safe_url_for_log(capability_url)}"
        )
        try:
            status_code, payload, raw_text = self._request_json_url(
                capability_url,
                method="POST",
                payload={},
                timeout=30,
                context="folder export capability check",
            )
        except Exception as exc:
            _xt_debug(f"OMERO folder export capability unavailable: {exc}")
            return {"available": False, "reason": str(exc)}

        message = self._payload_error_message(
            payload,
            raw_text,
            f"HTTP {status_code}",
        )
        lowered = message.lower()
        if message == "No files provided.":
            _xt_debug("OMERO folder export capability available=True")
            return {"available": True, "reason": ""}
        if "please login as regular user" in lowered:
            _xt_debug(
                "OMERO folder export capability unavailable: regular user required"
            )
            return {
                "available": False,
                "reason": "Folder export is unavailable for the OMERO root user.",
            }
        if isinstance(payload, dict) and payload.get("ok") is False and message:
            _xt_debug(f"OMERO folder export capability unavailable: {message}")
            return {"available": False, "reason": message}

        _xt_debug(
            "OMERO folder export capability unavailable: "
            f"unexpected status={status_code}"
        )
        return {
            "available": False,
            "reason": "Folder export is not available on this OMERO.web instance.",
        }

    def start_folder_export_job(self, dataset_name, file_entries):
        """Start the server-side job for the folder export workflow.

        Inputs: `dataset_name`, `file_entries`. Output: start folder export job result.
        Raises: RuntimeError when validation or the called operation fails.
        """
        if not isinstance(dataset_name, str) or not dataset_name.strip():
            raise RuntimeError("The selected folder name is invalid.")
        files = []
        for entry in list(file_entries or []):
            if not isinstance(entry, dict):
                continue
            relative_path = str(entry.get("relative_path") or "").strip()
            if not relative_path:
                continue
            try:
                size = int(entry.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            size = max(size, 0)
            files.append({"relative_path": relative_path, "size": size})
        if not files:
            raise RuntimeError("The selected folder does not contain any files.")

        start_url = f"{self.base_url.rstrip('/')}/omeroweb_import/start/"
        _xt_debug(
            "Starting OMERO folder export job via endpoint="
            f"{_safe_url_for_log(start_url)}"
        )
        client_upload_id = uuid.uuid4().hex
        status_code, payload, raw_text = self._request_json_url(
            start_url,
            method="POST",
            payload={
                "client_upload_id": client_upload_id,
                "files": files,
                "dataset_name_override": dataset_name.strip(),
                "compatibility_enabled": True,
            },
            timeout=60,
            context="folder export start",
            retry_transient=True,
        )
        if (
            status_code >= 400
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError(
                self._payload_error_message(
                    payload,
                    raw_text,
                    "Failed to start OMERO folder export.",
                )
            )

        for key in (
            "upload_url",
            "import_step_url",
            "status_url",
            "confirm_url",
            "prune_url",
        ):
            if payload.get(key):
                payload[key] = self._normalize_url(payload[key], self.base_url)
        return payload

    def upload_folder_chunk(
        self,
        upload_url,
        relative_path,
        file_size,
        chunk_start,
        chunk_bytes,
        is_last_chunk,
    ):
        """Upload the folder chunk for `OMEROWebClient`.

        Inputs: `upload_url`, `relative_path`, `file_size`, `chunk_start`,
        `chunk_bytes`, `is_last_chunk`. Output: chunk payload or size. Raises:
        RuntimeError when validation or the called operation fails.
        """
        if not upload_url:
            raise RuntimeError("The OMERO upload URL is missing.")
        safe_relative_path = str(relative_path or "").strip()
        if not safe_relative_path:
            raise RuntimeError("A folder export file path is missing.")
        boundary, body = _multipart_form_body(
            {
                "upload_mode": "chunked",
                "relative_path": safe_relative_path,
                "chunk_start": int(chunk_start),
                "chunk_end": int(chunk_start) + len(chunk_bytes or b""),
                "file_size": int(file_size),
                "is_last_chunk": "1" if is_last_chunk else "0",
                "chunk_sha256": hashlib.sha256(chunk_bytes or b"").hexdigest(),
            },
            "file",
            os.path.basename(safe_relative_path) or "upload.bin",
            chunk_bytes or b"",
        )
        status_code, payload, raw_text = self._request_json_url(
            upload_url,
            method="POST",
            raw_data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=EXPORT_TIMEOUT + 60,
            context="folder export chunk upload",
            retry_transient=True,
        )
        if (
            status_code >= 400
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError(
                self._payload_error_message(
                    payload,
                    raw_text,
                    "Failed to upload a folder chunk to OMERO.",
                )
            )
        return payload

    def trigger_folder_export(self, import_step_url):
        """Trigger the server-side step for the folder export workflow.

        Inputs: `import_step_url`. Output: trigger folder export result. Raises:
        RuntimeError when validation or the called operation fails.
        """
        if not import_step_url:
            raise RuntimeError("The OMERO folder export step URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            import_step_url,
            method="POST",
            payload={},
            timeout=60,
            context="folder export trigger",
        )
        if (
            status_code >= 400
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError(
                self._payload_error_message(
                    payload,
                    raw_text,
                    "Failed to start the OMERO folder export.",
                )
            )
        return payload

    def confirm_folder_export(self, confirm_url):
        """Confirm the folder export workflow for `OMEROWebClient`.

        Inputs: `confirm_url`. Output: confirm folder export result. Raises:
        RuntimeError when validation or the called operation fails.
        """
        if not confirm_url:
            raise RuntimeError("The OMERO confirmation URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            confirm_url,
            method="POST",
            payload={},
            timeout=60,
            context="folder export confirmation",
        )
        if (
            status_code >= 400
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError(
                self._payload_error_message(
                    payload,
                    raw_text,
                    "Failed to confirm the OMERO folder export.",
                )
            )
        return payload

    def get_folder_export_status(self, status_url):
        """Return folder export status.

        Inputs: `status_url`. Output: status value. Raises: RuntimeError when validation or the
        called operation fails.
        """
        if not status_url:
            raise RuntimeError("The OMERO status URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            status_url,
            method="GET",
            timeout=30,
            context="folder export status poll",
        )
        if (
            status_code >= 400
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError(
                self._payload_error_message(
                    payload,
                    raw_text,
                    "Failed to poll the OMERO folder export status.",
                )
            )
        return payload

    def cancel_folder_export_job(self, job_payload):
        """Best-effort cancellation for a folder export upload/import job.

        Inputs: job payload. Output: bool indicating whether a cancel request was sent.
        """
        if not isinstance(job_payload, dict):
            return False
        prune_url = job_payload.get("prune_url")
        if prune_url:
            prune_url = self._normalize_url(prune_url, self.base_url)
            try:
                status_code, payload, raw_text = self._request_json_url(
                    prune_url,
                    method="POST",
                    payload={"keep_paths": []},
                    timeout=30,
                    context="folder export cancellation",
                )
                if status_code < 400 and isinstance(payload, dict):
                    _xt_debug(
                        "Folder export server-side staged files pruned after stop"
                    )
                    return True
                _xt_debug(
                    "Folder export cancel prune returned "
                    f"status={status_code} body_length={len(raw_text or '')}"
                )
            except Exception as exc:
                _xt_debug(f"Folder export cancel prune failed: {type(exc).__name__}")
        return False

    def poll_activity(self, job_id, timeout=900, interval=2):
        """Poll a script activity until completion.

        Inputs: `job_id`, `timeout`, `interval`. Output: `data` or None.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._api_request(f"activities/{job_id}/")
            if not data:
                return None

            status = (data.get("status") or data.get("state") or "").upper()
            if status in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                return data
            if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                return data

            time.sleep(interval)

        return None

    def cancel_ims_export(self, cancel_url):
        """Cancel a server-side OMERO IMS export job.

        Inputs: cancel URL. Output: bool indicating whether cancel was accepted.
        """
        if not cancel_url:
            return False
        cancel_url = self._normalize_url(cancel_url, self.base_url)
        try:
            status_code, payload, raw_text = self._request_json_url(
                cancel_url,
                method="POST",
                payload={"cancel": True},
                timeout=30,
                context="OMERO converter IMS export cancellation",
            )
            if (
                status_code < 400
                and isinstance(payload, dict)
                and payload.get("cancelled") is True
            ):
                _xt_debug("OMERO converter: server-side IMS export stopped")
                return True
            _xt_debug(
                "OMERO converter: cancel returned "
                f"status={status_code} body_length={len(raw_text or '')}"
            )
        except Exception as exc:
            _xt_debug(
                f"OMERO converter: cancel request failed {type(exc).__name__}: {exc}"
            )
        return False

    def ping(self, timeout=10):
        """That the authenticated OMERO.web session still answers.

        Inputs: `timeout`. Output: bool.
        """
        data = self._api_request(
            self._with_all_groups("m/projects/?limit=1"),
            timeout=timeout,
            raise_on_error=True,
        )
        return data is not None

    def list_projects(
        self,
        *,
        timeout=30,
        raise_on_error=False,
        retry_transient=False,
        include_collaboration_projects=True,
    ):
        """Return the projects for `OMEROWebClient`.

        Inputs: `timeout` timeout seconds, `raise_on_error`, `retry_transient`,
        `include_collaboration_projects`. Output: `_build_named_entities` result.
        """
        data = self._api_request(
            self._project_endpoint(include_collaboration_projects, self.user_id),
            timeout=timeout,
            raise_on_error=raise_on_error,
            retry_transient=retry_transient,
        )
        if not data:
            return []
        projects = self._extract_items(
            data,
            collection_keys=("data", "projects", "results", "items", "objects"),
        )
        return self._build_named_entities(projects, default_prefix="Project")

    def list_datasets(
        self,
        project_id,
        *,
        timeout=30,
        raise_on_error=False,
        retry_transient=False,
    ):
        """Return the datasets for `OMEROWebClient`.

        Inputs: `project_id` OMERO project ID, `timeout` timeout seconds,
        `raise_on_error`, `retry_transient`. Output: `_build_named_entities` result.
        """
        data = self._api_request(
            self._with_all_groups(f"m/projects/{project_id}/datasets/"),
            timeout=timeout,
            raise_on_error=raise_on_error,
            retry_transient=retry_transient,
        )
        datasets = self._extract_items(
            data,
            collection_keys=("data", "datasets", "results", "items", "objects"),
        )
        if datasets:
            return self._build_named_entities(datasets, default_prefix="Dataset")

        data = self._api_request(
            self._with_all_groups(f"m/projects/{project_id}/"),
            timeout=timeout,
            raise_on_error=raise_on_error,
            retry_transient=retry_transient,
        )
        if not data:
            return []

        details = data.get("data") if isinstance(data, dict) else None
        if not isinstance(details, dict):
            details = data if isinstance(data, dict) else {}
        datasets = (
            details.get("Datasets")
            or details.get("datasets")
            or self._extract_items(details, collection_keys=("data", "datasets"))
        )
        return self._build_named_entities(datasets, default_prefix="Dataset")

    def list_images(
        self,
        dataset_id,
        *,
        timeout=30,
        raise_on_error=False,
        retry_transient=False,
    ):
        """Return the images for `OMEROWebClient`.

        Inputs: `dataset_id` OMERO dataset ID, `timeout` timeout seconds,
        `raise_on_error`, `retry_transient`. Output: `out`.
        """
        data = self._api_request(
            self._with_all_groups(f"m/datasets/{dataset_id}/images/"),
            timeout=timeout,
            raise_on_error=raise_on_error,
            retry_transient=retry_transient,
        )
        if not data:
            return []
        images = self._extract_items(
            data,
            collection_keys=("data", "images", "results", "items", "objects"),
        )
        out = []
        for img in images:
            if not isinstance(img, dict):
                continue
            image_id = img.get("@id") or img.get("id")
            if image_id is None:
                continue
            pixels = img.get("Pixels") or img.get("pixels") or {}
            item = {
                "id": image_id,
                "name": img.get("Name") or img.get("name") or f"Image {image_id}",
                "sizeX": pixels.get("SizeX", pixels.get("sizeX", 0)),
                "sizeY": pixels.get("SizeY", pixels.get("sizeY", 0)),
                "sizeZ": pixels.get("SizeZ", pixels.get("sizeZ", 1)),
                "sizeC": pixels.get("SizeC", pixels.get("sizeC", 1)),
                "sizeT": pixels.get("SizeT", pixels.get("sizeT", 1)),
            }
            out.append(item)
        return out

    def download_ims_export(
        self,
        image_id,
        download_dir,
        fallback_name="export.ims",
        target_filename=None,
        duplicate_policy=None,
        cancel_event=None,
    ):
        """Download an Imaris .ims export for a given image_id.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`,
        `target_filename`, `duplicate_policy`. Output: `local_path`. Raises:
        RuntimeError when validation or the called operation fails.
        """
        _raise_if_cancelled(cancel_event, "OMERO converter IMS export")
        if download_dir is None:
            download_dir = os.path.join(tempfile.gettempdir(), "ImarisOMEROExports")
            os.makedirs(download_dir, exist_ok=True)
        elif not os.path.isdir(download_dir):
            raise RuntimeError(
                "Download directory does not exist. Please select or type an existing "
                "folder that Imaris can write to."
            )

        # Ensure logged in
        if not self.session_id:
            raise RuntimeError("Not logged in to OMERO.web (missing session key).")

        base = self.base_url.rstrip("/")
        query_params = {
            "image": int(image_id),
            "async": 1,
            "base_url": base,
        }

        encoded_query = urllib.parse.urlencode(query_params)
        export_url = f"{base}/omero_imaris_connector/imaris-export/?{encoded_query}"
        _xt_debug(
            "OMERO converter: requesting custom IMS export endpoint="
            f"{_safe_url_for_log(export_url)}"
        )

        # Create request with explicit cookies
        req = self._create_request_with_cookies(export_url)
        status_url = None
        local_path = None

        try:
            _raise_if_cancelled(cancel_event, "OMERO converter IMS export")
            with self._open_request_response(
                req,
                timeout=30,
                cancel_event=cancel_event,
            ) as response:
                if self._check_login_redirect(
                    response, "OMERO converter IMS export request"
                ):
                    if not self._attempt_reauth("OMERO converter IMS export request"):
                        raise RuntimeError(
                            "Not authenticated to OMERO.web (redirected to login). "
                            "Please login again."
                        )
                    return self.download_ims_export(
                        image_id,
                        download_dir,
                        fallback_name=fallback_name,
                        target_filename=target_filename,
                        duplicate_policy=duplicate_policy,
                        cancel_event=cancel_event,
                    )

                raw_body = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "OMERO converter IMS export failed: server returned a non-JSON response. "
                        "Please verify the OMERO.web Imaris connector is healthy."
                    ) from exc

                job_id = payload.get("job_id")
                status_url = payload.get("status_url")
                if not job_id or not status_url:
                    raise RuntimeError(
                        f"Unexpected OMERO converter response from server: {payload}"
                    )

                status_url = self._normalize_url(status_url, base)
                _xt_debug(
                    "OMERO converter: IMS export started; polling endpoint="
                    f"{_safe_url_for_log(status_url)}"
                )

            # Poll for completion
            deadline = time.time() + EXPORT_TIMEOUT
            download_url = None
            last_state = None
            poll_count = 0
            reauth_attempted = False

            while time.time() < deadline:
                _raise_if_cancelled(cancel_event, "OMERO converter IMS export")
                poll_count += 1
                _xt_debug(
                    f"OMERO converter: IMS export poll #{poll_count} endpoint="
                    f"{_safe_url_for_log(status_url)}"
                )

                # Create poll request with explicit cookies
                poll_req = self._create_request_with_cookies(status_url)

                try:
                    with self._open_request_response(
                        poll_req,
                        timeout=30,
                        cancel_event=cancel_event,
                    ) as poll_response:
                        if self._check_login_redirect(
                            poll_response, "OMERO converter IMS export poll"
                        ):
                            # Try to re-extract cookies in case they were updated
                            self._extract_cookies_from_jar()
                            _xt_debug(
                                "Session state after redirect: "
                                f"sessionid_present={bool(self.session_id)}"
                            )
                            if not reauth_attempted:
                                reauth_attempted = True
                                if self._attempt_reauth(
                                    "OMERO converter IMS export poll"
                                ):
                                    continue
                            raise RuntimeError(
                                "Not authenticated to OMERO.web (redirected to login) "
                                "while polling OMERO converter IMS export. "
                                "Session may have expired. Please try again."
                            )

                        poll_body = poll_response.read().decode(
                            "utf-8", errors="replace"
                        )
                        try:
                            poll_payload = json.loads(poll_body)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                "OMERO converter IMS export poll failed: server returned a non-JSON response. "
                                "Please verify the OMERO.web Imaris connector is healthy."
                            ) from exc

                except urllib.error.HTTPError as e:
                    if e.code in (401, 403):
                        if not reauth_attempted:
                            reauth_attempted = True
                            if self._attempt_reauth(
                                "OMERO converter IMS export poll HTTP error"
                            ):
                                continue
                        raise RuntimeError(
                            f"Authentication error ({e.code}) while polling OMERO "
                            "converter IMS export. "
                            "Session may have expired. Please try again."
                        )
                    raise

                last_state = poll_payload.get("state")
                _xt_debug(
                    "OMERO converter: IMS export poll state="
                    f"{last_state} finished={bool(poll_payload.get('finished'))} "
                    f"failed={bool(poll_payload.get('failed'))} "
                    f"status={poll_payload.get('status') or '<unset>'}"
                )

                if poll_payload.get("failed"):
                    error_msg = poll_payload.get("error", "unknown error")
                    raise RuntimeError(
                        f"OMERO converter IMS export failed: {error_msg}"
                    )

                if poll_payload.get("finished"):
                    download_url = poll_payload.get("download_url")
                    if download_url:
                        download_url = self._normalize_url(download_url, base)
                    break

                _wait_for_cancel_or_timeout(
                    cancel_event,
                    EXPORT_POLL_INTERVAL,
                    "OMERO converter IMS export",
                )

            if not download_url:
                raise RuntimeError(
                    f"OMERO converter IMS export timed out (last state: {last_state})"
                )

            # Download the file
            _raise_if_cancelled(cancel_event, "OMERO converter IMS export")
            _xt_debug(
                "OMERO converter: downloading IMS endpoint="
                f"{_safe_url_for_log(download_url)}"
            )
            download_req = self._create_request_with_cookies(download_url)

            with self._open_request_response(
                download_req,
                timeout=EXPORT_TIMEOUT + 60,
                cancel_event=cancel_event,
            ) as response:
                if self._check_login_redirect(
                    response, "OMERO converter IMS export download"
                ):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web (redirected to login) "
                        "while downloading OMERO converter IMS export."
                    )

                cd = response.headers.get("Content-Disposition", "")
                filename = _extract_content_disposition_filename(cd)
                safe_filename = _safe_download_filename(
                    target_filename or filename,
                    fallback_name,
                    default_extension=".ims",
                )
                local_path = _download_path_for_policy(
                    download_dir,
                    safe_filename,
                    duplicate_policy,
                )

                total_size = int(response.headers.get("content-length", 0) or 0)
                downloaded = 0
                chunk_size = _download_chunk_size_bytes()

                _xt_debug(
                    "OMERO converter: downloading IMS to selected local connector path"
                )
                with open(local_path, "wb") as f:
                    while True:
                        _raise_if_cancelled(
                            cancel_event,
                            "OMERO converter IMS export download",
                        )
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            progress_mb = downloaded / DOWNLOAD_PROGRESS_UNIT_BYTES
                            _xt_console_log(
                                f"  Progress: {percent:.1f}% ({progress_mb:.1f} MB)",
                                end="\r",
                                flush=True,
                            )

                if total_size:
                    _xt_console_log()

            _raise_if_cancelled(cancel_event, "OMERO converter IMS export download")
            if not os.path.exists(local_path):
                raise RuntimeError(
                    f"Download completed but file not found at {local_path}"
                )
            if os.path.getsize(local_path) <= 0:
                raise RuntimeError("Downloaded IMS file is empty")
            if not is_ims_file(local_path):
                raise RuntimeError(
                    "Downloaded IMS export is not a valid IMS (HDF5) file."
                )

            _xt_debug("OMERO converter: IMS export downloaded OK")
            return local_path

        except _ConnectorOperationCancelled:
            self.cancel_ims_export(status_url)
            _safe_remove_partial_download(local_path)
            raise
        except urllib.error.HTTPError as e:
            try:
                body_length = len(e.read())
            except Exception as exc:
                body_length = 0
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            _xt_debug(
                "OMERO converter: IMS export HTTP error body omitted "
                f"length={body_length}"
            )
            raise RuntimeError(
                f"OMERO converter IMS export HTTPError {e.code}: {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"OMERO converter IMS export failed (URLError): {e}"
            ) from e

    def download_selected_image_ome_tiff(
        self,
        image_id,
        download_dir,
        fallback_name="image.ome.tif",
        target_filename=None,
        duplicate_policy=None,
        cancel_event=None,
    ):
        """Download a standard OMERO.web OME-TIFF export for one Image ID.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`,
        `target_filename`, `duplicate_policy`. Output: local OME-TIFF path. Raises:
        RuntimeError when validation or export fails.
        """
        _raise_if_cancelled(cancel_event, "Imaris converter selected Image export")
        if download_dir is None:
            download_dir = os.path.join(tempfile.gettempdir(), "ImarisOMEROExports")
            os.makedirs(download_dir, exist_ok=True)
        elif not os.path.isdir(download_dir):
            raise RuntimeError(
                "Download directory does not exist. Please select or type an existing "
                "folder that Imaris can write to."
            )
        if not self.session_id:
            raise RuntimeError("Not logged in to OMERO.web (missing session key).")

        base = self.base_url.rstrip("/")
        export_url = f"{base}/webgateway/render_ome_tiff/i/{int(image_id)}/"
        _xt_debug(
            "Imaris converter: requesting selected Image OME-TIFF export endpoint="
            f"{_safe_url_for_log(export_url)}"
        )
        req = self._create_request_with_cookies(export_url)
        local_path = None

        try:
            _raise_if_cancelled(cancel_event, "Imaris converter selected Image export")
            with self._open_request_response(
                req,
                timeout=EXPORT_TIMEOUT + 60,
                cancel_event=cancel_event,
            ) as response:
                if self._check_login_redirect(
                    response, "Imaris converter selected Image OME-TIFF export"
                ):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web while exporting selected Image "
                        "as OME-TIFF."
                    )

                status = getattr(response, "status", 200)
                if 300 <= int(status or 0) < 400:
                    location = response.headers.get("Location") or ""
                    if "/webclient/login/" in location:
                        raise RuntimeError(
                            "Not authenticated to OMERO.web while exporting selected "
                            "Image as OME-TIFF."
                        )
                    raise RuntimeError(
                        "OMERO.web redirected instead of returning an OME-TIFF export "
                        "for the selected Image ID."
                    )

                content_type = (response.headers.get("Content-Type") or "").lower()
                if "text/html" in content_type:
                    raw_body = response.read(4096)
                    if self._looks_like_login_page(raw_body):
                        raise RuntimeError(
                            "Not authenticated to OMERO.web while exporting selected "
                            "Image as OME-TIFF."
                        )
                    raise RuntimeError(
                        "OMERO.web returned HTML instead of an OME-TIFF export for "
                        "the selected Image ID."
                    )

                cd = response.headers.get("Content-Disposition", "")
                filename = _extract_content_disposition_filename(cd)
                safe_filename = _safe_download_filename(
                    target_filename or filename,
                    fallback_name,
                )
                if os.path.splitext(safe_filename)[1].lower() not in {
                    ".tif",
                    ".tiff",
                    ".tf8",
                }:
                    safe_filename = f"{safe_filename}.ome.tif"
                local_path = _download_path_for_policy(
                    download_dir,
                    safe_filename,
                    duplicate_policy,
                )
                total_size = int(response.headers.get("content-length", 0) or 0)
                downloaded = 0
                chunk_size = _download_chunk_size_bytes()

                _xt_debug(
                    "Imaris converter: downloading selected Image OME-TIFF export"
                )
                with open(local_path, "wb") as f:
                    while True:
                        _raise_if_cancelled(
                            cancel_event,
                            "Imaris converter selected Image download",
                        )
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            progress_mb = downloaded / DOWNLOAD_PROGRESS_UNIT_BYTES
                            _xt_console_log(
                                f"  Progress: {percent:.1f}% ({progress_mb:.1f} MB)",
                                end="\r",
                                flush=True,
                            )

                if total_size:
                    _xt_console_log()

            _raise_if_cancelled(
                cancel_event, "Imaris converter selected Image download"
            )
            if not os.path.exists(local_path):
                raise RuntimeError(
                    f"Download completed but file not found at {local_path}"
                )
            if os.path.getsize(local_path) <= 0:
                raise RuntimeError("Selected Image OME-TIFF export is empty")
            if not is_tiff_file(local_path):
                raise RuntimeError(
                    "Selected Image OME-TIFF export is not a readable TIFF file."
                )

            _xt_debug("Imaris converter: selected Image OME-TIFF export downloaded OK")
            return local_path
        except _ConnectorOperationCancelled:
            _safe_remove_partial_download(local_path)
            raise
        except urllib.error.HTTPError as e:
            try:
                body_length = len(e.read())
            except Exception as exc:
                body_length = 0
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            _xt_debug(
                "Imaris converter: selected Image OME-TIFF export HTTP error body omitted "
                f"length={body_length}"
            )
            if e.code == 404:
                raise RuntimeError(
                    "OMERO.web did not export an OME-TIFF for the selected Image ID. "
                    "No archived original file was downloaded."
                ) from e
            raise RuntimeError(
                f"Selected Image OME-TIFF export HTTPError {e.code}: {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Selected Image OME-TIFF export failed (URLError): {e}"
            ) from e

    @staticmethod
    def _normalize_url(url, base_url):
        """Normalize the URL for `OMEROWebClient`.

        Inputs: `url` URL, `base_url` base URL. Output: URL string.
        """
        if not url:
            return url

        parsed = urllib.parse.urlparse(url)
        base_parsed = urllib.parse.urlparse(base_url)

        # If URL has scheme and netloc
        if parsed.scheme and parsed.netloc:
            # Always rebuild to use base_url's scheme and netloc
            # This handles cases where server returns localhost, Docker hostname, etc.
            if (
                parsed.netloc != base_parsed.netloc
                or parsed.scheme != base_parsed.scheme
            ):
                rebuilt = urllib.parse.urlunparse(
                    (
                        base_parsed.scheme,
                        base_parsed.netloc,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )
                _xt_debug(
                    "Normalized OMERO.web endpoint "
                    f"{_safe_url_for_log(url)} -> {_safe_url_for_log(rebuilt)}"
                )
                return rebuilt
            return url

        # Relative URL - join with base
        result = urllib.parse.urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
        return result


class OMEROBrowserDialog:
    """UI dialog for browsing OMERO data and loading IMS into Imaris."""

    def __init__(self, imaris, imaris_id=None):
        """Create `OMEROBrowserDialog` with `imaris` and `imaris_id`.

        Inputs: `imaris`, `imaris_id`. Output: None.
        """
        self.imaris = imaris
        self.imaris_id = imaris_id
        self.client: Any = None
        self._all_projects_data = []
        self._all_datasets_data = []
        self._all_images_data = []
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
        self.temp_files = []
        self._selected_image_export_files = set()
        self._pid = None
        self._did = None
        self._refresh_generation = 0
        self._refresh_in_progress = False
        self._native_bridge_probe_lock = threading.Lock()
        self._native_bridge_probe_done = threading.Event()
        self._native_bridge_probe_started = False
        self._native_bridge_probe_in_progress = False
        self._native_bridge_available = _imaris_application_handle_is_live(self.imaris)
        self._native_bridge_python_executable = None
        self._native_bridge_probe_error = ""
        self._native_bridge_last_verified_at = (
            time.time() if self._native_bridge_available else 0.0
        )
        self._connected = False
        self._connection_in_progress = False
        self._folder_export_available = False
        self._folder_export_reason = "Connect to OMERO first."
        self._folder_export_in_progress = False
        self._operation_cancel_event = threading.Event()
        self._operation_generation = 0
        self._active_folder_export_job = None
        self._folder_export_initial_path_hint_consumed = False
        self._last_folder_export_selection = ""
        self._load_in_progress = False
        self._image_selection_anchor = None
        self._health_ping_generation = 0
        self._health_ping_in_progress = False
        self._health_ping_after_id: Optional[str] = None
        self._browser_panel_fractions = tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)
        self._browser_panel_layout_widths = None
        self._browser_sash_drag_index = None
        self._indicator_state = "disconnected"
        self._indicator_blink_on = False
        self._indicator_after_id: Optional[str] = None
        self._password_reveal_after_id: Optional[str] = None
        self._password_revealed = False
        self.folder_path_var: Any
        self.folder_path_entry: Any
        self.select_folder_btn: Any
        self.autosave_settings_var: Any
        self.autosave_settings_check: Any
        self.show_log_var: Any
        self.show_log_check: Any
        self.search_function_var: Any
        self.search_function_check: Any
        self.collaboration_projects_var: Any
        self.collaboration_projects_check: Any
        self.append_observed_folders_var: Any
        self.append_observed_folders_check: Any
        self._browser_search_frames = {}
        self._browser_search_entries = {}
        self._browser_search_vars = {}
        self._browser_search_placeholder_visible = {}
        self._browser_search_trace_suppressed = set()
        self._modal_background_lock_depth = 0
        self._modal_background_cursor_restore = []
        self._modal_background_window_disabled = False
        self._folder_path_placeholder_visible = False
        self._folder_path_trace_suppressed = False
        self._folder_path_trace_id = None
        self._folder_path_write_state = "empty"
        self._folder_path_dir_check_generation = 0
        self._folder_path_dir_check_value = ""
        self._folder_path_dir_check_is_dir = False
        self._settings_file_path = None
        self._saved_settings = {}
        self._autosave_settings_write_error = ""
        self._preferred_converter_setting = ""
        self._available_converter_options = ()
        try:
            self._settings_file_path = _connector_settings_env_path()
            _prepare_connector_settings_for_current_version(self._settings_file_path)
            _ensure_connector_settings_imaris_executable(self._settings_file_path)
            self._saved_settings = _load_connector_settings(self._settings_file_path)
        except OSError as exc:
            self._autosave_settings_write_error = str(exc)
            _log_connector_settings_event(
                f"Connector settings load failed: {type(exc).__name__}"
            )

        # Get export directory
        self.export_dir = self._get_export_dir()

        _ensure_tk_loaded()
        self.root = tk.Tk()
        self._ui_thread_id = threading.get_ident()
        self.root.title("OMERO Connector")
        self._window_icon_image = _apply_omero_window_icon(self.root)
        self.root.geometry(
            f"{OMERO_CONNECTOR_WINDOW_WIDTH}x{OMERO_CONNECTOR_WINDOW_HEIGHT}"
        )
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._configure_initial_window_constraints()
        self._start_native_bridge_probe()

    def _on_close(self):
        """Handle close event.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._request_stop_current_operation()
        self._cancel_password_reveal_timer()
        self._cancel_health_ping()
        self._cancel_indicator_blink()
        self.root.destroy()

    @staticmethod
    def _connection_label(parent, text):
        """Return a start-aligned label for the connection settings grid.

        Inputs: `parent`, `text`. Output: Tk label.
        """
        return tk.Label(
            parent,
            text=text,
            anchor=_tk_constant("W", "w"),
            justify=_tk_constant("LEFT", "left"),
            width=CONNECTION_LABEL_WIDTH,
        )

    def _build_ui(self):
        # Connection frame
        """Build the ui for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        conn_frame = tk.LabelFrame(
            self.root, text="OMERO connection & settings", padx=10, pady=10
        )
        conn_frame.pack(fill=tk.X, padx=10, pady=10)

        saved_settings = getattr(self, "_saved_settings", {})
        default_host = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_HOST_KEY
        ) or (
            os.environ.get("OMERO_WEB_HOST")
            or os.environ.get("OMERO_HOST")
            or os.environ.get("OMEROHOST")
            or ""
        )
        default_port = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_PORT_KEY
        ) or (
            os.environ.get("OMERO_WEB_PORT")
            or os.environ.get("OMERO_WEB_PUBLIC_PORT")
            or os.environ.get("OMERO_PORT")
            or ""
        )
        default_user = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_USERNAME_KEY
        ) or (os.environ.get("OMERO_USER") or os.environ.get("OMERO_USERNAME") or "")
        default_https = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_HTTPS_KEY), False
        )
        default_folder_path = ""
        default_converter = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_CONVERTER_KEY
        )
        default_autosave_settings = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_AUTOSAVE_KEY), True
        )
        default_show_log = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_SHOW_LOG_KEY), True
        )
        default_search_function = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY), False
        )
        default_collaboration_projects = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_COLLABORATION_PROJECTS_KEY),
            False,
        )
        default_append_observed_folders = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY),
            False,
        )

        self.host_label = self._connection_label(conn_frame, "Host:")
        self.host_label.grid(
            row=0, column=0, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.host_entry = tk.Entry(conn_frame, width=25)
        self.host_entry.insert(0, default_host)
        self.host_entry.grid(row=0, column=1, pady=5, padx=5)

        self._connection_label(conn_frame, "Port:").grid(
            row=0, column=2, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        port_validate_command = None
        register = getattr(self.root, "register", None)
        if callable(register):
            port_validate_command = (register(_valid_port_entry_text), "%P")
        port_entry_options: Any = {"width": 8}
        if port_validate_command is not None:
            port_entry_options.update(
                {"validate": "key", "validatecommand": port_validate_command}
            )
        self.port_entry = tk.Entry(conn_frame, **port_entry_options)
        self.port_entry.insert(0, default_port)
        self.port_entry.grid(row=0, column=3, pady=5, padx=5, sticky=tk.W)

        self.https_var = tk.BooleanVar(value=default_https)
        tk.Checkbutton(conn_frame, text="Use HTTPS", variable=self.https_var).grid(
            row=0, column=4, pady=5, padx=5
        )

        self._connection_label(conn_frame, "Username:").grid(
            row=1, column=0, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.user_entry = tk.Entry(conn_frame, width=25)
        self.user_entry.insert(0, default_user)
        self.user_entry.grid(row=1, column=1, pady=5, padx=5)

        self._connection_label(conn_frame, "Password:").grid(
            row=1, column=2, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.password_frame = tk.Frame(
            conn_frame,
            bd=1,
            relief=_tk_constant("SUNKEN", "sunken"),
            bg="white",
        )
        self.password_frame.grid(
            row=1, column=3, columnspan=2, pady=5, padx=5, sticky=tk.EW
        )
        self.password_frame.grid_columnconfigure(0, weight=1)
        self.pass_entry = tk.Entry(
            self.password_frame,
            show="*",
            width=25,
            bd=0,
            relief=_tk_constant("FLAT", "flat"),
            highlightthickness=0,
            bg="white",
        )
        self.pass_entry.grid(
            row=0,
            column=0,
            sticky=tk.EW,
            padx=(5, 2),
            pady=0,
            ipady=0,
        )
        self.pass_entry.bind("<Control-c>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Control-C>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Control-x>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Control-X>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Command-c>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Command-C>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Command-x>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<Command-X>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<<Copy>>", self._block_hidden_password_clipboard)
        self.pass_entry.bind("<<Cut>>", self._block_hidden_password_clipboard)
        self.password_reveal_btn = _PasswordRevealButton(
            self.password_frame,
            command=self._toggle_password_reveal,
            bg=REVEAL_ICON_BG,
            fg=REVEAL_ICON_FG,
            activebackground=REVEAL_ICON_ACTIVE_BG,
            activeforeground=REVEAL_ICON_FG,
            width=PASSWORD_REVEAL_BUTTON_SIZE,
            height=PASSWORD_REVEAL_BUTTON_SIZE,
        )
        self.password_reveal_btn.grid(row=0, column=1, padx=(1, 3), pady=1)

        self.connect_btn = _RoundedButton(
            conn_frame,
            text="Connect",
            command=self._toggle_connection,
            bg="#3498db",
            fg="white",
            activebackground="#2f85c7",
            activeforeground="white",
            font=("Arial", 10, "bold"),
            width=150,
            height=42,
        )
        self.connect_btn.grid(row=0, column=5, rowspan=2, padx=(10, 12), pady=5)

        self.autosave_settings_var = tk.BooleanVar(value=default_autosave_settings)
        self.show_log_var = tk.BooleanVar(value=default_show_log)
        self.search_function_var = tk.BooleanVar(value=default_search_function)
        self.collaboration_projects_var = tk.BooleanVar(
            value=default_collaboration_projects
        )
        self.autosave_settings_frame = tk.Frame(
            conn_frame,
            width=AUTOSAVE_SETTINGS_FRAME_WIDTH,
            height=38,
        )
        self.autosave_settings_frame.grid(
            row=0,
            column=6,
            sticky=tk.W,
            padx=(34, 0),
            pady=5,
        )
        self.autosave_settings_frame.grid_propagate(False)
        self.autosave_settings_check = tk.Checkbutton(
            self.autosave_settings_frame,
            text="Autosave settings",
            variable=self.autosave_settings_var,
            command=self._on_autosave_settings_changed,
            state=_tk_constant("DISABLED", "disabled"),
            disabledforeground="#7a828a",
        )
        self.autosave_settings_check.pack(side=tk.LEFT)
        self.show_log_check = tk.Checkbutton(
            self.autosave_settings_frame,
            text="Show log",
            variable=self.show_log_var,
            command=self._on_show_log_changed,
        )
        self.show_log_check.pack(
            side=tk.LEFT,
            padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0),
        )
        self.search_function_check = tk.Checkbutton(
            self.autosave_settings_frame,
            text="Search",
            variable=self.search_function_var,
            command=self._on_search_function_changed,
            state=_tk_constant("DISABLED", "disabled"),
            disabledforeground="#7a828a",
        )
        self.search_function_check.pack(
            side=tk.LEFT,
            padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0),
        )
        self.collaboration_projects_check = tk.Checkbutton(
            self.autosave_settings_frame,
            text="Collaboration projects",
            variable=self.collaboration_projects_var,
            command=self._on_collaboration_projects_changed,
            state=_tk_constant("DISABLED", "disabled"),
            disabledforeground="#7a828a",
        )
        self.collaboration_projects_check.pack(
            side=tk.LEFT,
            padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0),
        )

        self._preferred_converter_setting = default_converter
        self.converter_var = tk.StringVar(value="")
        self.converter_slot = tk.Frame(
            conn_frame,
            width=CONVERTER_SLOT_WIDTH,
            height=38,
        )
        self.converter_slot.grid(
            row=2,
            column=6,
            columnspan=3,
            sticky=tk.W,
            padx=(34, 0),
            pady=5,
        )
        self.converter_slot.grid_propagate(False)
        self.converter_slot.pack_propagate(False)
        self.append_observed_folders_var = tk.BooleanVar(
            value=default_append_observed_folders
        )
        self.append_observed_folders_check = tk.Checkbutton(
            self.converter_slot,
            text="Append to Observed Folders",
            variable=self.append_observed_folders_var,
            command=self._on_append_observed_folders_changed,
            state=_tk_constant("DISABLED", "disabled"),
            disabledforeground="#7a828a",
        )
        self.append_observed_folders_check.pack(side=tk.LEFT)
        self.converter_frame = tk.Frame(self.converter_slot)
        self.converter_text_offset_spacer = tk.Frame(self.converter_frame, width=0)
        self.converter_text_offset_spacer.pack(side=tk.LEFT, fill=tk.Y)
        self.converter_label = tk.Label(self.converter_frame, text="Converter:")
        self.converter_label.pack(side=tk.LEFT, padx=(0, 5))
        self.converter_dropdown = _ConverterDropdown(
            self.converter_frame,
            variable=self.converter_var,
            command=self._select_converter,
            on_open=self._clear_browser_listbox_focus,
            bg="#f8f9fa",
            fg="#2c3e50",
            activebackground="#e9eef3",
            activeforeground="#2c3e50",
            font=CONVERTER_MENU_FONT,
        )
        self.converter_dropdown.pack(side=tk.LEFT)
        self.refresh_btn = _RoundedButton(
            self.converter_frame,
            text="Refresh",
            command=self._refresh_browser,
            bg="#3498db",
            fg="white",
            activebackground="#2f85c7",
            activeforeground="white",
            font=("Arial", 10, "bold"),
            width=112,
            height=36,
            compact_height=True,
        )
        self.refresh_btn.pack(side=tk.RIGHT)
        self.converter_frame.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
            padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0),
        )
        self.converter_frame.pack_forget()
        conn_frame.grid_columnconfigure(7, weight=1)

        self.folder_path_var = tk.StringVar(value=default_folder_path)
        self._folder_path_placeholder_visible = False
        self._folder_path_trace_suppressed = False
        self._folder_path_write_state = "empty"
        self.path_label = self._connection_label(conn_frame, "Local path:")
        self.path_label.grid(
            row=2, column=0, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.folder_path_entry = tk.Entry(
            conn_frame,
            textvariable=self.folder_path_var,
            font=("Arial", 10),
            width=1,
        )
        self.folder_path_entry.grid(
            row=2,
            column=1,
            columnspan=4,
            sticky=tk.EW,
            padx=5,
            pady=5,
            ipady=4,
        )
        self.folder_path_entry.bind(
            "<FocusIn>",
            lambda _event: self._hide_folder_path_placeholder(),
        )
        self.folder_path_entry.bind(
            "<FocusOut>",
            lambda _event: self._show_folder_path_placeholder(),
        )
        trace_add: Any = getattr(self.folder_path_var, "trace_add", None)
        if callable(trace_add):
            self._folder_path_trace_id = trace_add(
                "write",
                lambda *_args: self._on_folder_path_changed(),
            )
        self.select_folder_btn = _RoundedButton(
            conn_frame,
            text="Select",
            command=self._select_local_folder,
            bg=FOLDER_PATH_SELECT_BG,
            fg="white",
            activebackground=FOLDER_PATH_SELECT_ACTIVE_BG,
            activeforeground="white",
            font=("Arial", 10, "bold"),
            width=96,
            height=38,
            compact_height=True,
        )
        self.select_folder_btn.grid(row=2, column=5, padx=(10, 12), pady=5, sticky=tk.W)
        self.panel_icon_frame = tk.Frame(conn_frame)
        self.panel_icon_frame.grid(
            row=0,
            column=8,
            rowspan=2,
            sticky=tk.NE,
            padx=(12, 0),
            pady=(0, 2),
        )
        self.help_btn = _CircularIconButton(
            self.panel_icon_frame,
            text="?",
            command=self._show_connector_help,
            bg=CONNECTOR_HELP_ICON_BG,
            fg=CONNECTOR_HELP_ICON_FG,
            activebackground=CONNECTOR_HELP_ICON_ACTIVE_BG,
            activeforeground=CONNECTOR_HELP_ICON_FG,
            font=CONNECTOR_PANEL_ICON_FONT,
            width=CONNECTOR_PANEL_ICON_SIZE,
            height=CONNECTOR_PANEL_ICON_SIZE,
        )
        self.info_btn = _CircularIconButton(
            self.panel_icon_frame,
            text="i",
            command=self._show_connector_info,
            bg=CONNECTOR_INFO_ICON_BG,
            fg=CONNECTOR_INFO_ICON_FG,
            activebackground=CONNECTOR_INFO_ICON_ACTIVE_BG,
            activeforeground=CONNECTOR_INFO_ICON_FG,
            font=CONNECTOR_PANEL_ICON_FONT,
            width=CONNECTOR_PANEL_ICON_SIZE,
            height=CONNECTOR_PANEL_ICON_SIZE,
        )
        self.help_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.info_btn.pack(side=tk.LEFT)
        self._align_connection_panel_right_controls()
        self._show_folder_path_placeholder()

        # Browser
        browser = tk.Frame(self.root)
        browser.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.browser_frame = browser
        browser.grid_rowconfigure(0, weight=1)

        # Projects
        p_frame = tk.LabelFrame(browser, text="Projects")
        p_frame.grid(row=0, column=0, sticky=tk.NSEW)
        self._build_browser_search_entry(p_frame, "projects", "Projects")
        self.plist = self._build_scrolled_listbox(p_frame, row=1)
        self.plist.bind("<<ListboxSelect>>", lambda e: self._sel_proj())

        self.browser_sash_1 = self._build_browser_sash(browser, 0)
        self.browser_sash_1.grid(row=0, column=1, sticky=tk.NS)

        # Datasets
        d_frame = tk.LabelFrame(browser, text="Datasets")
        d_frame.grid(row=0, column=2, sticky=tk.NSEW)
        self._build_browser_search_entry(d_frame, "datasets", "Datasets")
        self.dlist = self._build_scrolled_listbox(d_frame, row=1)
        self.dlist.bind("<<ListboxSelect>>", lambda e: self._sel_ds())

        self.browser_sash_2 = self._build_browser_sash(browser, 1)
        self.browser_sash_2.grid(row=0, column=3, sticky=tk.NS)

        # Images
        i_frame = tk.LabelFrame(browser, text="Images")
        i_frame.grid(row=0, column=4, sticky=tk.NSEW)
        self._build_browser_search_entry(i_frame, "images", "Images")
        self.ilist = self._build_scrolled_listbox(
            i_frame,
            selectmode=_tk_constant("MULTIPLE", "multiple"),
            row=1,
        )
        self._configure_image_selection_bindings()
        self._apply_browser_panel_layout()
        browser.bind("<Configure>", lambda _event: self._apply_browser_panel_layout())

        # Actions
        actions = tk.Frame(self.root)
        actions.pack(fill=tk.X, padx=ACTION_ROW_HORIZONTAL_PAD, pady=10)
        actions.grid_columnconfigure(1, minsize=ACTION_BUTTON_GAP)
        actions.grid_columnconfigure(3, weight=1)

        self.load_btn = _RoundedButton(
            actions,
            text="Load images into Imaris",
            command=self._load,
            bg="#27ae60",
            fg="white",
            activebackground="#229954",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            state=_tk_constant("DISABLED", "disabled"),
            width=260,
            height=52,
        )
        self.load_btn.grid(row=0, column=0, sticky=tk.W, padx=ACTION_BUTTON_PAD)

        self.export_btn = _RoundedButton(
            actions,
            text="Export folder to OMERO",
            command=self._export_folder_to_omero,
            bg="#3498db",
            fg="white",
            activebackground="#2f85c7",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            state=_tk_constant("DISABLED", "disabled"),
            width=260,
            height=52,
        )
        self.export_btn.grid(row=0, column=2, sticky=tk.W, padx=ACTION_BUTTON_PAD)

        self.stop_btn = _StopSignButton(
            actions,
            text="STOP",
            command=self._request_stop_current_operation,
            bg="#d71920",
            fg="white",
            activebackground="#a90f14",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            width=108,
            height=52,
        )
        self.stop_btn.grid(
            row=0,
            column=3,
        )
        self.stop_btn.grid_remove()

        self.close_btn = _RoundedButton(
            actions,
            text="Close",
            command=self._on_close,
            bg="#4b5563",
            fg="white",
            activebackground="#374151",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            width=120,
            height=52,
        )
        self.close_btn.grid(row=0, column=4, sticky=tk.E, padx=ACTION_BUTTON_PAD)

        # Reserved for a later progress bar.
        bottom_progress_margin = tk.Frame(
            self.root,
            height=BOTTOM_PROGRESS_RESERVED_HEIGHT,
            bg=_resolve_tk_color(self.root, _widget_background(self.root)),
        )
        bottom_progress_margin.pack(fill=tk.X, side=tk.BOTTOM)
        bottom_progress_margin.pack_propagate(False)

        # Status
        status_frame = tk.Frame(self.root, bg=STATUS_NEUTRAL_BG)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status = tk.Label(
            status_frame,
            text="Ready - Please connect to OMERO",
            bg=STATUS_NEUTRAL_BG,
            anchor=tk.W,
            padx=STATUS_TEXT_PAD,
            pady=5,
            font=("Arial", 9),
            height=2,
        )
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.connection_indicator = tk.Canvas(
            status_frame,
            width=34,
            height=30,
            bg=STATUS_NEUTRAL_BG,
            highlightthickness=0,
            bd=0,
        )
        self.connection_indicator.pack(
            side=tk.RIGHT,
            padx=(STATUS_TEXT_PAD, STATUS_TEXT_PAD),
            pady=2,
        )
        self._draw_connection_indicator("disconnected")
        self.root.bind("<Button-1>", self._clear_text_focus_on_non_input_click, add="+")
        self._set_browser_search_visible(self._search_function_enabled())
        self._set_browser_interaction_state(False)
        self._align_path_row_control_heights()

    def _clear_text_focus_on_non_input_click(self, event):
        """Clear blinking text cursors when clicking outside text inputs.

        Inputs: Tk button event. Output: None.
        """
        event_widget = getattr(event, "widget", None)
        if _widget_or_ancestor_is_text_input(event_widget):
            return
        focus_get = getattr(self.root, "focus_get", None)
        focused_widget = focus_get() if callable(focus_get) else None
        if _widget_or_ancestor_is_text_input(focused_widget):
            self.root.focus_set()

    def _build_browser_search_entry(self, parent, key, label):
        """Build a browser-panel search entry.

        Inputs: `parent`, `key`, `label`. Output: Tk frame containing the entry.
        """
        search_frame = tk.Frame(parent)
        search_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=3, pady=3)
        search_frame.grid_columnconfigure(0, weight=1)
        search_frame.grid_columnconfigure(1, weight=1)
        search_var = tk.StringVar(value="")
        search_entry = tk.Entry(
            search_frame,
            textvariable=search_var,
            font=("Arial", 10),
            width=1,
        )
        search_entry.grid(row=0, column=0, sticky=tk.EW, ipady=4)
        search_entry.bind(
            "<FocusIn>",
            lambda _event, search_key=key: self._hide_browser_search_placeholder(
                search_key
            ),
        )
        search_entry.bind(
            "<FocusOut>",
            lambda _event, search_key=key: self._show_browser_search_placeholder(
                search_key
            ),
        )
        trace_add = getattr(search_var, "trace_add", None)
        if callable(trace_add):
            trace_add(
                "write",
                lambda *_args, search_key=key: self._on_browser_search_changed(
                    search_key
                ),
            )

        self._browser_search_frames[key] = search_frame
        self._browser_search_entries[key] = search_entry
        self._browser_search_vars[key] = search_var
        self._browser_search_placeholder_visible[key] = False
        return search_frame

    @staticmethod
    def _build_scrolled_listbox(parent, selectmode=None, row=0):
        """Build the scrolled listbox for `OMEROBrowserDialog`.

        Inputs: `parent`, `selectmode`, `row`. Output: `listbox`.
        """
        y_scroll = tk.Scrollbar(parent, orient=_tk_constant("VERTICAL", "vertical"))
        x_scroll = tk.Scrollbar(parent, orient=_tk_constant("HORIZONTAL", "horizontal"))
        listbox = tk.Listbox(
            parent,
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
            exportselection=False,
            activestyle=_tk_constant("NONE", "none"),
        )
        if selectmode is not None:
            listbox.config(selectmode=selectmode)
        parent.grid_rowconfigure(row, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        listbox.grid(row=row, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=row, column=1, sticky=tk.NS)
        x_scroll.grid(row=row + 1, column=0, sticky=tk.EW)
        y_scroll.config(command=listbox.yview)
        x_scroll.config(command=listbox.xview)
        return listbox

    def _build_browser_sash(self, parent, sash_index):
        """Return a draggable browser-panel splitter.

        Inputs: `parent`, `sash_index`. Output: `tk.Frame`.
        """
        sash = tk.Frame(
            parent,
            width=BROWSER_SPLITTER_WIDTH,
            cursor="sb_h_double_arrow",
            bd=0,
            highlightthickness=0,
        )
        sash.bind(
            "<ButtonPress-1>",
            lambda event, index=sash_index: self._start_browser_panel_resize(
                index, event
            ),
        )
        sash.bind("<B1-Motion>", self._drag_browser_panel_resize)
        sash.bind("<ButtonRelease-1>", self._stop_browser_panel_resize)
        return sash

    def _browser_panel_area_width(self):
        """Return available browser width excluding splitter bars.

        Inputs: none. Output: int.
        """
        browser = getattr(self, "browser_frame", None)
        if browser is None:
            return 1
        total_width = max(1, int(browser.winfo_width() or 1))
        return max(1, total_width - (2 * BROWSER_SPLITTER_WIDTH))

    def _apply_browser_panel_layout(self):
        """Apply stored browser-panel fractions to the grid columns.

        Inputs: none. Output: None.
        """
        browser = getattr(self, "browser_frame", None)
        if browser is None:
            return
        fractions = _normalized_browser_panel_fractions(
            getattr(self, "_browser_panel_fractions", BROWSER_PANEL_DEFAULT_FRACTIONS)
        )
        self._browser_panel_fractions = fractions
        available_width = self._browser_panel_area_width()
        widths = [
            max(1, int(round(available_width * fraction))) for fraction in fractions
        ]
        widths[-1] = max(1, available_width - widths[0] - widths[1])
        if widths[-1] < 1:
            widths[-1] = 1
            widths[1] = max(1, available_width - widths[0] - widths[2])
        layout_widths = tuple(widths)
        if getattr(self, "_browser_panel_layout_widths", None) == layout_widths:
            return
        self._browser_panel_layout_widths = layout_widths
        for column, width in zip((0, 2, 4), widths):
            browser.grid_columnconfigure(column, minsize=width, weight=0)
        for column in (1, 3):
            browser.grid_columnconfigure(
                column,
                minsize=BROWSER_SPLITTER_WIDTH,
                weight=0,
            )

    def _start_browser_panel_resize(self, sash_index, _event):
        """Remember the active browser splitter drag.

        Inputs: `sash_index`, `_event`. Output: None.
        """
        self._browser_sash_drag_index = sash_index

    def _drag_browser_panel_resize(self, event):
        """Resize browser panels while dragging a splitter.

        Inputs: `event`. Output: None.
        """
        sash_index = getattr(self, "_browser_sash_drag_index", None)
        if sash_index not in {0, 1}:
            return
        browser = getattr(self, "browser_frame", None)
        if browser is None:
            return
        browser_x = browser.winfo_rootx()
        x_position = max(0.0, float(event.x_root - browser_x))
        if sash_index == 0:
            target_pixels = x_position - (BROWSER_SPLITTER_WIDTH / 2.0)
        else:
            target_pixels = x_position - (1.5 * BROWSER_SPLITTER_WIDTH)
        target_fraction = target_pixels / float(self._browser_panel_area_width())
        self._browser_panel_fractions = _resize_browser_panel_fractions(
            getattr(self, "_browser_panel_fractions", BROWSER_PANEL_DEFAULT_FRACTIONS),
            sash_index,
            target_fraction,
        )
        self._apply_browser_panel_layout()

    def _stop_browser_panel_resize(self, _event):
        """Clear active browser splitter drag state.

        Inputs: `_event`. Output: None.
        """
        self._browser_sash_drag_index = None

    def _configure_initial_window_constraints(self):
        """Configure the initial window constraints for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: configures the described state and returns None.
        """
        self._enforce_window_minimum_for_current_layout()
        self.root.resizable(True, True)

    def _enforce_window_minimum_for_current_layout(self):
        """Prevent the main window from shrinking below requested widget width.

        Inputs: none. Output: None.
        """
        root = getattr(self, "root", None)
        if root is None:
            return
        _call_if_available(root, "update_idletasks")
        width, height = self._current_window_minimum_size(root)
        _call_if_available(root, "minsize", width, height)
        if self._window_is_smaller_than(root, width, height):
            root.geometry(f"{width}x{height}")
            _call_if_available(root, "update_idletasks")

    @staticmethod
    def _current_window_minimum_size(root):
        """Return the minimum size required by the current connector layout.

        Inputs: `root`. Output: tuple of width and height.
        """
        current_min = _current_root_minsize(root)
        width = max(
            OMERO_CONNECTOR_WINDOW_WIDTH,
            _safe_widget_dimension(root, "winfo_width"),
            _safe_widget_dimension(root, "winfo_reqwidth"),
            current_min[0],
        )
        height = max(
            OMERO_CONNECTOR_WINDOW_HEIGHT,
            _safe_widget_dimension(root, "winfo_height"),
            _safe_widget_dimension(root, "winfo_reqheight"),
            current_min[1],
        )
        return width, height

    @staticmethod
    def _window_is_smaller_than(root, width, height):
        """Return whether the current root size is below the supplied size.

        Inputs: `root`, `width`, `height`. Output: bool.
        """
        return (
            _safe_widget_dimension(root, "winfo_width") < width
            or _safe_widget_dimension(root, "winfo_height") < height
        )

    def _select_converter(self, value):
        """Set the selected converter and refresh dependent action state.

        Inputs: `value`. Output: None.
        """
        self.converter_var.set(value)
        self._preferred_converter_setting = str(value or "")
        self._set_load_button_for_converter()
        if (
            getattr(self, "_connected", False)
            and self._autosave_settings_enabled()
            and not self._write_autosave_settings()
        ):
            self._show_autosave_settings_error()

    def _set_converter_options(self, options):
        """Set the converter options for `OMEROBrowserDialog`.

        Inputs: `options`. Output: None.
        """
        options = list(options or [])
        self._available_converter_options = tuple(options)
        dropdown = getattr(self, "converter_dropdown", None)
        if dropdown is not None:
            dropdown.set_options(options)
        if not options:
            self.converter_var.set("")
            self._hide_converter_frame()
            self._set_load_button_for_converter()
            self._set_refresh_button_state(_tk_constant("DISABLED", "disabled"))
            return

        preferred = str(getattr(self, "_preferred_converter_setting", "") or "")
        if preferred not in options:
            preferred = _filled_connector_setting(
                getattr(self, "_saved_settings", {}),
                CONNECTOR_SETTINGS_CONVERTER_KEY,
            )
        selected = preferred if preferred in options else options[0]
        self.converter_var.set(selected)
        self._preferred_converter_setting = selected
        self._show_converter_frame()
        self._set_load_button_for_converter()
        self._set_refresh_button_state(
            _tk_constant("DISABLED", "disabled")
            if getattr(self, "_folder_export_in_progress", False)
            else _tk_constant("NORMAL", "normal")
        )

    def _set_folder_path_entry_fg(self, color):
        """Set the folder path entry text color when the widget is available.

        Inputs: `color`. Output: None.
        """
        entry = getattr(self, "folder_path_entry", None)
        configure: Any = getattr(entry, "config", None)
        if callable(configure):
            try:
                configure(fg=color)
            except Exception as exc:
                _xt_debug(
                    f"Folder path entry color update failed: {type(exc).__name__}"
                )

    def _set_folder_path_var_safely(self, value):
        """Set the path variable without treating the write as user typing.

        Inputs: `value`. Output: None.
        """
        variable = getattr(self, "folder_path_var", None)
        setter: Any = getattr(variable, "set", None)
        if not callable(setter):
            return
        self._folder_path_trace_suppressed = True
        try:
            setter(value)
        finally:
            self._folder_path_trace_suppressed = False

    def _on_folder_path_changed(self):
        """Handle user edits to the folder path box.

        Inputs: no caller arguments. Output: None.
        """
        if getattr(self, "_folder_path_trace_suppressed", False):
            return
        if getattr(self, "_folder_path_placeholder_visible", False):
            return
        path_value = self._current_local_folder_path()
        self._folder_path_write_state = (
            "unchecked" if _is_structurally_valid_folder_path(path_value) else "invalid"
        )
        self._queue_folder_path_dir_check(path_value)
        self._set_folder_path_entry_fg(FOLDER_PATH_TEXT_FG)
        self._set_load_button_for_converter()

    def _show_folder_path_placeholder(self):
        """Show display-only placeholder text when the path entry is empty.

        Inputs: no caller arguments. Output: None.
        """
        variable = getattr(self, "folder_path_var", None)
        raw_value = _stringvar_value(variable)
        if raw_value.strip():
            if (
                getattr(self, "_folder_path_placeholder_visible", False)
                and raw_value == FOLDER_PATH_PLACEHOLDER
            ):
                self._set_folder_path_entry_fg(FOLDER_PATH_PLACEHOLDER_FG)
                return
            self._folder_path_placeholder_visible = False
            self._folder_path_write_state = (
                "unchecked"
                if _is_structurally_valid_folder_path(raw_value)
                else "invalid"
            )
            self._queue_folder_path_dir_check(raw_value)
            self._set_folder_path_entry_fg(FOLDER_PATH_TEXT_FG)
            self._set_load_button_for_converter()
            return

        self._set_folder_path_var_safely(FOLDER_PATH_PLACEHOLDER)
        self._folder_path_placeholder_visible = True
        self._folder_path_write_state = "empty"
        self._queue_folder_path_dir_check("")
        self._set_folder_path_entry_fg(FOLDER_PATH_PLACEHOLDER_FG)
        self._set_load_button_for_converter()

    def _hide_folder_path_placeholder(self):
        """Clear display-only placeholder text before user path editing.

        Inputs: no caller arguments. Output: None.
        """
        if getattr(self, "_folder_path_placeholder_visible", False):
            self._set_folder_path_var_safely("")
        self._folder_path_placeholder_visible = False
        self._folder_path_write_state = "empty"
        self._queue_folder_path_dir_check("")
        self._set_folder_path_entry_fg(FOLDER_PATH_TEXT_FG)
        self._set_load_button_for_converter()

    def _set_folder_path_value(self, folder_path, write_state="unchecked"):
        """Store a real folder path and mark the entry text as user data.

        Inputs: `folder_path`, `write_state`. Output: None.
        """
        value = _display_local_path(folder_path)
        self._set_folder_path_var_safely(value)
        self._folder_path_placeholder_visible = False
        self._folder_path_write_state = (
            write_state if _is_structurally_valid_folder_path(value) else "invalid"
        )
        self._queue_folder_path_dir_check(value)
        self._set_folder_path_entry_fg(FOLDER_PATH_TEXT_FG)
        self._set_load_button_for_converter()

    def _entry_text(self, widget_name):
        """Return text from one entry widget.

        Inputs: `widget_name`. Output: `str`.
        """
        widget = getattr(self, widget_name, None)
        getter: Any = getattr(widget, "get", None)
        value = getter() if callable(getter) else ""
        return str(value or "")

    def _autosave_settings_enabled(self):
        """Return whether settings autosave is currently selected.

        Inputs: none. Output: bool.
        """
        variable = getattr(self, "autosave_settings_var", None)
        getter: Any = getattr(variable, "get", None)
        return bool(getter() if callable(getter) else False)

    def _show_log_enabled(self):
        """Return whether command-window log output should be visible.

        Inputs: none. Output: bool.
        """
        variable = getattr(self, "show_log_var", None)
        getter: Any = getattr(variable, "get", None)
        return bool(getter() if callable(getter) else True)

    def _search_function_enabled(self):
        """Return whether the browser search option is selected.

        Inputs: none. Output: bool.
        """
        variable = getattr(self, "search_function_var", None)
        getter: Any = getattr(variable, "get", None)
        return bool(getter() if callable(getter) else False)

    def _collaboration_projects_enabled(self):
        """Return whether project browsing should include collaboration projects.

        Inputs: none. Output: bool.
        """
        variable = getattr(self, "collaboration_projects_var", None)
        getter: Any = getattr(variable, "get", None)
        return bool(getter() if callable(getter) else False)

    def _append_observed_folders_enabled(self):
        """Return whether selected paths should be appended to Imaris Arena.

        Inputs: none. Output: bool.
        """
        variable = getattr(self, "append_observed_folders_var", None)
        getter: Any = getattr(variable, "get", None)
        return bool(getter() if callable(getter) else False)

    def _append_current_path_to_imaris_arena_if_enabled(self):
        """Append the current local folder path to Imaris Arena when enabled.

        Inputs: none. Output: bool.
        """
        if not self._append_observed_folders_enabled():
            return False
        folder_path = self._current_local_folder_path()
        if not _is_structurally_valid_folder_path(folder_path):
            return False
        if not _safe_is_directory(folder_path):
            return False
        imaris_executable = _filled_connector_setting(
            getattr(self, "_saved_settings", {}),
            CONNECTOR_SETTINGS_IMARIS_EXE_KEY,
        )
        try:
            return _append_imaris_arena_observed_folder(
                folder_path,
                imaris_executable=imaris_executable or None,
            )
        except Exception as exc:
            _xt_debug(
                "Imaris Arena observed-folder append failed while loading: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

    def _browser_search_placeholder(self, key):
        """Return placeholder text for a browser search entry.

        Inputs: `key`. Output: placeholder text.
        """
        label = {
            "projects": "Projects",
            "datasets": "Datasets",
            "images": "Images",
        }.get(key, "items")
        return f"Type to search {label}"

    def _set_browser_search_var_safely(self, key, value):
        """Set a browser search variable without triggering filtering side effects.

        Inputs: `key`, `value`. Output: None.
        """
        variable = getattr(self, "_browser_search_vars", {}).get(key)
        setter = getattr(variable, "set", None)
        if not callable(setter):
            return
        suppressed: Set[str] = getattr(
            self,
            "_browser_search_trace_suppressed",
            set(),
        )
        suppressed.add(key)
        self._browser_search_trace_suppressed = suppressed
        try:
            setter(value)
        finally:
            self._browser_search_trace_suppressed.discard(key)

    def _show_browser_search_placeholder(self, key):
        """Show search placeholder text when a search box is empty.

        Inputs: `key`. Output: None.
        """
        if not self._search_function_enabled():
            return
        variable = getattr(self, "_browser_search_vars", {}).get(key)
        getter = getattr(variable, "get", None)
        current = str(getter() if callable(getter) else "")
        if current:
            return
        self._set_browser_search_var_safely(
            key,
            self._browser_search_placeholder(key),
        )
        getattr(self, "_browser_search_placeholder_visible", {})[key] = True
        entry = getattr(self, "_browser_search_entries", {}).get(key)
        configure = getattr(entry, "config", None)
        if callable(configure):
            configure(fg=BROWSER_SEARCH_PLACEHOLDER_FG)

    def _hide_browser_search_placeholder(self, key):
        """Hide search placeholder text before user editing.

        Inputs: `key`. Output: None.
        """
        if getattr(self, "_browser_search_placeholder_visible", {}).get(key, False):
            self._set_browser_search_var_safely(key, "")
        getattr(self, "_browser_search_placeholder_visible", {})[key] = False
        entry = getattr(self, "_browser_search_entries", {}).get(key)
        configure = getattr(entry, "config", None)
        if callable(configure):
            configure(fg=BROWSER_SEARCH_TEXT_FG)

    def _browser_search_query(self, key):
        """Return the active browser search query for a panel.

        Inputs: `key`. Output: query text.
        """
        if getattr(self, "_browser_search_placeholder_visible", {}).get(key, False):
            return ""
        variable = getattr(self, "_browser_search_vars", {}).get(key)
        getter = getattr(variable, "get", None)
        return str(getter() if callable(getter) else "").strip()

    @staticmethod
    def _filter_entities_by_label(entities, labeler, query):
        """Filter already-loaded entities by a case-insensitive partial label match.

        Inputs: `entities`, `labeler`, `query`. Output: filtered entity list.
        """
        rows = list(entities or [])
        query_text = str(query or "").strip().casefold()
        if not query_text:
            return rows
        return [
            entity
            for entity in rows
            if query_text in str(labeler(entity) or "").casefold()
        ]

    def _set_browser_search_visible(self, visible):
        """Show or hide browser search boxes without changing the window size.

        Inputs: `visible`. Output: None.
        """
        visible = bool(visible)
        for key, frame in getattr(self, "_browser_search_frames", {}).items():
            if visible:
                grid = getattr(frame, "grid", None)
                if callable(grid):
                    grid()
                self._show_browser_search_placeholder(key)
            else:
                getattr(self, "_browser_search_placeholder_visible", {})[key] = False
                self._set_browser_search_var_safely(key, "")
                grid_remove = getattr(frame, "grid_remove", None)
                if callable(grid_remove):
                    grid_remove()
        self._apply_all_browser_search_filters()
        self._set_browser_interaction_state(getattr(self, "_connected", False))

    def _set_browser_interaction_state(self, enabled):
        """Enable or disable browser searches and lists.

        Inputs: `enabled`. Output: None.
        """
        enabled = bool(enabled)
        state = (
            _tk_constant("NORMAL", "normal")
            if enabled
            else _tk_constant("DISABLED", "disabled")
        )
        search_state = state
        for check_name in (
            "search_function_check",
            "collaboration_projects_check",
            "append_observed_folders_check",
        ):
            configure = getattr(getattr(self, check_name, None), "config", None)
            if callable(configure):
                configure(state=state)

        for key, entry in getattr(self, "_browser_search_entries", {}).items():
            configure = getattr(entry, "config", None)
            if not callable(configure):
                continue
            if enabled:
                foreground = (
                    BROWSER_SEARCH_PLACEHOLDER_FG
                    if getattr(self, "_browser_search_placeholder_visible", {}).get(
                        key, False
                    )
                    else BROWSER_SEARCH_TEXT_FG
                )
                configure(
                    state=search_state,
                    bg="white",
                    fg=foreground,
                    disabledforeground=BROWSER_DISABLED_FG,
                )
            else:
                configure(
                    state=search_state,
                    bg=BROWSER_DISABLED_BG,
                    fg=BROWSER_DISABLED_FG,
                    disabledforeground=BROWSER_DISABLED_FG,
                )

        for listbox_name in ("plist", "dlist", "ilist"):
            listbox = getattr(self, listbox_name, None)
            configure = getattr(listbox, "config", None)
            if not callable(configure):
                continue
            if enabled:
                configure(state=state, bg="white", fg="#111827")
            else:
                configure(
                    state=state,
                    bg=BROWSER_DISABLED_BG,
                    fg=BROWSER_DISABLED_FG,
                    disabledforeground=BROWSER_DISABLED_FG,
                )

    def _on_browser_search_changed(self, key):
        """Filter one browser panel after its search query changes.

        Inputs: `key`. Output: None.
        """
        if key in getattr(self, "_browser_search_trace_suppressed", set()):
            return
        if getattr(self, "_browser_search_placeholder_visible", {}).get(key, False):
            return
        self._apply_browser_search_filter(key)

    def _apply_all_browser_search_filters(self):
        """Refresh all browser panels from current search queries.

        Inputs: none. Output: None.
        """
        for key in ("projects", "datasets", "images"):
            self._apply_browser_search_filter(key)

    def _apply_browser_search_filter(self, key):
        """Apply the current search filter to one already-loaded browser panel.

        Inputs: `key`. Output: None.
        """
        if key == "projects":
            if not hasattr(self, "plist"):
                return
            selected_id = self._current_selected_project_id()
            self.projects_data = self._filter_entities_by_label(
                getattr(self, "_all_projects_data", []),
                self._project_list_label,
                self._browser_search_query("projects"),
            )
            self._replace_listbox_items(
                self.plist,
                [self._project_list_label(project) for project in self.projects_data],
            )
            self._select_listbox_index(
                self.plist,
                self._find_entity_index(self.projects_data, selected_id),
            )
            return
        if key == "datasets":
            if not hasattr(self, "dlist"):
                return
            selected_id = self._current_selected_dataset_id()
            self.datasets_data = self._filter_entities_by_label(
                getattr(self, "_all_datasets_data", []),
                self._dataset_list_label,
                self._browser_search_query("datasets"),
            )
            self._replace_listbox_items(
                self.dlist,
                [self._dataset_list_label(dataset) for dataset in self.datasets_data],
            )
            self._select_listbox_index(
                self.dlist,
                self._find_entity_index(self.datasets_data, selected_id),
            )
            return
        if key == "images":
            if not hasattr(self, "ilist"):
                return
            selected_ids = {
                self._entity_id(image)
                for image in self._selected_images()
                if self._entity_id(image) is not None
            }
            self.images_data = self._filter_entities_by_label(
                getattr(self, "_all_images_data", []),
                self._image_list_label,
                self._browser_search_query("images"),
            )
            self._replace_listbox_items(
                self.ilist,
                [self._image_list_label(image) for image in self.images_data],
            )
            self._clear_listbox_selection(self.ilist)
            first_selected_index = None
            for index, image in enumerate(self.images_data):
                if self._entity_id(image) in selected_ids:
                    self.ilist.selection_set(index)
                    if first_selected_index is None:
                        first_selected_index = index
            self._image_selection_anchor = first_selected_index
            if first_selected_index is not None:
                self._set_listbox_anchor(self.ilist, first_selected_index)
            self._refresh_load_button_text()

    def _iter_modal_background_widgets(self):
        """Yield main-window widgets whose cursors must be neutral during modals.

        Inputs: none. Output: yielded Tk widgets.
        """
        root = getattr(self, "root", None)
        if root is None:
            return
        stack = [root]
        while stack:
            widget = stack.pop()
            if widget is not root:
                toplevel_getter = getattr(widget, "winfo_toplevel", None)
                try:
                    if callable(toplevel_getter) and toplevel_getter() is not root:
                        continue
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in XTOmeroConnector.py",
                        exc_info=exc,
                    )
                    continue
            yield widget
            children_getter = getattr(widget, "winfo_children", None)
            if callable(children_getter):
                try:
                    stack.extend(children_getter())
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in XTOmeroConnector.py",
                        exc_info=exc,
                    )
                    continue

    def _set_main_window_disabled(self, disabled):
        """Block or restore direct input to the main connector window.

        Inputs: `disabled`. Output: bool indicating whether Tk accepted the request.
        """
        root = getattr(self, "root", None)
        for method_name in ("attributes", "wm_attributes"):
            setter = getattr(root, method_name, None)
            if callable(setter):
                try:
                    setter("-disabled", bool(disabled))
                    return True
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in XTOmeroConnector.py",
                        exc_info=exc,
                    )
                    continue
        return False

    def _lock_modal_background(self):
        """Neutralize background interaction while a blocking child is active.

        Inputs: none. Output: None.
        """
        depth = int(getattr(self, "_modal_background_lock_depth", 0) or 0)
        self._modal_background_lock_depth = depth + 1
        if depth:
            return

        cursor_restore = []
        for widget in self._iter_modal_background_widgets():
            getter = getattr(widget, "cget", None)
            setter = getattr(widget, "configure", None)
            if not callable(getter) or not callable(setter):
                continue
            try:
                cursor_restore.append((widget, getter("cursor")))
                setter(cursor="arrow")
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
                continue
        self._modal_background_cursor_restore = cursor_restore
        self._modal_background_window_disabled = self._set_main_window_disabled(True)

    def _unlock_modal_background(self):
        """Restore the main connector window after a blocking child closes.

        Inputs: none. Output: None.
        """
        depth = int(getattr(self, "_modal_background_lock_depth", 0) or 0)
        if depth > 1:
            self._modal_background_lock_depth = depth - 1
            return
        self._modal_background_lock_depth = 0

        for widget, cursor in reversed(
            list(getattr(self, "_modal_background_cursor_restore", []) or [])
        ):
            exists = getattr(widget, "winfo_exists", None)
            setter = getattr(widget, "configure", None)
            try:
                if callable(setter) and (not callable(exists) or exists()):
                    setter(cursor=cursor)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
                continue
        self._modal_background_cursor_restore = []

        if getattr(self, "_modal_background_window_disabled", False):
            self._set_main_window_disabled(False)
        self._modal_background_window_disabled = False
        self._sync_action_button_cursors()

    @staticmethod
    def _call_messagebox_function(function, title, message, parent, **options):
        """Call a Tk messagebox function with a parent when supported.

        Inputs: `function`, `title`, `message`, `parent`, `options`. Output: function
        result.
        """
        try:
            return function(title, message, parent=parent, **options)
        except TypeError as exc:
            message_text = str(exc)
            if "parent" not in message_text and "keyword" not in message_text:
                raise
            try:
                return function(title, message, **options)
            except TypeError as fallback_exc:
                fallback_text = str(fallback_exc)
                if "keyword" not in fallback_text:
                    raise
                return function(title, message)

    def _run_blocking_modal(self, callback):
        """Run a blocking modal while the main window cannot be interacted with.

        Inputs: `callback`. Output: callback result.
        """
        self._lock_modal_background()
        try:
            return callback()
        finally:
            self._unlock_modal_background()

    def _show_messagebox_dialog(self, kind, title, message, **options):
        """Show a modal messagebox with the main window locked behind it.

        Inputs: `kind`, `title`, `message`, `options`. Output: messagebox result.
        """
        function = getattr(messagebox, kind)
        return self._run_blocking_modal(
            lambda: self._call_messagebox_function(
                function,
                title,
                message,
                getattr(self, "root", None),
                **options,
            )
        )

    def _show_warning_dialog(self, title, message):
        """Show a modal warning dialog.

        Inputs: `title`, `message`. Output: messagebox result.
        """
        return self._show_messagebox_dialog("showwarning", title, message)

    def _show_error_dialog(self, title, message):
        """Show a modal error dialog.

        Inputs: `title`, `message`. Output: messagebox result.
        """
        return self._show_messagebox_dialog("showerror", title, message)

    def _show_info_dialog(self, title, message):
        """Show a modal information dialog.

        Inputs: `title`, `message`. Output: messagebox result.
        """
        return self._show_messagebox_dialog("showinfo", title, message)

    def _ask_yes_no_dialog(self, title, message):
        """Show a modal yes/no question dialog.

        Inputs: `title`, `message`. Output: bool.
        """
        return bool(self._show_messagebox_dialog("askyesno", title, message))

    def _ask_yes_no_cancel_dialog(self, title, message):
        """Show a modal yes/no/cancel question dialog.

        Inputs: `title`, `message`. Output: bool or None.
        """
        return self._show_messagebox_dialog(
            "askyesnocancel",
            title,
            message,
            default="yes",
        )

    def _connector_settings_snapshot(self):
        """Return the connector settings that may be persisted.

        Inputs: none. Output: dict. Passwords are intentionally excluded.
        """
        https_variable = getattr(self, "https_var", None)
        https_getter: Any = getattr(https_variable, "get", None)
        https_value = https_getter() if callable(https_getter) else False
        imaris_executable = _filled_connector_setting(
            getattr(self, "_saved_settings", {}),
            CONNECTOR_SETTINGS_IMARIS_EXE_KEY,
        )
        if not _is_existing_supported_imaris_executable_path(imaris_executable):
            settings_file_path = getattr(self, "_settings_file_path", None)
            try:
                settings_target = (
                    _coerce_path(settings_file_path)
                    if settings_file_path is not None
                    else None
                )
            except TypeError:
                settings_target = None
            if (
                settings_target is not None
                and not _connector_settings_target_safety_error(settings_target)
            ):
                imaris_executable = (
                    _connector_settings_imaris_executable_candidate(settings_target)
                    or ""
                )
            else:
                imaris_executable = ""
        return {
            CONNECTOR_SETTINGS_HOST_KEY: self._entry_text("host_entry").strip(),
            CONNECTOR_SETTINGS_PORT_KEY: self._entry_text("port_entry").strip(),
            CONNECTOR_SETTINGS_USERNAME_KEY: self._entry_text("user_entry").strip(),
            CONNECTOR_SETTINGS_HTTPS_KEY: _connector_settings_bool_text(https_value),
            CONNECTOR_SETTINGS_CONVERTER_KEY: _stringvar_value(
                getattr(self, "converter_var", None)
            ),
            CONNECTOR_SETTINGS_AUTOSAVE_KEY: _connector_settings_bool_text(
                self._autosave_settings_enabled()
            ),
            CONNECTOR_SETTINGS_SHOW_LOG_KEY: _connector_settings_bool_text(
                self._show_log_enabled()
            ),
            CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY: _connector_settings_bool_text(
                self._search_function_enabled()
            ),
            CONNECTOR_SETTINGS_COLLABORATION_PROJECTS_KEY: (
                _connector_settings_bool_text(self._collaboration_projects_enabled())
            ),
            CONNECTOR_SETTINGS_APPEND_OBSERVED_FOLDERS_KEY: _connector_settings_bool_text(
                self._append_observed_folders_enabled()
            ),
            CONNECTOR_SETTINGS_IMARIS_EXE_KEY: imaris_executable,
            CONNECTOR_SETTINGS_VERSION_KEY: _current_connector_settings_version(),
        }

    def _write_autosave_settings(self):
        """Write connector autosave settings to the user profile.

        Inputs: none. Output: bool.
        """
        if getattr(self, "_settings_file_path", None) is None:
            try:
                self._settings_file_path = _connector_settings_env_path()
            except OSError as exc:
                self._autosave_settings_write_error = str(exc)
                _log_connector_settings_event(
                    f"Connector settings write failed: {type(exc).__name__}"
                )
                return False
        try:
            _atomic_write_connector_settings(
                self._connector_settings_snapshot(), self._settings_file_path
            )
            self._saved_settings = _load_connector_settings(self._settings_file_path)
            self._autosave_settings_write_error = ""
            return True
        except (OSError, TypeError, ValueError) as exc:
            self._autosave_settings_write_error = str(exc)
            return False

    def _show_autosave_settings_error(self):
        """Show the generic autosave-settings write error.

        Inputs: none. Output: None.
        """
        self._show_warning_dialog(
            AUTOSAVE_SETTINGS_ERROR_TITLE,
            AUTOSAVE_SETTINGS_ERROR_MESSAGE,
        )

    def _cancel_password_reveal_timer(self):
        """Cancel any pending password-hide callback.

        Inputs: none. Output: None.
        """
        after_id: Optional[str] = getattr(self, "_password_reveal_after_id", None)
        root = getattr(self, "root", None)
        if after_id is not None and root is not None and hasattr(root, "after_cancel"):
            try:
                root.after_cancel(after_id)
            except Exception as exc:
                _xt_debug(f"Password reveal timer cancellation failed: {exc}")
        self._password_reveal_after_id = None

    def _set_password_revealed(self, visible):
        """Set whether the password entry text is visible.

        Inputs: `visible`. Output: None.
        """
        visible = bool(visible)
        entry = getattr(self, "pass_entry", None)
        configure: Any = getattr(entry, "config", None)
        if callable(configure):
            configure(show="" if visible else "*")
        self._password_revealed = visible
        button = getattr(self, "password_reveal_btn", None)
        setter: Any = getattr(button, "set_visible", None)
        if callable(setter):
            setter(visible)
        if not visible:
            self._cancel_password_reveal_timer()

    def _block_hidden_password_clipboard(self, _event=None):
        """Prevent copy/cut while hidden without blocking selection or paste.

        Inputs: optional Tk event. Output: Tk break marker or None.
        """
        if not getattr(self, "_password_revealed", False):
            return "break"
        return None

    def _hide_password_reveal(self):
        """Hide the password entry text after the reveal timeout.

        Inputs: none. Output: None.
        """
        self._password_reveal_after_id = None
        self._set_password_revealed(False)

    def _toggle_password_reveal(self):
        """Reveal the password entry contents for the fixed timeout.

        Inputs: none. Output: None.
        """
        if getattr(self, "_password_revealed", False):
            self._set_password_revealed(False)
            return
        if not self._entry_text("pass_entry"):
            self._set_password_revealed(False)
            return
        self._set_password_revealed(True)
        self._cancel_password_reveal_timer()
        root = getattr(self, "root", None)
        if root is not None and hasattr(root, "after"):
            self._password_reveal_after_id = root.after(
                PASSWORD_REVEAL_DURATION_MS,
                self._hide_password_reveal,
            )

    def _clear_password_entry(self):
        """Clear the visible password field and restore hidden mode first.

        Inputs: none. Output: None.
        """
        self._set_password_revealed(False)
        entry = getattr(self, "pass_entry", None)
        delete: Any = getattr(entry, "delete", None)
        if callable(delete):
            delete(0, _tk_constant("END", "end"))

    def _set_password_entry_interactive(self, enabled):
        """Enable or gray out the password entry and reveal control.

        Inputs: `enabled`. Output: None.
        """
        enabled = bool(enabled)
        state = (
            _tk_constant("NORMAL", "normal")
            if enabled
            else _tk_constant("DISABLED", "disabled")
        )
        bg = "white" if enabled else BROWSER_DISABLED_BG
        fg = "#111827" if enabled else BROWSER_DISABLED_FG
        frame_config = getattr(getattr(self, "password_frame", None), "config", None)
        if callable(frame_config):
            frame_config(bg=bg)
        entry_config = getattr(getattr(self, "pass_entry", None), "config", None)
        if callable(entry_config):
            entry_config(
                state=state,
                bg=bg,
                fg=fg,
                disabledbackground=BROWSER_DISABLED_BG,
                disabledforeground=BROWSER_DISABLED_FG,
            )
        reveal_config = getattr(
            getattr(self, "password_reveal_btn", None),
            "config",
            None,
        )
        if callable(reveal_config):
            reveal_config(state=state)

    def _set_autosave_settings_control_state(self, enabled):
        """Enable or disable the autosave settings checkbox.

        Inputs: `enabled`. Output: None.
        """
        check = getattr(self, "autosave_settings_check", None)
        configure: Any = getattr(check, "config", None)
        if callable(configure):
            state = (
                _tk_constant("NORMAL", "normal")
                if enabled
                else _tk_constant("DISABLED", "disabled")
            )
            configure(state=state)

    def _set_connected_settings_control_state(self, enabled):
        """Enable or disable settings that require a verified OMERO connection.

        Inputs: `enabled`. Output: None.
        """
        self._set_autosave_settings_control_state(enabled)
        self._set_browser_interaction_state(enabled)

    def _on_autosave_settings_changed(self):
        """Persist the autosave status immediately after a user toggle.

        Inputs: none. Output: None.
        """
        if not getattr(self, "_connected", False):
            self._set_connected_settings_control_state(False)
            return
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _on_show_log_changed(self):
        """Persist and apply the command-window log visibility setting.

        Inputs: none. Output: None.
        """
        _configure_xt_console_visibility(self._show_log_enabled())
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _on_search_function_changed(self):
        """Show or hide browser search boxes and persist the setting.

        Inputs: none. Output: None.
        """
        if not getattr(self, "_connected", False):
            self._set_connected_settings_control_state(False)
            return
        self._set_browser_search_visible(self._search_function_enabled())
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _on_collaboration_projects_changed(self):
        """Persist the project-scope setting and refresh the project list.

        Inputs: none. Output: None.
        """
        if not getattr(self, "_connected", False):
            self._set_connected_settings_control_state(False)
            return
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()
        self._refresh_browser()

    def _on_append_observed_folders_changed(self):
        """Persist the Imaris Arena observed-folder append setting.

        Inputs: none. Output: None.
        """
        if not getattr(self, "_connected", False):
            self._set_connected_settings_control_state(False)
            return
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _enable_autosave_after_verified_connection(self):
        """Enable autosave controls and persist verified connection settings.

        Inputs: none. Output: None.
        """
        self._set_connected_settings_control_state(True)
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _current_local_folder_path(self):
        """Return the export folder path currently typed in the selector row.

        Inputs: no caller arguments. Output: `str`.
        """
        if getattr(self, "_folder_path_placeholder_visible", False):
            return ""
        return _stringvar_value(getattr(self, "folder_path_var", None))

    def _queue_folder_path_dir_check(self, path_value):
        """Start a background existence check for the typed path.

        Inputs: `path_value`. Output: None.
        """
        path_text = str(path_value or "")
        generation = getattr(self, "_folder_path_dir_check_generation", 0) + 1
        self._folder_path_dir_check_generation = generation
        if not path_text or not _is_structurally_valid_folder_path(path_text):
            self._finish_folder_path_dir_check(generation, path_text, False)
            return
        root = getattr(self, "root", None)
        if root is None or not hasattr(root, "after"):
            self._finish_folder_path_dir_check(
                generation,
                path_text,
                _safe_is_directory(path_text),
            )
            return
        threading.Thread(
            target=self._folder_path_dir_check_worker,
            args=(generation, path_text),
            daemon=True,
        ).start()

    def _folder_path_dir_check_worker(self, generation, path_text):
        """Check whether the typed path is an existing directory off the UI thread.

        Inputs: `generation`, `path_text`. Output: None.
        """
        is_directory = _safe_is_directory(path_text)
        self._invoke_on_ui_thread(
            lambda: self._finish_folder_path_dir_check(
                generation,
                path_text,
                is_directory,
            ),
            wait=False,
        )

    def _finish_folder_path_dir_check(self, generation, path_text, is_directory):
        """Record the latest typed-path directory check result.

        Inputs: `generation`, `path_text`, `is_directory`. Output: None.
        """
        if generation != getattr(self, "_folder_path_dir_check_generation", 0):
            return
        self._folder_path_dir_check_value = str(path_text or "")
        self._folder_path_dir_check_is_dir = bool(is_directory)

    def _folder_path_allows_load_button(self):
        """Return whether path text can participate in the Load button state.

        Inputs: none. Output: bool.
        """
        if getattr(self, "_folder_path_placeholder_visible", False):
            return False
        path_value = self._current_local_folder_path()
        if not _is_structurally_valid_folder_path(path_value):
            return False
        return getattr(self, "_folder_path_write_state", "unchecked") != "unwritable"

    def _show_folder_path_write_error(self):
        """Show the common local-folder write error.

        Inputs: no caller arguments. Output: None.
        """
        self._show_error_dialog(
            LOCAL_PATH_WRITE_ERROR_TITLE,
            LOCAL_PATH_WRITE_ERROR_MESSAGE,
        )

    def _mark_folder_path_write_state(self, path_value):
        """Check and remember whether the path is writable.

        Inputs: `path_value`. Output: bool.
        """
        error = _folder_path_write_error(path_value)
        self._folder_path_write_state = "unwritable" if error else "writable"
        self._set_load_button_for_converter()
        return not error

    def _select_local_folder(self):
        """Open the native folder selector and store the selected path.

        Inputs: no caller arguments. Output: None.
        """
        dialog_title = "Select folder to export to OMERO"
        current_path = self._current_local_folder_path()
        if _safe_is_directory(current_path):
            selected_folder = filedialog.askdirectory(
                parent=self.root,
                mustexist=True,
                title=dialog_title,
                initialdir=current_path,
            )
        else:
            selected_folder = filedialog.askdirectory(
                parent=self.root,
                mustexist=True,
                title=dialog_title,
            )
        if selected_folder:
            selected_folder = str(selected_folder)
            error = _folder_path_write_error(selected_folder)
            self._set_folder_path_value(
                selected_folder,
                write_state="unwritable" if error else "writable",
            )
            if error:
                self._show_folder_path_write_error()
            else:
                if (
                    getattr(self, "_connected", False)
                    and self._autosave_settings_enabled()
                    and not self._write_autosave_settings()
                ):
                    self._show_autosave_settings_error()

    def _folder_export_dialog_initialdir(self):
        """Return the export-folder chooser initial directory for this session.

        Inputs: none. Output: `str`.
        """
        last_selection = getattr(self, "_last_folder_export_selection", "")
        if _safe_is_directory(last_selection):
            return str(last_selection)
        if getattr(self, "_folder_export_initial_path_hint_consumed", False):
            return ""
        path_value = self._current_local_folder_path()
        if (
            path_value
            and path_value == getattr(self, "_folder_path_dir_check_value", "")
            and getattr(self, "_folder_path_dir_check_is_dir", False)
        ):
            return path_value
        return ""

    def _select_folder_for_omero_export(self):
        """Open the native folder chooser for folder export.

        Inputs: none. Output: selected folder path or empty string.
        """
        dialog_options = {
            "parent": self.root,
            "mustexist": True,
            "title": "Select folder to export to OMERO",
        }
        initialdir = self._folder_export_dialog_initialdir()
        if initialdir:
            dialog_options["initialdir"] = initialdir
        self._folder_export_initial_path_hint_consumed = True
        selected_folder = filedialog.askdirectory(**dialog_options)
        if not selected_folder:
            return ""
        selected_text = str(selected_folder)
        self._last_folder_export_selection = selected_text
        return selected_text

    def _export_folder_to_omero(self):
        """Export the selected folder to OMERO for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if self._folder_export_in_progress:
            return
        if getattr(self, "_refresh_in_progress", False):
            self._show_warning_dialog(
                "Refresh In Progress",
                "Please wait for the OMERO browser refresh to finish.",
            )
            return
        if not self._connected or self.client is None:
            self._show_warning_dialog("Not Connected", "Please connect to OMERO first.")
            return
        if not self._folder_export_available:
            self._show_warning_dialog(
                "Export Unavailable",
                self._folder_export_reason
                or "Folder export is not available on this OMERO.web instance.",
            )
            return

        selected_folder = self._select_folder_for_omero_export()
        if not selected_folder:
            return

        if _coerce_path(selected_folder) is None:
            self._show_error_dialog(
                "Invalid Folder",
                "Please select an existing folder.",
            )
            return

        folder_name = _folder_display_name(selected_folder)
        if _is_filesystem_root(selected_folder) or not folder_name:
            self._show_error_dialog(
                "Invalid Folder",
                "Please select a regular folder, not a filesystem root.",
            )
            return

        if not _safe_is_directory(selected_folder):
            self._show_error_dialog(
                "Invalid Folder",
                "Please select an existing folder.",
            )
            return

        confirmation = (
            "Export the selected folder to OMERO root path as a dataset?\n\n"
            f"Dataset name: {folder_name}\n"
            "\n"
            "This will upload every file inside the selected folder."
        )
        if not self._ask_yes_no_dialog("Confirm folder export", confirmation):
            return

        self._set_actions_busy_for_export(True)
        operation_event = getattr(self, "_operation_cancel_event", None)
        operation_generation = getattr(self, "_operation_generation", None)
        worker_args: Tuple[Any, ...] = (selected_folder, folder_name)
        if operation_event is not None and operation_generation is not None:
            worker_args = (*worker_args, operation_event, operation_generation)
        self._set_status("Preparing folder export to OMERO...", "#fff3cd")
        threading.Thread(
            target=self._export_folder_worker,
            args=worker_args,
            daemon=True,
        ).start()

    @staticmethod
    def _folder_export_failure_message(status_payload):
        """Return the folder export failure message for `OMEROBrowserDialog`.

        Inputs: `status_payload`. Output: `str`.
        """
        if isinstance(status_payload, dict):
            errors = [
                str(value).strip()
                for value in list(status_payload.get("errors") or [])
                if str(value).strip()
            ]
            if errors:
                return errors[0]
            messages = [
                str(value).strip()
                for value in list(status_payload.get("messages") or [])
                if str(value).strip()
            ]
            if messages:
                return messages[-1]
        return "OMERO reported that the folder export failed."

    @staticmethod
    def _folder_export_progress_percent(current_value, total_value):
        """Return the folder export progress percent for `OMEROBrowserDialog`.

        Inputs: `current_value`, `total_value`. Output: bounded maximum value.
        """
        try:
            current = float(current_value or 0)
            total = float(total_value or 0)
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None
        return max(0.0, min((current / total) * 100.0, 100.0))

    def _folder_export_status_text(self, folder_name, status_payload):
        """Return the folder export status text for `OMEROBrowserDialog`.

        Inputs: `folder_name`, `status_payload`. Output: status value.
        """
        status = str(status_payload.get("status") or "").strip().lower()
        total_bytes = status_payload.get("total_bytes") or 0

        if status == "uploading":
            percent = self._folder_export_progress_percent(
                status_payload.get("uploaded_bytes"),
                total_bytes,
            )
            if percent is not None:
                return f"Uploading folder to OMERO... {percent:.1f}%"
            return f"Uploading folder '{folder_name}' to OMERO..."

        if status == "checking":
            return "Checking folder export compatibility in OMERO..."
        if status == "awaiting_confirmation":
            return "Waiting for confirmation to continue the OMERO folder export..."
        if status == "ready":
            return "Starting OMERO folder export..."
        if status == "importing":
            percent = self._folder_export_progress_percent(
                status_payload.get("import_progress_bytes")
                or status_payload.get("imported_bytes"),
                total_bytes,
            )
            if percent is not None:
                return f"Exporting folder to OMERO... {percent:.1f}%"
            return f"Exporting folder '{folder_name}' to OMERO..."
        if status == "done":
            return "Folder export completed in OMERO"
        if status == "error":
            return "Folder export failed"
        if status:
            return f"Folder export status: {status}"
        return f"Exporting folder '{folder_name}' to OMERO..."

    def _confirm_folder_export_with_incompatible_files(self, status_payload):
        """Confirm folder export with incompatible files for `OMEROBrowserDialog`.

        Inputs: `status_payload`. Output: `bool`.
        """
        incompatible_files = [
            str(path).strip()
            for path in list(status_payload.get("incompatible_files") or [])
            if str(path).strip()
        ]
        preview = incompatible_files[:FOLDER_EXPORT_CONFIRM_PREVIEW_LIMIT]
        lines = [
            "OMERO reported incompatible files in the selected folder.",
            "",
            "Continue exporting the remaining compatible files?",
        ]
        if preview:
            lines.extend(["", "Incompatible files:"])
            lines.extend(f"- {item}" for item in preview)
            remaining = len(incompatible_files) - len(preview)
            if remaining > 0:
                lines.append(f"- ... and {remaining} more")
        prompt = "\n".join(lines)
        return bool(
            self._invoke_on_ui_thread(
                lambda: self._ask_yes_no_dialog(
                    "Confirm Compatible OMERO Export",
                    prompt,
                )
            )
        )

    def _wait_for_folder_export_completion(
        self,
        folder_name,
        status_url,
        confirm_url,
        cancel_event=None,
    ):
        """Wait for folder export completion for `OMEROBrowserDialog`.

        Inputs: `folder_name`, `status_url`, `confirm_url`. Output: `status_payload`.
        Raises: RuntimeError when validation or the called operation fails.
        """
        deadline = time.time() + FOLDER_EXPORT_TIMEOUT
        while time.time() < deadline:
            self._raise_if_current_operation_cancelled("Folder export", cancel_event)
            status_payload = self.client.get_folder_export_status(status_url)
            self._set_status(
                self._folder_export_status_text(folder_name, status_payload),
                "#fff3cd",
            )
            status = str(status_payload.get("status") or "").strip().lower()
            if status == "done":
                return status_payload
            if status == "error":
                raise RuntimeError(self._folder_export_failure_message(status_payload))
            if status_payload.get("confirmation_required"):
                if not self._confirm_folder_export_with_incompatible_files(
                    status_payload
                ):
                    raise RuntimeError(
                        "Folder export was cancelled after OMERO reported incompatible files."
                    )
                self._raise_if_current_operation_cancelled(
                    "Folder export",
                    cancel_event,
                )
                self._set_status("Confirming compatible OMERO export...", "#fff3cd")
                self.client.confirm_folder_export(confirm_url)
            _wait_for_cancel_or_timeout(
                cancel_event
                if cancel_event is not None
                else getattr(self, "_operation_cancel_event", None),
                FOLDER_EXPORT_POLL_INTERVAL,
                "Folder export",
            )

        raise RuntimeError("Folder export timed out while waiting for OMERO.")

    def _export_folder_worker(
        self,
        selected_folder,
        folder_name,
        operation_event=None,
        operation_generation=None,
    ):
        """Export the folder through the OMERO.web folder export workflow.

        Inputs: `selected_folder`, `folder_name`. Output: None. Raises: RuntimeError
        when validation or the called operation fails.
        """
        cancel_event = (
            operation_event
            if operation_event is not None
            else getattr(self, "_operation_cancel_event", None)
        )
        export_succeeded = False
        export_cancelled = False
        job_payload = None
        try:
            self._raise_if_current_operation_cancelled("Folder export", cancel_event)
            self._set_status("Scanning selected folder...", "#fff3cd")
            local_entries = _collect_local_folder_entries(selected_folder)
            self._raise_if_current_operation_cancelled("Folder export", cancel_event)
            total_bytes = sum(int(entry.get("size") or 0) for entry in local_entries)
            _xt_debug(
                "Folder export starting "
                f"dataset_name={folder_name!r} file_count={len(local_entries)} "
                f"total_bytes={total_bytes}"
            )

            self._set_status("Creating OMERO upload job...", "#fff3cd")
            job_payload = self.client.start_folder_export_job(
                folder_name, local_entries
            )
            self._raise_if_current_operation_cancelled("Folder export", cancel_event)
            if self._operation_is_current(operation_event, operation_generation):
                self._active_folder_export_job = job_payload
            upload_url = job_payload.get("upload_url")
            import_step_url = job_payload.get("import_step_url")
            status_url = job_payload.get("status_url")
            confirm_url = job_payload.get("confirm_url")
            prune_url = job_payload.get("prune_url")

            if (
                not upload_url
                or not import_step_url
                or not status_url
                or not confirm_url
                or not prune_url
            ):
                raise RuntimeError(
                    "OMERO returned an incomplete folder-export job response."
                )

            chunk_size = _upload_chunk_size_bytes()
            uploaded_bytes = 0
            file_count = len(local_entries)

            for file_index, entry in enumerate(local_entries, start=1):
                self._raise_if_current_operation_cancelled(
                    "Folder export",
                    cancel_event,
                )
                absolute_path = entry.get("absolute_path")
                relative_path = entry.get("relative_path")
                file_size = int(entry.get("size") or 0)
                if not absolute_path or not relative_path:
                    raise RuntimeError("A selected file entry is incomplete.")

                display_name = PurePosixPath(relative_path).name or relative_path
                with open(absolute_path, "rb") as handle:
                    chunk_start = 0
                    sent_empty_file = False
                    while True:
                        self._raise_if_current_operation_cancelled(
                            "Folder export",
                            cancel_event,
                        )
                        chunk = handle.read(chunk_size)
                        if not chunk:
                            if file_size == 0 and not sent_empty_file:
                                chunk = b""
                                sent_empty_file = True
                                is_last_chunk = True
                            else:
                                break
                        else:
                            is_last_chunk = chunk_start + len(chunk) >= file_size

                        projected_uploaded = uploaded_bytes + len(chunk)
                        percent = (
                            100.0
                            if total_bytes <= 0
                            else max(
                                0.0,
                                min(
                                    (projected_uploaded / float(total_bytes)) * 100.0,
                                    100.0,
                                ),
                            )
                        )
                        self._set_status(
                            (
                                "Uploading folder to OMERO... "
                                f"{percent:.1f}% ({file_index}/{file_count}: {display_name})"
                            ),
                            "#fff3cd",
                        )
                        self.client.upload_folder_chunk(
                            upload_url,
                            relative_path,
                            file_size,
                            chunk_start,
                            chunk,
                            is_last_chunk,
                        )
                        self._raise_if_current_operation_cancelled(
                            "Folder export",
                            cancel_event,
                        )
                        chunk_start += len(chunk)
                        uploaded_bytes += len(chunk)
                        if is_last_chunk:
                            break

                if chunk_start != file_size:
                    raise RuntimeError(
                        f"Folder upload size verification failed for {relative_path}."
                    )

            self._raise_if_current_operation_cancelled("Folder export", cancel_event)
            self._set_status("Starting OMERO folder export...", "#fff3cd")
            self.client.trigger_folder_export(import_step_url)
            final_status = self._wait_for_folder_export_completion(
                folder_name,
                status_url,
                confirm_url,
                cancel_event=cancel_event,
            )

            incompatible_files = list(final_status.get("incompatible_files") or [])
            if incompatible_files:
                skipped_count = len(incompatible_files)
                self._set_status(
                    "Folder export completed with compatibility skips",
                    "#fff3cd",
                )
                self._show_info(
                    "Folder Export Completed",
                    (
                        f"The folder was exported to OMERO root path as dataset "
                        f"'{folder_name}'.\n\n"
                        f"{skipped_count} incompatible "
                        f"{_pluralize(skipped_count, 'file')} "
                        f"{_pluralize(skipped_count, 'was', 'were')} skipped."
                    ),
                )
            else:
                self._set_status("Folder export completed in OMERO", "#d4edda")
                self._show_info(
                    "Folder Export Completed",
                    (
                        f"The folder was exported to OMERO root path as dataset "
                        f"'{folder_name}'."
                    ),
                )
            export_succeeded = True
        except _ConnectorOperationCancelled as exc:
            export_cancelled = True
            if job_payload:
                self.client.cancel_folder_export_job(job_payload)
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("Folder export stopped by user", "#fff3cd")
            _xt_debug(f"Folder export stopped by user in background: {exc}")
        except Exception as exc:
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("Folder export failed", "#f8d7da")
                self._show_error("Folder Export Failed", str(exc))
                _xt_debug(f"Folder export failed: {type(exc).__name__}: {exc}")
            else:
                _xt_debug(
                    "Stopped folder export background worker failed: "
                    f"{type(exc).__name__}: {exc}"
                )
        finally:
            if self._operation_is_current(operation_event, operation_generation):
                self._active_folder_export_job = None
                self._invoke_on_ui_thread(
                    partial(
                        self._finish_export_workflow,
                        export_succeeded,
                        export_cancelled,
                    ),
                    wait=False,
                )
            else:
                _xt_debug("Stopped folder export background worker finished.")

    def _hide_converter_frame(self):
        """Hide the converter frame for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self.converter_frame.pack_forget()

    def _align_connection_panel_right_controls(self):
        """Align fixed connection-panel controls.

        Inputs: none. Output: None.
        """
        root = getattr(self, "root", None)
        if root is not None:
            _call_if_available(root, "update_idletasks")
        converter_slot = getattr(self, "converter_slot", None)
        if converter_slot is not None:
            converter_slot.config(width=CONVERTER_SLOT_WIDTH)
            converter_slot.grid_configure(padx=(34, 0))
        converter_text_spacer = getattr(self, "converter_text_offset_spacer", None)
        autosave_check = getattr(self, "autosave_settings_check", None)
        if converter_text_spacer is not None and autosave_check is not None:
            converter_text_spacer.config(width=_checkbutton_text_offset(autosave_check))
        panel_icon_frame = getattr(self, "panel_icon_frame", None)
        if panel_icon_frame is not None:
            panel_icon_frame.grid_configure(padx=(12, 0))

    def _align_path_row_control_heights(self):
        """Match path-row command controls to the rendered path entry height.

        Inputs: none. Output: None.
        """
        root = getattr(self, "root", None)
        if root is not None:
            _call_if_available(root, "update_idletasks")
        entry_height = _safe_widget_dimension(
            getattr(self, "folder_path_entry", None), "winfo_height"
        )
        if entry_height <= 0:
            return
        for control in (
            getattr(self, "select_folder_btn", None),
            getattr(self, "refresh_btn", None),
            getattr(self, "converter_dropdown", None),
        ):
            configure = getattr(control, "config", None)
            if callable(configure):
                configure(height=entry_height)
        converter_slot = getattr(self, "converter_slot", None)
        if converter_slot is not None:
            converter_slot.config(height=entry_height)

    def _show_converter_frame(self):
        """Show the converter frame for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._align_connection_panel_right_controls()
        self._align_path_row_control_heights()
        pack = getattr(self.converter_frame, "pack", None)
        if callable(pack):
            pack(
                side=tk.LEFT,
                fill=tk.BOTH,
                expand=True,
                padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0),
            )
            return
        grid = getattr(self.converter_frame, "grid", None)
        if callable(grid):
            grid()

    def _set_connect_button(self, text, state, bg, active_bg=None):
        """Set the connect button for `OMEROBrowserDialog`.

        Inputs: `text`, `state`, `bg`, `active_bg`. Output: None.
        """
        self.connect_btn.config(
            text=text,
            state=state,
            bg=bg,
            activebackground=active_bg or bg,
            fg="white",
            activeforeground="white",
        )
        self._sync_action_button_cursors()

    def _toggle_connection(self):
        """Toggle the connection for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if self._connection_in_progress:
            return
        if self._connected:
            self._disconnect()
            return
        self._connect()

    @staticmethod
    def _clear_client_session_state(client):
        """Clear retained sensitive session state from an OMERO.web client.

        Inputs: `client`. Output: None.
        """
        if client is None:
            return
        cookie_jar = getattr(client, "cookie_jar", None)
        if cookie_jar is not None:
            with contextlib.suppress(Exception):
                cookie_jar.clear()
        for attr, value in (
            ("password", ""),
            ("csrf_token", None),
            ("session_id", None),
            ("session_key", None),
            ("user_id", None),
        ):
            with contextlib.suppress(Exception):
                setattr(client, attr, value)

    def _disconnect(
        self,
        status_text="Disconnected",
        status_color=STATUS_NEUTRAL_BG,
        clear_password=True,
    ):
        """The current OMERO.web session and reset browser state.

        Inputs: optional status text/color and password-clear flag. Output: None.
        """
        self._cancel_health_ping()
        if self.client is not None:
            try:
                if self.client.cookie_jar is not None:
                    self.client.cookie_jar.clear()
            except Exception as exc:
                _xt_debug(
                    f"Suppressed cookie-jar clear failure during disconnect: {exc}"
                )
            self.client.password = CLEARED_CREDENTIAL_TEXT
            self.client.csrf_token = None
            self.client.session_id = None
            self.client.session_key = None
            self.client.user_id = None
        self.client = None
        self._connected = False
        self._set_password_entry_interactive(True)
        self._pid = None
        self._did = None
        self._refresh_generation += 1
        self._refresh_in_progress = False
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
        self._all_projects_data = []
        self._all_datasets_data = []
        self._all_images_data = []
        self._image_selection_anchor = None
        self._set_folder_export_capability(False, "Connect to OMERO first.")
        self.plist.delete(0, _tk_constant("END", "end"))
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        if clear_password:
            self._clear_password_entry()
        self._set_converter_options([])
        self._set_connect_button(
            "Connect",
            _tk_constant("NORMAL", "normal"),
            "#3498db",
            active_bg="#2f85c7",
        )
        self._set_autosave_settings_control_state(False)
        self._set_status(status_text, status_color)
        self._set_connection_indicator("disconnected")
        self._set_browser_interaction_state(False)

    def _detect_converter_options_after_connection(self, client=None):
        """Populate converter options from verified OMERO and Imaris capabilities.

        Inputs: optional OMERO.web `client`. Output: `options`.
        """
        if client is None:
            client = self.client
        can_attempt_imaris_handoff = self._has_imaris_converter_handoff_target()
        options = []
        omero_available = False
        if client:
            omero_available = client.has_omero_ims_export_capability()
        if omero_available:
            options.append("OMERO")
        if can_attempt_imaris_handoff:
            options.append("Imaris")
        _xt_debug(f"Detected converter options after connection: {options}")
        return options

    def _has_imaris_handoff_target(self):
        """Return whether this XT session can attempt an Imaris file handoff.

        Inputs: none. Output: bool.
        """
        if _imaris_application_handle_is_live(getattr(self, "imaris", None)):
            return True
        self.imaris = None
        return _coerce_imaris_id(getattr(self, "imaris_id", None)) is not None

    def _has_imaris_converter_handoff_target(self):
        """Return whether selected-image exports can be submitted to Imaris.

        Inputs: none. Output: bool.
        """
        return _find_imaris_file_converter_executable() is not None

    def _detect_folder_export_after_connection(self, client=None):
        """Detect folder export availability after connection.

        Inputs: optional OMERO.web `client`. Output: `capability`.
        """
        if client is None:
            client = self.client
        if not client:
            return {"available": False, "reason": "No OMERO.web client is available."}
        capability = client.get_folder_export_capability()
        _xt_debug(
            "Detected OMERO folder export capability "
            f"available={bool(capability.get('available'))}"
        )
        return capability

    @staticmethod
    def _get_export_dir():
        """Return export dir.

        Inputs: none. Output: `export_dir`.
        """
        configured = os.environ.get("OMERO_IMARIS_EXPORT_DIR", "").strip()
        configured_path = _coerce_path(configured) if configured else None
        if configured_path is not None and configured_path.is_absolute():
            export_dir = str(configured_path)
            os.makedirs(export_dir, exist_ok=True)
            return export_dir
        base = tempfile.gettempdir()
        export_dir = os.path.join(base, "ImarisOMEROExports")
        os.makedirs(export_dir, exist_ok=True)
        return export_dir

    def _set_status(self, text, color=STATUS_NEUTRAL_BG):
        """Set the status for `OMEROBrowserDialog`.

        Inputs: `text`, `color`. Output: None.
        """

        def update():
            """Refresh the UI state.

            Inputs: no caller arguments. Output: performs the documented action and returns None.
            """
            self.status.config(text=text, bg=color)

        self.root.after(0, update)

    def _draw_connection_indicator(self, state):
        """Draw a compact status indicator in the bottom status row.

        Inputs: `state`. Output: None.
        """
        canvas = getattr(self, "connection_indicator", None)
        if canvas is None:
            return
        palette = {
            "connected": "#1f9d55",
            "busy": "#2f80ed" if self._indicator_blink_on else "#93c5fd",
            "error": "#d64545",
            "disconnected": "#8a949e",
        }
        fill = palette.get(state, palette["disconnected"])
        canvas.delete("all")
        canvas.create_oval(6, 4, 28, 26, fill=fill, outline="#ffffff", width=1)

    def _set_connection_indicator(self, state):
        """Set the connection indicator for `OMEROBrowserDialog`.

        Inputs: `state`. Output: None.
        """
        ui_thread_id = getattr(self, "_ui_thread_id", None)
        root = getattr(self, "root", None)
        if (
            ui_thread_id is not None
            and threading.get_ident() != ui_thread_id
            and root is not None
            and hasattr(root, "after")
        ):
            self.root.after(0, lambda: self._set_connection_indicator(state))
            return
        self._indicator_state = state
        self._indicator_blink_on = state == "busy" and getattr(
            self,
            "_indicator_blink_on",
            False,
        )
        self._draw_connection_indicator(state)
        indicator_after_id: Optional[str] = getattr(self, "_indicator_after_id", None)
        if (
            indicator_after_id is not None
            and root is not None
            and hasattr(root, "after_cancel")
        ):
            try:
                root.after_cancel(indicator_after_id)
            except Exception as exc:
                _xt_debug(f"Indicator timer cancellation failed: {exc}")
            self._indicator_after_id = None
        if state == "busy" and root is not None and hasattr(root, "after"):
            self._schedule_indicator_blink()

    def _cancel_indicator_blink(self):
        """Cancel pending indicator animation callbacks.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._indicator_state = "disconnected"
        self._indicator_blink_on = False
        indicator_after_id: Optional[str] = getattr(self, "_indicator_after_id", None)
        if indicator_after_id is not None:
            try:
                self.root.after_cancel(indicator_after_id)
            except Exception as exc:
                _xt_debug(f"Indicator timer cancellation failed: {exc}")
            self._indicator_after_id = None

    def _schedule_indicator_blink(self):
        """Keep the busy indicator blinking while work is active.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if self._indicator_state != "busy":
            return
        root = getattr(self, "root", None)
        if root is None or not hasattr(root, "after"):
            return
        self._indicator_blink_on = not self._indicator_blink_on
        self._draw_connection_indicator("busy")
        self._indicator_after_id = self.root.after(650, self._schedule_indicator_blink)

    def _restore_idle_connection_indicator(self):
        """Restore the indicator after foreground work completes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if getattr(self, "_connected", False):
            self._set_connection_indicator("connected")
        else:
            self._set_connection_indicator("disconnected")

    def _sync_action_button_cursors(self):
        """Restore hand cursors on custom connector buttons after modal locks.

        Inputs: none. Output: None.
        """
        for name in (
            "connect_btn",
            "load_btn",
            "export_btn",
            "stop_btn",
            "close_btn",
            "refresh_btn",
        ):
            sync = getattr(getattr(self, name, None), "_sync_cursor", None)
            if callable(sync):
                sync()

    def _reset_background_cursor_after_silent_work(self):
        """Restore the main-window background cursor after silent background work.

        Inputs: no caller arguments. Output: None.
        """
        if (
            getattr(self, "_connection_in_progress", False)
            or getattr(self, "_folder_export_in_progress", False)
            or getattr(self, "_load_in_progress", False)
            or getattr(self, "_modal_background_lock_depth", 0) > 0
            or getattr(self, "_browser_sash_drag_index", None) is not None
        ):
            return
        root = getattr(self, "root", None)
        setter = getattr(root, "configure", None) or getattr(root, "config", None)
        if not callable(setter):
            return
        try:
            setter(cursor="")
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py",
                exc_info=exc,
            )
        self._sync_action_button_cursors()

    def _request_background_cursor_reset(self):
        """Schedule a safe background cursor reset on the UI thread.

        Inputs: none. Output: None.
        """
        invoker = getattr(self, "_invoke_on_ui_thread", None)
        if callable(invoker):
            try:
                invoker(self._reset_background_cursor_after_silent_work, wait=False)
                return
            except Exception:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=True,
                )
        self._reset_background_cursor_after_silent_work()

    def _schedule_health_ping(self):
        """Schedule a read-only connection health check.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if (
            not getattr(self, "_connected", False)
            or getattr(self, "client", None) is None
        ):
            return
        if self._health_ping_after_id is not None:
            try:
                self.root.after_cancel(self._health_ping_after_id)
            except Exception as exc:
                _xt_debug(f"Health ping timer cancellation failed: {exc}")
        interval_ms = int(_health_ping_interval_seconds() * 1000)
        self._health_ping_after_id = self.root.after(
            interval_ms, self._start_health_ping
        )

    def _cancel_health_ping(self):
        """Cancel pending health checks and invalidate in-flight ping results.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._health_ping_generation += 1
        self._health_ping_in_progress = False
        if self._health_ping_after_id is not None:
            try:
                self.root.after_cancel(self._health_ping_after_id)
            except Exception as exc:
                _xt_debug(f"Health ping timer cancellation failed: {exc}")
            self._health_ping_after_id = None

    def _start_health_ping(self):
        """Start the health ping for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: starts the described state and returns None.
        """
        self._health_ping_after_id = None
        if (
            not getattr(self, "_connected", False)
            or self.client is None
            or self._health_ping_in_progress
        ):
            return
        self._health_ping_in_progress = True
        self._health_ping_generation += 1
        generation = self._health_ping_generation
        self._reset_background_cursor_after_silent_work()
        threading.Thread(
            target=self._health_ping_worker,
            args=(generation,),
            daemon=True,
        ).start()

    def _health_ping_worker(self, generation):
        """The read-only health check.

        Inputs: `generation`. Output: None.
        """
        error = None
        client = self.client
        attempts = _health_ping_retry_attempts()
        retry_delay = _health_ping_retry_delay_seconds()
        for attempt in range(attempts):
            if generation != self._health_ping_generation:
                return
            try:
                client.ping(timeout=_health_ping_timeout_seconds())
                error = None
                break
            except Exception as exc:
                error = exc
                if attempt + 1 < attempts and retry_delay > 0:
                    time.sleep(retry_delay)
        self._invoke_on_ui_thread(
            lambda: self._finish_health_ping(generation, error),
            wait=False,
        )

    def _finish_health_ping(self, generation, error):
        """Apply the health-check result without reconnecting or disconnecting.

        Inputs: `generation`, `error`. Output: None.
        """
        if generation != self._health_ping_generation:
            return
        self._health_ping_in_progress = False
        self._reset_background_cursor_after_silent_work()
        if not getattr(self, "_connected", False):
            self._set_connection_indicator("disconnected")
            return
        if error is None:
            if self._indicator_state != "busy":
                self._set_connection_indicator("connected")
        else:
            self._handle_health_ping_failure(error)
            return
        self._schedule_health_ping()

    def _handle_health_ping_failure(self, error):
        """Report a verified lost OMERO connection and return to connect-ready UI.

        Inputs: `error`. Output: None.
        """
        _xt_debug(
            f"Read-only OMERO health check failed after retries: {type(error).__name__}"
        )
        self._disconnect(
            status_text="Connection lost - Ready to connect",
            status_color="#f8d7da",
            clear_password=False,
        )
        self._show_error_dialog(
            "Connection Lost",
            "The OMERO connection was lost. Please reconnect to continue.",
        )

    def _show_error(self, title, message):
        """Show the error for `OMEROBrowserDialog`.

        Inputs: `title`, `message`. Output: None.
        """
        self.root.after(0, lambda: self._show_error_dialog(title, message))

    def _show_info(self, title, message):
        """Show the info for `OMEROBrowserDialog`.

        Inputs: `title`, `message`. Output: None.
        """
        self.root.after(0, lambda: self._show_info_dialog(title, message))

    def _show_connector_help(self):
        """Show the modal OMERO connector help window.

        Inputs: none. Output: None.
        """

        def _show_modal():
            """Build and show the blocking connector help dialog.

            Inputs: none. Output: None.
            """
            help_window = tk.Toplevel(self.root)
            help_window.title(CONNECTOR_HELP_TITLE)
            _apply_omero_window_icon(
                help_window, getattr(self, "_window_icon_image", None)
            )
            help_window.resizable(False, False)
            help_window.transient(self.root)
            help_window.configure(bg="#f8fafc")

            frame = tk.Frame(help_window, padx=22, pady=18, bg="#f8fafc")
            frame.grid(row=0, column=0, sticky=tk.NSEW)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_columnconfigure(1, weight=0)

            row_index = 0
            for section_title, section_lines in CONNECTOR_HELP_SECTIONS:
                tk.Label(
                    frame,
                    text=section_title,
                    font=("Arial", 10, "bold"),
                    bg="#f8fafc",
                    fg="#1f2937",
                    anchor=tk.W,
                    justify=tk.LEFT,
                ).grid(row=row_index, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
                row_index += 1
                for line in section_lines:
                    tk.Label(
                        frame,
                        text=f"- {line}",
                        font=("Arial", 9),
                        bg="#f8fafc",
                        fg="#374151",
                        anchor=tk.W,
                        justify=tk.LEFT,
                        wraplength=660,
                    ).grid(
                        row=row_index,
                        column=0,
                        columnspan=2,
                        sticky=tk.W,
                        pady=1,
                    )
                    row_index += 1

            def _close_help_window():
                """Close only the connector help child window.

                Inputs: none. Output: None.
                """
                with contextlib.suppress(Exception):
                    help_window.grab_release()
                help_window.destroy()

            close_button = tk.Button(
                frame,
                text="Close",
                command=_close_help_window,
                font=("Arial", 9),
                width=10,
                default=_tk_constant("ACTIVE", "active"),
            )
            close_button.grid(
                row=row_index,
                column=1,
                sticky=tk.SE,
                padx=(18, 0),
                pady=(14, 0),
            )

            help_window.protocol("WM_DELETE_WINDOW", _close_help_window)
            help_window.update_idletasks()
            parent_x = int(self.root.winfo_rootx() or 0)
            parent_y = int(self.root.winfo_rooty() or 0)
            parent_w = int(self.root.winfo_width() or 0)
            parent_h = int(self.root.winfo_height() or 0)
            width = max(int(help_window.winfo_reqwidth() or 0), 740)
            height = int(help_window.winfo_reqheight() or 0)
            x_pos = parent_x + max(0, (parent_w - width) // 2)
            y_pos = parent_y + max(0, (parent_h - height) // 2)
            help_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
            close_button.focus_set()
            help_window.grab_set()
            self.root.wait_window(help_window)

        _show_modal()

    def _show_connector_info(self):
        """Show the modal OMERO connector information window.

        Inputs: none. Output: None.
        """

        def _show_modal():
            """Build and show the blocking connector information dialog.

            Inputs: none. Output: None.
            """
            info_window = tk.Toplevel(self.root)
            info_window.title(CONNECTOR_INFO_TITLE)
            _apply_omero_window_icon(
                info_window, getattr(self, "_window_icon_image", None)
            )
            info_window.resizable(False, False)
            info_window.transient(self.root)
            info_window.configure(bg="#f8fafc")

            frame = tk.Frame(info_window, padx=18, pady=16, bg="#f8fafc")
            frame.grid(row=0, column=0, sticky=tk.NSEW)
            frame.grid_columnconfigure(0, weight=0)
            frame.grid_columnconfigure(1, weight=1)
            frame.grid_columnconfigure(2, weight=0)

            disclaimer = tk.Label(
                frame,
                text=CONNECTOR_INFO_DISCLAIMER,
                font=("Arial", 9),
                bg="#f8fafc",
                fg="#374151",
                anchor=tk.W,
                justify=tk.LEFT,
                wraplength=390,
            )
            disclaimer.grid(
                row=0,
                column=0,
                columnspan=3,
                sticky=tk.EW,
                pady=0,
            )

            metadata_label_font = ("Arial", 9, "bold")
            metadata_value_font = ("Arial", 9)
            metadata_rows = (
                ("Original developer:", CONNECTOR_INFO_AUTHOR),
                ("Version:", CONNECTOR_INFO_VERSION),
            )
            for row_index, (label_text, value_text) in enumerate(
                metadata_rows, start=1
            ):
                tk.Label(
                    frame,
                    text=label_text,
                    font=metadata_label_font,
                    bg="#f8fafc",
                    fg="#1f2937",
                    anchor=tk.W,
                ).grid(row=row_index, column=0, sticky=tk.W, pady=0)
                tk.Label(
                    frame,
                    text=value_text,
                    font=metadata_value_font,
                    bg="#f8fafc",
                    fg="#1f2937",
                    anchor=tk.W,
                ).grid(row=row_index, column=1, sticky=tk.W, padx=(4, 0), pady=0)

            def _close_info_window():
                """Close only the connector information child window.

                Inputs: none. Output: None.
                """
                with contextlib.suppress(Exception):
                    info_window.grab_release()
                info_window.destroy()

            close_button = tk.Button(
                frame,
                text="Close",
                command=_close_info_window,
                font=("Arial", 9),
                width=10,
                default=_tk_constant("ACTIVE", "active"),
            )
            close_button.grid(row=3, column=2, sticky=tk.SE, padx=(18, 0), pady=(10, 0))

            info_window.protocol("WM_DELETE_WINDOW", _close_info_window)
            info_window.update_idletasks()
            parent_x = int(self.root.winfo_rootx() or 0)
            parent_y = int(self.root.winfo_rooty() or 0)
            parent_w = int(self.root.winfo_width() or 0)
            parent_h = int(self.root.winfo_height() or 0)
            width = int(info_window.winfo_reqwidth() or 0)
            height = int(info_window.winfo_reqheight() or 0)
            x_pos = parent_x + max(0, (parent_w - width) // 2)
            y_pos = parent_y + max(0, (parent_h - height) // 2)
            info_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
            close_button.focus_set()
            info_window.grab_set()
            self.root.wait_window(info_window)

        _show_modal()

    def _invoke_on_ui_thread(self, callback, wait=True):
        """A callback on Tk's UI thread and optionally wait for the result.

        Inputs: `callback`, `wait`. Output: invoke on ui thread result. Raises: error
        when validation or the called operation fails.
        """
        value: Any = None
        error: Optional[BaseException] = None
        completed = threading.Event()

        def runner():
            """The callback and capture its result.

            Inputs: no caller arguments. Output: performs the documented action and returns None.
            """
            nonlocal error, value
            try:
                value = callback()
            except Exception as exc:
                error = exc
            finally:
                completed.set()

        self.root.after(0, runner)
        if not wait:
            return None
        completed.wait()
        if error is not None:
            raise error
        return value

    def _get_native_bridge_python_executable(self):
        """Return native bridge python executable.

        Inputs: none. Output: `self._native_bridge_python_executable`.
        """
        with self._native_bridge_probe_lock:
            return self._native_bridge_python_executable

    def _open_with_native_bridge_runner(
        self,
        downloaded_file,
        require_ims=True,
        allow_when_disabled=False,
    ):
        """Open the with native bridge runner for `OMEROBrowserDialog`.

        Inputs: `downloaded_file`, `require_ims`, `allow_when_disabled`. Output:
        `_open_file_in_imaris_with_native_bridge_runner` result.
        """
        bridge_python = self._get_native_bridge_python_executable()
        return _open_file_in_imaris_with_native_bridge_runner(
            downloaded_file,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
            allow_when_disabled=allow_when_disabled,
        )

    def _open_files_with_native_bridge_runner(
        self,
        downloaded_files,
        require_ims=True,
        allow_when_disabled=False,
    ):
        """Open the files with native bridge runner for `OMEROBrowserDialog`.

        Inputs: `downloaded_files`, `require_ims`, `allow_when_disabled`. Output:
        `_open_files_in_imaris_with_native_bridge_runner` result.
        """
        bridge_python = self._get_native_bridge_python_executable()
        return _open_files_in_imaris_with_native_bridge_runner(
            downloaded_files,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
            allow_when_disabled=allow_when_disabled,
        )

    def _resolve_direct_imaris_handle_for_handoff(self):
        """Resolve the normal XT Imaris handle for a same-session file handoff.

        Inputs: none. Output: bool.
        """
        if _imaris_application_handle_is_live(getattr(self, "imaris", None)):
            return True
        self.imaris = None
        if _coerce_imaris_id(getattr(self, "imaris_id", None)) is None:
            return False

        def _resolve_on_current_thread():
            """Resolve and cache the current Imaris application handle.

            Inputs: none. Output: bool.
            """
            if _imaris_application_handle_is_live(getattr(self, "imaris", None)):
                return True
            self.imaris = None
            _xt_debug("Attempting direct Imaris XT handle acquisition")
            resolved = _resolve_imaris_application(
                self.imaris_id,
                retries=IMARIS_HANDLE_RETRY_ATTEMPTS,
                retry_interval=IMARIS_HANDLE_RETRY_INTERVAL,
            )
            if _imaris_application_handle_is_live(resolved):
                self.imaris = resolved
                _xt_debug("Resolved direct Imaris XT handle for current session")
                return True
            self.imaris = None
            return False

        if threading.get_ident() == getattr(self, "_ui_thread_id", None):
            return _resolve_on_current_thread()
        invoker = getattr(self, "_invoke_on_ui_thread", None)
        root_after = getattr(getattr(self, "root", None), "after", None)
        if callable(invoker) and callable(root_after):
            return bool(invoker(_resolve_on_current_thread))
        return _resolve_on_current_thread()

    def _open_downloaded_file_in_imaris(
        self,
        downloaded_file,
        require_ims=True,
        selected_image_export=False,
    ):
        """Open one downloaded connector file in the connected Imaris application.

        Inputs: `downloaded_file`, `require_ims`, `selected_image_export`. Output:
        `bool`.
        """
        if selected_image_export and not self._is_tracked_selected_image_export_file(
            downloaded_file
        ):
            _xt_debug(
                "Imaris converter: refusing to open an untracked selected-image export"
            )
            return False

        if selected_image_export:
            self._set_status(
                "Submitting selected Image export to Imaris File Converter...",
                "#fff3cd",
            )
            return submit_selected_image_export_to_imaris_converter(downloaded_file)

        self._set_status("Opening IMS in Imaris...", "#fff3cd")
        native_bridge_enabled = _native_imaris_bridge_enabled()
        if not _imaris_application_handle_is_live(getattr(self, "imaris", None)):
            self.imaris = None

        if (
            native_bridge_enabled
            and self.imaris is None
            and self._get_native_bridge_python_executable()
        ):
            _xt_debug(
                "Opening file in the current Imaris session via compatible native bridge runner"
            )
            return self._open_with_native_bridge_runner(
                downloaded_file,
                require_ims=require_ims,
            )

        if self.imaris is None:
            _xt_debug(
                "Direct Imaris handle is not available in this Python; "
                "attempting UI-thread acquisition"
            )
            self._resolve_direct_imaris_handle_for_handoff()

        if self.imaris is None and _coerce_imaris_id(self.imaris_id) is not None:
            _xt_debug(
                "Direct Imaris handle remains unavailable in this Python; "
                "trying compatible native bridge runner for final same-session open"
            )
            if self._open_with_native_bridge_runner(
                downloaded_file,
                require_ims=require_ims,
                allow_when_disabled=not native_bridge_enabled,
            ):
                return True
            if not native_bridge_enabled:
                return False
        elif self.imaris is None:
            _xt_debug(
                "Direct Imaris handle remains unavailable and no numeric XT "
                "application id is available for same-session handoff"
            )
        else:
            _xt_debug(
                f"Using Imaris handle type={type(self.imaris).__name__} for file open"
            )

        if self.imaris is not None:
            if open_file_in_imaris(
                downloaded_file,
                self.imaris,
                require_ims=require_ims,
            ):
                return True

        if not native_bridge_enabled:
            return False

        _xt_debug(
            "Direct Imaris handle path did not open the file; "
            "trying compatible native bridge runner"
        )
        if self._open_with_native_bridge_runner(
            downloaded_file,
            require_ims=require_ims,
        ):
            return True

        _xt_debug("Native bridge runner did not open the file in the live XT session")
        return False

    def _open_downloaded_files_in_imaris(
        self,
        downloaded_files,
        require_ims=True,
        selected_image_export=False,
    ):
        """Open downloaded connector files in the connected Imaris application.

        Inputs: `downloaded_files`, `require_ims`, `selected_image_export`. Output:
        `bool`.
        """
        downloaded_files = list(downloaded_files or [])
        if not downloaded_files:
            return False
        if len(downloaded_files) == 1:
            return self._open_downloaded_file_in_imaris(
                downloaded_files[0],
                require_ims=require_ims,
                selected_image_export=selected_image_export,
            )
        if selected_image_export and any(
            not self._is_tracked_selected_image_export_file(path)
            for path in downloaded_files
        ):
            _xt_debug(
                "Imaris converter: refusing to open an untracked selected-image "
                "export batch"
            )
            return False

        if selected_image_export:
            self._set_status(
                "Submitting selected Image exports to Imaris File Converter...",
                "#fff3cd",
            )
            return submit_selected_image_exports_to_imaris_converter(downloaded_files)

        self._set_status("Opening selected files in Imaris...", "#fff3cd")
        native_bridge_enabled = _native_imaris_bridge_enabled()
        if not _imaris_application_handle_is_live(getattr(self, "imaris", None)):
            self.imaris = None

        if (
            native_bridge_enabled
            and self.imaris is None
            and self._get_native_bridge_python_executable()
        ):
            _xt_debug(
                "Opening selected files in the current Imaris session via "
                "compatible native bridge runner"
            )
            return self._open_files_with_native_bridge_runner(
                downloaded_files,
                require_ims=require_ims,
            )

        if self.imaris is None:
            _xt_debug(
                "Direct Imaris handle is not available in this Python; "
                "attempting UI-thread acquisition for batch open"
            )
            self._resolve_direct_imaris_handle_for_handoff()

        if self.imaris is None and _coerce_imaris_id(self.imaris_id) is not None:
            _xt_debug(
                "Direct Imaris handle remains unavailable in this Python; "
                "trying compatible native bridge runner for final batch open"
            )
            if self._open_files_with_native_bridge_runner(
                downloaded_files,
                require_ims=require_ims,
                allow_when_disabled=not native_bridge_enabled,
            ):
                return True
            if not native_bridge_enabled:
                return False
        elif self.imaris is None:
            _xt_debug(
                "Direct Imaris handle remains unavailable and no numeric XT "
                "application id is available for batch handoff"
            )

        if self.imaris is not None:
            if open_files_in_imaris(
                downloaded_files,
                self.imaris,
                require_ims=require_ims,
            ):
                return True

        if not native_bridge_enabled:
            return False

        _xt_debug(
            "Direct Imaris handle path did not complete the batch open; "
            "trying compatible native bridge runner"
        )
        if self._open_files_with_native_bridge_runner(
            downloaded_files,
            require_ims=require_ims,
        ):
            return True

        _xt_debug(
            "Native bridge runner did not complete the batch open in the live XT "
            "session"
        )
        return False

    def _start_native_bridge_probe(self):
        """Probe native Imaris opening capability in the background.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if not _native_imaris_bridge_enabled():
            with self._native_bridge_probe_lock:
                self._native_bridge_probe_in_progress = False
                self._native_bridge_probe_started = True
                self._native_bridge_available = _imaris_application_handle_is_live(
                    getattr(self, "imaris", None)
                )
                self._native_bridge_python_executable = None
                self._native_bridge_probe_error = ""
                self._native_bridge_last_verified_at = (
                    time.time() if self._native_bridge_available else 0.0
                )
                self._native_bridge_probe_done.set()
            return

        with self._native_bridge_probe_lock:
            if self._native_bridge_probe_in_progress:
                return
            if (
                self._native_bridge_probe_started
                and self._native_bridge_probe_done.is_set()
            ):
                return
            self._native_bridge_probe_in_progress = True
            self._native_bridge_probe_started = True
            if _imaris_application_handle_is_live(self.imaris):
                self._native_bridge_available = True
                self._native_bridge_last_verified_at = time.time()
                self._native_bridge_probe_in_progress = False
                self._native_bridge_probe_done.set()
                _xt_debug("Native bridge probe skipped: current Imaris handle is live")
                return
            self.imaris = None

        threading.Thread(target=self._native_bridge_probe_worker, daemon=True).start()

    def _reset_native_bridge_probe(self):
        """Cached native-bridge probe state so a later Imaris session is detected.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        with self._native_bridge_probe_lock:
            self._native_bridge_probe_done.clear()
            self._native_bridge_probe_started = False
            self._native_bridge_probe_in_progress = False
            self._native_bridge_available = _imaris_application_handle_is_live(
                getattr(self, "imaris", None)
            )
            self._native_bridge_python_executable = None
            self._native_bridge_probe_error = ""
            self._native_bridge_last_verified_at = (
                time.time() if self._native_bridge_available else 0.0
            )

    def _reset_native_bridge_probe_for_converter_detection(self):
        """Reset stale native-bridge detection without interrupting an active probe.

        Inputs: none. Output: None.
        """
        with self._native_bridge_probe_lock:
            if getattr(self, "_native_bridge_probe_in_progress", False):
                return
        self._reset_native_bridge_probe()

    def _run_native_bridge_probe_now(self, timeout=NATIVE_BRIDGE_REVALIDATION_TIMEOUT):
        """Or restart a bounded native-bridge probe and wait for its result.

        Inputs: `timeout` timeout seconds. Output: `wait` result.
        """
        if not _native_imaris_bridge_enabled():
            self._start_native_bridge_probe()
            return True
        self._reset_native_bridge_probe()
        self._start_native_bridge_probe()
        return self._native_bridge_probe_done.wait(timeout=max(0.0, float(timeout)))

    def _native_bridge_probe_worker(self):
        """Probe native bridge readiness in the background refresh worker.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if not _native_imaris_bridge_enabled():
            with self._native_bridge_probe_lock:
                self._native_bridge_python_executable = None
                self._native_bridge_available = _imaris_application_handle_is_live(
                    getattr(self, "imaris", None)
                )
                self._native_bridge_probe_error = ""
                self._native_bridge_last_verified_at = (
                    time.time() if self._native_bridge_available else 0.0
                )
                self._native_bridge_probe_in_progress = False
                self._native_bridge_probe_done.set()
            return

        bridge_python = None
        bridge_error = ""
        verified_at = 0.0
        try:
            if _coerce_imaris_id(self.imaris_id) is None:
                bridge_error = "No numeric Imaris application id was provided."
            else:
                bridge_python = _find_compatible_native_bridge_python(self.imaris_id)
                if bridge_python:
                    verified_at = time.time()
                    _xt_debug(
                        f"Native bridge probe found compatible Python: {bridge_python}"
                    )
                else:
                    bridge_error = (
                        "No compatible installed Python could load ImarisLib/IcePy "
                        "and resolve the live Imaris application."
                    )
        except Exception as exc:
            bridge_error = str(exc)
            _xt_debug(f"Native bridge probe failed: {exc}")
        finally:
            with self._native_bridge_probe_lock:
                self._native_bridge_python_executable = bridge_python
                self._native_bridge_available = bool(bridge_python)
                self._native_bridge_probe_error = bridge_error
                self._native_bridge_last_verified_at = verified_at
                self._native_bridge_probe_in_progress = False
                self._native_bridge_probe_done.set()
            self._request_background_cursor_reset()

    def _revalidate_native_bridge(self):
        """Synchronously verify that the cached native bridge still resolves Imaris.

        Inputs: none. Output: `bool`.
        """
        if _imaris_application_handle_is_live(self.imaris):
            with self._native_bridge_probe_lock:
                self._native_bridge_available = True
                self._native_bridge_probe_error = ""
                self._native_bridge_last_verified_at = time.time()
            return True
        self.imaris = None

        if not _native_imaris_bridge_enabled():
            with self._native_bridge_probe_lock:
                self._native_bridge_available = False
                self._native_bridge_probe_error = ""
                self._native_bridge_last_verified_at = 0.0
            return False

        if _coerce_imaris_id(self.imaris_id) is None:
            bridge_error = "No numeric Imaris application id was provided."
            with self._native_bridge_probe_lock:
                self._native_bridge_available = False
                self._native_bridge_probe_error = bridge_error
                self._native_bridge_last_verified_at = 0.0
            _xt_debug(f"Native bridge revalidation failed: {bridge_error}")
            return False

        with self._native_bridge_probe_lock:
            preferred_python = self._native_bridge_python_executable

        bridge_python = None
        bridge_error = ""
        try:
            if preferred_python and _run_native_bridge_probe_helper(
                preferred_python,
                self.imaris_id,
            ):
                bridge_python = preferred_python
            else:
                bridge_python = _find_compatible_native_bridge_python(self.imaris_id)
            if bridge_python:
                _xt_debug(
                    "Native bridge revalidation resolved the current Imaris session"
                )
            else:
                bridge_error = (
                    "No compatible installed Python could load ImarisLib/IcePy "
                    "and resolve the live Imaris application."
                )
        except Exception as exc:
            bridge_error = str(exc)
            _xt_debug(f"Native bridge revalidation failed: {exc}")

        with self._native_bridge_probe_lock:
            self._native_bridge_python_executable = bridge_python
            self._native_bridge_available = bool(bridge_python)
            self._native_bridge_probe_error = bridge_error
            self._native_bridge_last_verified_at = time.time() if bridge_python else 0.0
        return bool(bridge_python)

    def _ensure_native_open_ready_before_export(self):
        """Return True only when the final open can use a native Imaris bridge.

        Inputs: none. Output: bool.
        """
        if _imaris_application_handle_is_live(self.imaris):
            return True
        self.imaris = None

        self._set_status("Checking Imaris same-session open support...", "#fff3cd")
        if self._resolve_direct_imaris_handle_for_handoff():
            return True

        if not _native_imaris_bridge_enabled():
            if _coerce_imaris_id(getattr(self, "imaris_id", None)) is not None:
                _xt_debug(
                    "Proceeding with Imaris handoff because a numeric XT application "
                    "id is available; final file open will retry direct handle "
                    "acquisition on the UI thread"
                )
                return True
            return False

        with self._native_bridge_probe_lock:
            initial_available = self._native_bridge_available
            initial_last_verified_at = self._native_bridge_last_verified_at

        if (
            initial_available
            and time.time() - initial_last_verified_at <= NATIVE_BRIDGE_REVALIDATE_AFTER
        ):
            return True
        if initial_available and self._revalidate_native_bridge():
            return True

        if not initial_available:
            if not self._run_native_bridge_probe_now(
                timeout=NATIVE_BRIDGE_REVALIDATION_TIMEOUT
            ):
                _xt_debug("Native bridge probe timed out before export")
                with self._native_bridge_probe_lock:
                    self._native_bridge_available = False
                    self._native_bridge_probe_error = "probe timed out"
                    self._native_bridge_last_verified_at = 0.0
            with self._native_bridge_probe_lock:
                probed_available = self._native_bridge_available
                probed_bridge_error = self._native_bridge_probe_error
                probed_last_verified_at = self._native_bridge_last_verified_at
            if (
                probed_available
                and time.time() - probed_last_verified_at
                <= NATIVE_BRIDGE_REVALIDATE_AFTER
            ):
                return True
            if probed_available and self._revalidate_native_bridge():
                return True

            if not probed_available:
                _xt_debug(
                    "Imaris same-session open bridge is unavailable before export: "
                    f"{probed_bridge_error}"
                )

        with self._native_bridge_probe_lock:
            bridge_error = self._native_bridge_probe_error
        _xt_debug(
            "Imaris same-session open bridge failed revalidation before export: "
            f"{bridge_error}"
        )
        return False

    def _ensure_imaris_converter_handoff_ready_before_export(self):
        """Return True when selected-image exports can be submitted to Imaris.

        Inputs: none. Output: bool.
        """
        self._set_status("Checking Imaris converter handoff support...", "#fff3cd")
        if self._has_imaris_converter_handoff_target():
            return True
        _xt_debug(
            "Imaris converter handoff is unavailable before export: "
            "ImarisFileConverter.exe could not be discovered"
        )
        return False

    def _connect(self):
        """Open the connection for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: starts a background connection setup.
        """
        h = self.host_entry.get().strip()
        p = self.port_entry.get().strip()
        u = self.user_entry.get().strip()
        pw = self.pass_entry.get()

        if not all([h, p, u, pw]):
            self._show_warning_dialog(
                "Missing Fields", "Please fill all connection fields"
            )
            return

        self._set_converter_options([])
        self._set_folder_export_capability(False, "Detecting OMERO folder export...")

        port = _parse_port(p)
        if port is None:
            self._show_error_dialog(
                "Invalid Port",
                "Please enter a valid numeric port (1-65535) for the OMERO.web server.",
            )
            return

        host_error = _omero_web_host_input_error(h)
        if host_error:
            self._show_error_dialog("Invalid Host", host_error)
            return

        self._connection_in_progress = True
        self._set_connect_button(
            "Connecting...",
            _tk_constant("DISABLED", "disabled"),
            "#8fb7d9",
        )
        self._set_status("Connecting to OMERO...", "#fff3cd")
        self._set_connection_indicator("busy")

        scheme = "https" if self.https_var.get() else "http"
        include_collaboration_projects = self._collaboration_projects_enabled()
        threading.Thread(
            target=self._connect_worker,
            args=(h, port, u, pw, scheme, include_collaboration_projects),
            daemon=True,
        ).start()

    def _connect_worker(
        self,
        host,
        port,
        username,
        password,
        scheme,
        include_collaboration_projects=True,
    ):
        """Run OMERO.web login and capability detection off the Tk UI thread.

        Inputs: connection parameters. Output: schedules a UI-thread completion.
        """
        client = None
        try:
            client = OMEROWebClient(host, port, username, password, scheme=scheme)
            del password
            if not client.connect():
                self._clear_client_session_state(client)
                self._invoke_on_ui_thread(
                    lambda: self._finish_connect_failure(client),
                    wait=False,
                )
                return

            client.password = CLEARED_CREDENTIAL_TEXT
            self._invoke_on_ui_thread(
                lambda: self._set_status(
                    "Detecting connector capabilities...",
                    "#fff3cd",
                ),
                wait=False,
            )
            projects = client.list_projects(
                include_collaboration_projects=include_collaboration_projects
            )
            converter_options = self._detect_converter_options_after_connection(client)
            folder_export_capability = self._detect_folder_export_after_connection(
                client
            )
            self._invoke_on_ui_thread(
                lambda: self._finish_connect_success(
                    client,
                    projects,
                    converter_options,
                    folder_export_capability,
                ),
                wait=False,
            )
        except Exception as exc:
            self._clear_client_session_state(client)
            _xt_debug(f"Connection setup failed: {type(exc).__name__}: {exc}")
            self._invoke_on_ui_thread(
                lambda: self._finish_connect_failure(client),
                wait=False,
            )

    def _finish_connect_success(
        self,
        client,
        projects,
        converter_options,
        folder_export_capability,
    ):
        """Apply successful connection setup on the Tk UI thread.

        Inputs: connection artifacts. Output: updates connector UI state.
        """
        if not getattr(self, "_connection_in_progress", False):
            self._clear_client_session_state(client)
            return

        try:
            self.client = client
            self._connected = True
            self._clear_password_entry()
            self._set_password_entry_interactive(False)
            client.password = CLEARED_CREDENTIAL_TEXT
            self._set_connect_button(
                "Disconnect",
                _tk_constant("NORMAL", "normal"),
                "#f39c12",
                active_bg="#d68910",
            )
            self._set_browser_interaction_state(True)
            self._set_connection_indicator("connected")
            self._apply_loaded_projects(projects)
            self._set_converter_options(converter_options)
            self._set_folder_export_capability(
                folder_export_capability.get("available"),
                folder_export_capability.get("reason", ""),
            )
            if converter_options or folder_export_capability.get("available"):
                self._set_status("Connected to OMERO", "#d4edda")
            else:
                self._set_status(
                    "Connected, but no supported connector workflow is available",
                    "#f8d7da",
                )
            self._enable_autosave_after_verified_connection()
            self._schedule_health_ping()
        finally:
            self._connection_in_progress = False

    def _finish_connect_failure(self, client=None):
        """Restore connect-ready UI after failed background connection setup.

        Inputs: optional failed `client`. Output: updates connector UI state.
        """
        self._clear_client_session_state(client)
        self.client = None
        self._connected = False
        self._set_password_entry_interactive(True)
        self._set_folder_export_capability(False, "Connect to OMERO first.")
        self._set_connect_button(
            "Connect",
            _tk_constant("NORMAL", "normal"),
            "#3498db",
            active_bg="#2f85c7",
        )
        self._set_autosave_settings_control_state(False)
        self._set_browser_interaction_state(False)
        self._set_status("Connection failed", "#f8d7da")
        self._set_connection_indicator("error")
        self._connection_in_progress = False
        try:
            self._show_error_dialog(
                "Connection Failed",
                "Cannot connect to OMERO server.\nPlease check your credentials.",
            )
        finally:
            self._queue_connection_retry_focus()

    def _queue_connection_retry_focus(self):
        """Restore password-entry focus after a failed connection dialog.

        Inputs: no caller arguments. Output: schedules or performs focus recovery.
        """

        def restore_focus():
            """Restore main-window and password-entry focus for immediate retry.

            Inputs: no caller arguments. Output: None.
            """
            self._set_main_window_disabled(False)
            self._modal_background_lock_depth = 0
            self._modal_background_window_disabled = False
            root = getattr(self, "root", None)
            for method_name in ("lift", "focus_force"):
                method = getattr(root, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception as exc:
                        logger.debug(
                            "Suppressed non-fatal exception in XTOmeroConnector.py",
                            exc_info=exc,
                        )
            entry = getattr(self, "pass_entry", None)
            focus_set = getattr(entry, "focus_set", None)
            if callable(focus_set):
                try:
                    focus_set()
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in XTOmeroConnector.py",
                        exc_info=exc,
                    )
            icursor = getattr(entry, "icursor", None)
            if callable(icursor):
                try:
                    icursor(_tk_constant("END", "end"))
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in XTOmeroConnector.py",
                        exc_info=exc,
                    )

        root = getattr(self, "root", None)
        after = getattr(root, "after", None)
        if callable(after):
            try:
                after(0, restore_focus)
                return
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
        restore_focus()

    def _load_projects(self):
        """Load the projects for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: loads the described state and returns None.
        """
        self._apply_loaded_projects(
            self.client.list_projects(
                include_collaboration_projects=self._collaboration_projects_enabled()
            )
        )

    def _apply_loaded_projects(self, projects):
        """Populate the project browser from an already-fetched project list.

        Inputs: `projects`. Output: updates browser lists.
        """
        self._all_projects_data = list(projects or [])
        self.projects_data = list(self._all_projects_data)
        self._pid = None
        self._did = None
        self._all_datasets_data = []
        self._all_images_data = []
        self.datasets_data = []
        self.images_data = []
        self._image_selection_anchor = None
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._apply_all_browser_search_filters()

    def _sel_proj(self):
        """Select the active project in the browser UI state.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        sel = self.plist.curselection()
        if not sel:
            return
        p = self.projects_data[sel[0]]
        project_id = self._entity_id(p)
        if self._pid != project_id:
            self._pid = project_id
            self._did = None
            self._load_ds()

    def _sel_ds(self):
        """Select the active dataset in the browser UI state.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        sel = self.dlist.curselection()
        if not sel:
            return
        d = self.datasets_data[sel[0]]
        dataset_id = self._entity_id(d)
        if dataset_id is None:
            return
        self._did = dataset_id
        self._load_imgs(dataset_id)

    def _load_ds(self):
        """Load the ds for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: loads the described state and returns None.
        """
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._did = None
        self._all_images_data = []
        self.images_data = []
        self._all_datasets_data = self.client.list_datasets(self._pid)
        self.datasets_data = list(self._all_datasets_data)
        self._apply_browser_search_filter("datasets")
        self._apply_browser_search_filter("images")
        self._refresh_load_button_text()

    def _load_imgs(self, did):
        """Load the imgs for `OMEROBrowserDialog`.

        Inputs: `did`. Output: None.
        """
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._did = did
        self._all_images_data = self.client.list_images(did)
        self.images_data = list(self._all_images_data)
        self._image_selection_anchor = None
        self._apply_browser_search_filter("images")
        self._refresh_load_button_text()

    @classmethod
    def _project_list_label(cls, project):
        """Return the project list label for `OMEROBrowserDialog`.

        Inputs: `project`. Output: `bool`.
        """
        if isinstance(project, dict):
            project_id = cls._entity_id(project)
            return project.get("name") or (
                f"Project {project_id}" if project_id is not None else "Project"
            )
        return "Project"

    @classmethod
    def _dataset_list_label(cls, dataset):
        """Return the dataset list label for `OMEROBrowserDialog`.

        Inputs: `dataset`. Output: `bool`.
        """
        if isinstance(dataset, dict):
            dataset_id = cls._entity_id(dataset)
            return dataset.get("name") or (
                f"Dataset {dataset_id}" if dataset_id is not None else "Dataset"
            )
        return "Dataset"

    @classmethod
    def _image_list_label(cls, image):
        """Return the image list label for `OMEROBrowserDialog`.

        Inputs: `image`. Output: `list`.
        """
        if not isinstance(image, dict):
            return "Image"
        image_id = cls._entity_id(image)
        name = image.get("name") or (
            f"Image {image_id}" if image_id is not None else "Image"
        )
        size_x = image.get("sizeX", 0)
        size_y = image.get("sizeY", 0)
        size_z = image.get("sizeZ", 1)
        size_info = f"{size_x}×{size_y}×{size_z}"
        if image.get("sizeC", 1) > 1:
            size_info += f" C{image.get('sizeC')}"
        if image.get("sizeT", 1) > 1:
            size_info += f" T{image.get('sizeT')}"
        return f"{name} [{size_info}]"

    @staticmethod
    def _entity_id(entity):
        """Return the entity ID for `OMEROBrowserDialog`.

        Inputs: `entity`. Output: `str`.
        """
        if not isinstance(entity, dict):
            return None
        value = entity.get("id")
        if value is None:
            value = entity.get("@id")
        if value is None:
            return None
        return str(value)

    @classmethod
    def _find_entity_index(cls, entities, entity_id):
        """Find the entity index for `OMEROBrowserDialog`.

        Inputs: `entities`, `entity_id`. Output: `index`.
        """
        if entity_id is None:
            return None
        target = str(entity_id)
        for index, entity in enumerate(list(entities or [])):
            if cls._entity_id(entity) == target:
                return index
        return None

    @staticmethod
    def _clear_listbox_selection(listbox):
        """Clear the listbox selection for `OMEROBrowserDialog`.

        Inputs: `listbox`. Output: None.
        """
        selection_clear = getattr(listbox, "selection_clear", None)
        if callable(selection_clear):
            selection_clear(0, _tk_constant("END", "end"))

    @classmethod
    def _select_listbox_index(cls, listbox, index):
        """Select the listbox index for `OMEROBrowserDialog`.

        Inputs: `listbox`, `index`. Output: None.
        """
        cls._clear_listbox_selection(listbox)
        if index is None:
            return
        selection_set = getattr(listbox, "selection_set", None)
        if callable(selection_set):
            selection_set(index)
        see = getattr(listbox, "see", None)
        if callable(see):
            see(index)

    @staticmethod
    def _replace_listbox_items(listbox, labels):
        """Replace the listbox items for `OMEROBrowserDialog`.

        Inputs: `listbox`, `labels`. Output: None.
        """
        listbox.delete(0, _tk_constant("END", "end"))
        for label in labels:
            listbox.insert(_tk_constant("END", "end"), label)

    def _configure_image_selection_bindings(self):
        """Configure the image selection bindings for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: configures the described state and returns None.
        """
        self.ilist.bind("<Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind("<Control-Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind("<Shift-Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind(
            "<Control-Shift-Button-1>",
            self._on_image_listbox_click,
            add="+",
        )
        self.ilist.bind("<B1-Motion>", self._block_image_listbox_native_selection)
        self.ilist.bind(
            "<ButtonRelease-1>",
            self._block_image_listbox_native_selection,
        )
        self.ilist.bind("<Control-a>", self._on_images_select_all)
        self.ilist.bind("<Control-A>", self._on_images_select_all)

    def _block_image_listbox_native_selection(self, event):
        """Prevent native Tk bindings from mutating custom image selections.

        Inputs: `event`. Output: 'break' or None.
        """
        listbox = getattr(event, "widget", None)
        if listbox is not getattr(self, "ilist", None):
            return None
        return "break"

    @staticmethod
    def _listbox_size(listbox):
        """Return the listbox size for `OMEROBrowserDialog`.

        Inputs: `listbox`. Output: `int`.
        """
        size_getter = getattr(listbox, "size", None)
        if callable(size_getter):
            try:
                return int(size_getter())
            except Exception:
                return 0
        return 0

    @staticmethod
    def _set_listbox_anchor(listbox, index):
        """Set the listbox anchor for `OMEROBrowserDialog`.

        Inputs: `listbox`, `index`. Output: None.
        """
        activate = getattr(listbox, "activate", None)
        if callable(activate):
            try:
                activate(index)
            except Exception as exc:
                _xt_debug(f"Listbox activate failed: {type(exc).__name__}")
        selection_anchor = getattr(listbox, "selection_anchor", None)
        if callable(selection_anchor):
            try:
                selection_anchor(index)
            except Exception as exc:
                _xt_debug(f"Listbox anchor failed: {type(exc).__name__}")

    @staticmethod
    def _focus_listbox(listbox):
        """Give a listbox keyboard focus so Tk draws its native focus border.

        Inputs: `listbox`. Output: None.
        """
        focus_set = getattr(listbox, "focus_set", None)
        if callable(focus_set):
            try:
                focus_set()
            except Exception as exc:
                _xt_debug(f"Listbox focus failed: {type(exc).__name__}")

    def _clear_browser_listbox_focus(self):
        """Move focus off browser listboxes before non-browser controls open.

        Inputs: none. Output: None.
        """
        root = getattr(self, "root", None)
        if root is None:
            return
        focus_get = getattr(root, "focus_get", None)
        try:
            focused_widget = focus_get() if callable(focus_get) else None
        except Exception as exc:
            _xt_debug(f"Listbox focus lookup failed: {type(exc).__name__}")
            return
        for listbox_name in ("plist", "dlist", "ilist"):
            listbox = getattr(self, listbox_name, None)
            if _widget_is_or_descendant(focused_widget, listbox):
                focus_set = getattr(root, "focus_set", None)
                if callable(focus_set):
                    try:
                        focus_set()
                    except Exception as exc:
                        _xt_debug(f"Root focus reset failed: {type(exc).__name__}")
                return

    def _selected_image_count(self):
        """Return the number of currently selected valid images.

        Inputs: none. Output: `len` result.
        """
        return len(self._selected_images())

    def _load_button_text(self):
        """Return load-button text using singular/plural wording.

        Inputs: none. Output: text string.
        """
        count = self._selected_image_count()
        return f"Load {_pluralize(count, 'image')} into Imaris"

    def _refresh_load_button_text(self):
        """Refresh the load button label to match the selected image count.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._set_load_button_for_converter()

    def _on_images_select_all(self, event):
        """Select every image in the Images panel only.

        Inputs: `event`. Output: 'break' or None.
        """
        listbox = getattr(event, "widget", None)
        if listbox is not self.ilist:
            return None
        self._focus_listbox(listbox)

        size = self._listbox_size(listbox)
        if size <= 0:
            return "break"

        self._clear_listbox_selection(listbox)
        for index in range(size):
            listbox.selection_set(index)
        self._image_selection_anchor = 0
        self._set_listbox_anchor(listbox, 0)
        listbox.see(size - 1)
        self._refresh_load_button_text()
        return "break"

    def _on_image_listbox_click(self, event):
        """Handle image listbox click event.

        Inputs: `event`. Output: 'break' or None.
        """
        listbox = getattr(event, "widget", None)
        if listbox is not self.ilist:
            return None
        self._focus_listbox(listbox)

        size = self._listbox_size(listbox)
        if size <= 0:
            return "break"

        index = int(listbox.nearest(event.y))
        if index < 0 or index >= size:
            return "break"

        shift_pressed = bool(getattr(event, "state", 0) & 0x0001)
        ctrl_pressed = bool(getattr(event, "state", 0) & 0x0004)
        current_selection = {int(value) for value in listbox.curselection()}

        if shift_pressed:
            anchor = self._image_selection_anchor
            if anchor is None:
                anchor = min(current_selection) if current_selection else index
            start = min(anchor, index)
            end = max(anchor, index)
            if not ctrl_pressed:
                self._clear_listbox_selection(listbox)
            for selected_index in range(start, end + 1):
                listbox.selection_set(selected_index)
            self._set_listbox_anchor(listbox, index)
            listbox.see(index)
            self._refresh_load_button_text()
            return "break"

        if ctrl_pressed:
            if index in current_selection:
                listbox.selection_clear(index)
            else:
                listbox.selection_set(index)
            self._image_selection_anchor = index
            self._set_listbox_anchor(listbox, index)
            listbox.see(index)
            self._refresh_load_button_text()
            return "break"

        self._clear_listbox_selection(listbox)
        listbox.selection_set(index)
        self._image_selection_anchor = index
        self._set_listbox_anchor(listbox, index)
        listbox.see(index)
        self._refresh_load_button_text()
        return "break"

    def _current_selected_project_id(self):
        """Return current selected project ID.

        Inputs: none. Output: ID value.
        """
        for raw_index in self.plist.curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.projects_data):
                return self._entity_id(self.projects_data[index])
        return str(self._pid) if self._pid is not None else None

    def _current_selected_dataset_id(self):
        """Return current selected dataset ID.

        Inputs: none. Output: ID value.
        """
        for raw_index in self.dlist.curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.datasets_data):
                return self._entity_id(self.datasets_data[index])
        return str(self._did) if self._did is not None else None

    def _set_refresh_button_state(self, state):
        """Set the refresh button state for `OMEROBrowserDialog`.

        Inputs: `state`. Output: None.
        """
        refresh_btn = getattr(self, "refresh_btn", None)
        if refresh_btn is not None:
            refresh_btn.config(state=state)

    def _set_export_button_state(self, state):
        """Set the export button state for `OMEROBrowserDialog`.

        Inputs: `state`. Output: None.
        """
        export_btn = getattr(self, "export_btn", None)
        if export_btn is not None:
            export_btn.config(state=state)

    def _update_export_button_state(self):
        """Update the export button state for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: updates the described state and returns None.
        """
        enabled = (
            getattr(self, "_connected", False)
            and getattr(self, "_folder_export_available", False)
            and not getattr(self, "_connection_in_progress", False)
            and not getattr(self, "_folder_export_in_progress", False)
            and not getattr(self, "_load_in_progress", False)
        )
        self._set_export_button_state(
            _tk_constant("NORMAL", "normal")
            if enabled
            else _tk_constant("DISABLED", "disabled")
        )

    def _set_folder_export_capability(self, available, reason=""):
        """Set folder export availability for `OMEROBrowserDialog`.

        Inputs: `available`, `reason`. Output: None.
        """
        self._folder_export_available = bool(available)
        self._folder_export_reason = str(reason or "").strip()
        self._update_export_button_state()

    def _operation_is_running(self):
        """Return whether a load or folder export workflow is active.

        Inputs: none. Output: bool.
        """
        return bool(
            getattr(self, "_load_in_progress", False)
            or getattr(self, "_folder_export_in_progress", False)
        )

    def _show_stop_button_if_needed(self):
        """Show the stop button only during cancellable operations.

        Inputs: none. Output: None.
        """
        stop_btn = getattr(self, "stop_btn", None)
        if stop_btn is None:
            return
        if self._operation_is_running():
            stop_btn.grid()
            event = getattr(self, "_operation_cancel_event", None)
            stop_btn.config(
                state=(
                    _tk_constant("DISABLED", "disabled")
                    if event is not None and event.is_set()
                    else _tk_constant("NORMAL", "normal")
                )
            )
            return
        stop_btn.grid_remove()

    def _begin_cancellable_operation(self):
        """Reset cancellation state before starting a load or export workflow.

        Inputs: none. Output: operation cancel event and generation.
        """
        self._operation_generation = int(getattr(self, "_operation_generation", 0)) + 1
        self._operation_cancel_event = threading.Event()
        self._active_folder_export_job = None
        self._show_stop_button_if_needed()
        return self._operation_cancel_event, self._operation_generation

    def _operation_is_current(self, operation_event=None, operation_generation=None):
        """Return whether a background worker still owns the foreground UI state.

        Inputs: optional worker event and generation. Output: bool.
        """
        if operation_generation is None:
            return True
        return bool(
            getattr(self, "_operation_generation", 0) == operation_generation
            and getattr(self, "_operation_cancel_event", None) is operation_event
            and self._operation_is_running()
        )

    def _restore_actions_after_operation_stop(self):
        """Release foreground operation state immediately after Stop.

        Inputs: none. Output: None.
        """
        self._load_in_progress = False
        self._folder_export_in_progress = False
        self._active_folder_export_job = None
        self._restore_idle_connection_indicator()
        connect_btn = getattr(self, "connect_btn", None)
        if connect_btn is not None and getattr(self, "_connected", False):
            self._set_connect_button(
                "Disconnect",
                _tk_constant("NORMAL", "normal"),
                "#f39c12",
                active_bg="#d68910",
            )
        elif connect_btn is not None:
            self._set_connect_button(
                "Connect",
                _tk_constant("NORMAL", "normal"),
                "#3498db",
                active_bg="#2f85c7",
            )
        self._set_load_button_for_converter()
        self._update_export_button_state()
        if getattr(self, "_connected", False) and _stringvar_value(
            getattr(self, "converter_var", None)
        ) in {"OMERO", "Imaris"}:
            self._set_refresh_button_state(_tk_constant("NORMAL", "normal"))
        self._show_stop_button_if_needed()
        self._reset_background_cursor_after_silent_work()
        self._sync_action_button_cursors()

    @staticmethod
    def _cancel_folder_export_job_in_background(client, job_payload):
        """Cancel a folder export job without blocking the UI thread.

        Inputs: client and job payload. Output: None.
        """
        try:
            client.cancel_folder_export_job(job_payload)
        except Exception as exc:
            _xt_debug(
                "Folder export background cancellation failed: "
                f"{type(exc).__name__}: {exc}"
            )

    def _request_stop_current_operation(self):
        """Signal the active load/export workflow to stop.

        Inputs: none. Output: None.
        """
        if not self._operation_is_running():
            return
        event = getattr(self, "_operation_cancel_event", None)
        if event is None:
            event = threading.Event()
            self._operation_cancel_event = event
        if event.is_set():
            return
        event.set()
        _xt_debug("Stop requested by user; cancelling active connector operation")
        job_payload = getattr(self, "_active_folder_export_job", None)
        client = getattr(self, "client", None)
        self._operation_generation = int(getattr(self, "_operation_generation", 0)) + 1
        self._set_status("Stopped current connector operation.", "#fff3cd")
        self._restore_actions_after_operation_stop()
        if job_payload and client is not None:
            threading.Thread(
                target=self._cancel_folder_export_job_in_background,
                args=(client, job_payload),
                daemon=True,
            ).start()

    def _raise_if_current_operation_cancelled(self, context, cancel_event=None):
        """Raise if the user has requested the current operation to stop.

        Inputs: context and optional event. Output: None.
        """
        _raise_if_cancelled(
            cancel_event
            if cancel_event is not None
            else getattr(self, "_operation_cancel_event", None),
            context,
        )

    def _set_load_button_for_converter(self):
        """Set the load button for converter for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        converter_value = _stringvar_value(getattr(self, "converter_var", None))
        state = (
            _tk_constant("NORMAL", "normal")
            if (
                getattr(self, "_connected", False)
                and getattr(self, "client", None) is not None
                and converter_value in {"OMERO", "Imaris"}
                and self._folder_path_allows_load_button()
                and self._selected_image_count() > 0
                and not getattr(self, "_load_in_progress", False)
                and not getattr(self, "_folder_export_in_progress", False)
            )
            else _tk_constant("DISABLED", "disabled")
        )
        load_btn = getattr(self, "load_btn", None)
        if load_btn is not None:
            load_btn.config(state=state, text=self._load_button_text())

    def _set_actions_busy_for_export(self, active):
        """Set the actions busy for export for `OMEROBrowserDialog`.

        Inputs: `active`. Output: None.
        """
        self._folder_export_in_progress = bool(active)
        disabled = _tk_constant("DISABLED", "disabled")
        load_btn = getattr(self, "load_btn", None)
        connect_btn = getattr(self, "connect_btn", None)
        if active:
            self._begin_cancellable_operation()
            self._set_connection_indicator("busy")
            if load_btn is not None:
                load_btn.config(state=disabled)
            self._set_export_button_state(disabled)
            self._set_refresh_button_state(disabled)
            if connect_btn is not None:
                connect_btn.config(state=disabled)
            self._show_stop_button_if_needed()
            return

        if connect_btn is not None and getattr(self, "_connected", False):
            self._set_connect_button(
                "Disconnect",
                _tk_constant("NORMAL", "normal"),
                "#f39c12",
                active_bg="#d68910",
            )
        elif connect_btn is not None:
            self._set_connect_button(
                "Connect",
                _tk_constant("NORMAL", "normal"),
                "#3498db",
                active_bg="#2f85c7",
            )
        self._set_load_button_for_converter()
        self._update_export_button_state()
        if (
            getattr(self, "_connected", False)
            and _stringvar_value(getattr(self, "converter_var", None))
            in {
                "OMERO",
                "Imaris",
            }
            and not getattr(self, "_load_in_progress", False)
        ):
            self._set_refresh_button_state(_tk_constant("NORMAL", "normal"))
        self._show_stop_button_if_needed()

    def _clear_actions_busy_for_export(self):
        """Clear the actions busy for export for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._set_actions_busy_for_export(False)

    def _finish_export_workflow(self, succeeded, cancelled=False):
        """Restore export action state and reflect final connection indicator state.

        Inputs: `succeeded`. Output: None.
        """
        self._set_actions_busy_for_export(False)
        if succeeded or cancelled:
            self._restore_idle_connection_indicator()
        else:
            self._set_connection_indicator("error")

    def _set_actions_busy_for_load(self, active):
        """Set the actions busy for load for `OMEROBrowserDialog`.

        Inputs: `active`. Output: None.
        """
        self._load_in_progress = bool(active)
        disabled = _tk_constant("DISABLED", "disabled")
        load_btn = getattr(self, "load_btn", None)
        connect_btn = getattr(self, "connect_btn", None)
        if active:
            self._begin_cancellable_operation()
            self._set_connection_indicator("busy")
            if load_btn is not None:
                load_btn.config(state=disabled, text=self._load_button_text())
            self._set_export_button_state(disabled)
            self._set_refresh_button_state(disabled)
            if connect_btn is not None:
                connect_btn.config(state=disabled)
            self._show_stop_button_if_needed()
            return

        if connect_btn is not None and getattr(self, "_connected", False):
            self._set_connect_button(
                "Disconnect",
                _tk_constant("NORMAL", "normal"),
                "#f39c12",
                active_bg="#d68910",
            )
        elif connect_btn is not None:
            self._set_connect_button(
                "Connect",
                _tk_constant("NORMAL", "normal"),
                "#3498db",
                active_bg="#2f85c7",
            )
        self._set_load_button_for_converter()
        self._update_export_button_state()
        if (
            getattr(self, "_connected", False)
            and _stringvar_value(getattr(self, "converter_var", None))
            in {
                "OMERO",
                "Imaris",
            }
            and not getattr(self, "_folder_export_in_progress", False)
        ):
            self._set_refresh_button_state(_tk_constant("NORMAL", "normal"))
        self._show_stop_button_if_needed()

    def _clear_actions_busy_for_load(self):
        """Clear the actions busy for load for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._set_actions_busy_for_load(False)

    def _finish_load_workflow(self, succeeded, cancelled=False):
        """Restore load action state and reflect final connection indicator state.

        Inputs: `succeeded`. Output: None.
        """
        self._set_actions_busy_for_load(False)
        if succeeded or cancelled:
            self._restore_idle_connection_indicator()
        else:
            self._set_connection_indicator("error")

    def _refresh_browser(self):
        """Refresh the browser for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if self._refresh_in_progress:
            return
        if not self._connected or self.client is None:
            self._show_warning_dialog("Not Connected", "Please connect to OMERO first.")
            return

        self._refresh_in_progress = True
        self._refresh_generation += 1
        generation = self._refresh_generation
        project_id = self._current_selected_project_id()
        dataset_id = self._current_selected_dataset_id()
        include_collaboration_projects = self._collaboration_projects_enabled()
        self._set_refresh_button_state(_tk_constant("DISABLED", "disabled"))
        self._set_status("Refreshing OMERO browser...", "#fff3cd")
        threading.Thread(
            target=self._refresh_worker,
            args=(project_id, dataset_id, generation, include_collaboration_projects),
            daemon=True,
        ).start()

    def _fetch_browser_state_for_refresh(
        self,
        project_id,
        dataset_id,
        include_collaboration_projects=True,
    ):
        """Fetch the browser state for refresh for `OMEROBrowserDialog`.

        Inputs: `project_id` OMERO project ID, `dataset_id` OMERO dataset ID. Output:
        `tuple`.
        """
        timeout = _refresh_request_timeout_seconds()
        projects = self.client.list_projects(
            timeout=timeout,
            raise_on_error=True,
            retry_transient=True,
            include_collaboration_projects=include_collaboration_projects,
        )
        project_index = self._find_entity_index(projects, project_id)
        datasets = []
        dataset_index = None
        images = []

        if project_index is not None:
            refreshed_project_id = self._entity_id(projects[project_index])
            datasets = self.client.list_datasets(
                refreshed_project_id,
                timeout=timeout,
                raise_on_error=True,
                retry_transient=True,
            )
            dataset_index = self._find_entity_index(datasets, dataset_id)
            if dataset_index is not None:
                refreshed_dataset_id = self._entity_id(datasets[dataset_index])
                images = self.client.list_images(
                    refreshed_dataset_id,
                    timeout=timeout,
                    raise_on_error=True,
                    retry_transient=True,
                )

        return projects, project_index, datasets, dataset_index, images

    def _refresh_worker(
        self,
        project_id,
        dataset_id,
        generation,
        include_collaboration_projects=True,
    ):
        """Refresh the worker for `OMEROBrowserDialog`.

        Inputs: `project_id` OMERO project ID, `dataset_id` OMERO dataset ID,
        `generation`. Output: None. Raises: last_error for the exercised failure path.
        """
        try:
            attempts = _refresh_retry_attempts()
            delay = _refresh_retry_delay_seconds()
            last_error = None
            for attempt in range(1, attempts + 1):
                if generation != self._refresh_generation:
                    return
                try:
                    (
                        projects,
                        project_index,
                        datasets,
                        dataset_index,
                        images,
                    ) = self._fetch_browser_state_for_refresh(
                        project_id,
                        dataset_id,
                        include_collaboration_projects,
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt >= attempts:
                        break
                    _xt_debug(
                        "Refresh attempt "
                        f"{attempt}/{attempts} failed; attempting re-authentication: {exc}"
                    )
                    try:
                        if self.client is not None:
                            reauthenticate = getattr(
                                self.client, "reauthenticate", None
                            )
                            if callable(reauthenticate):
                                reauthenticate("browser refresh")
                    except Exception as reauth_exc:
                        _xt_debug(
                            "Refresh re-authentication attempt failed: "
                            f"{type(reauth_exc).__name__}: {reauth_exc}"
                        )
                    time.sleep(delay)

            if last_error is not None:
                raise last_error

            self._invoke_on_ui_thread(
                lambda: self._apply_refresh_result(
                    generation,
                    project_id,
                    dataset_id,
                    projects,
                    project_index,
                    datasets,
                    dataset_index,
                    images,
                ),
                wait=False,
            )
        except Exception as exc:
            refresh_error = exc
            self._invoke_on_ui_thread(
                lambda: self._finish_refresh_error(generation, refresh_error),
                wait=False,
            )

    def _apply_refresh_result(
        self,
        generation,
        requested_project_id,
        requested_dataset_id,
        projects,
        project_index,
        datasets,
        dataset_index,
        images,
    ):
        """Apply the refresh result for `OMEROBrowserDialog`.

        Inputs: `generation`, `requested_project_id`, `requested_dataset_id`,
        `projects`, `project_index`, `datasets`, `dataset_index`, `images`. Output:
        None.
        """
        if generation != self._refresh_generation or not self._connected:
            return

        projects = list(projects or [])
        datasets = list(datasets or [])
        images = list(images or [])

        self._all_projects_data = projects
        self.projects_data = list(projects)
        self._apply_browser_search_filter("projects")

        if project_index is None:
            self._pid = None
            self._did = None
            self._all_datasets_data = []
            self._all_images_data = []
            self.datasets_data = []
            self.images_data = []
            self._image_selection_anchor = None
            self._replace_listbox_items(self.dlist, [])
            self._replace_listbox_items(self.ilist, [])
            self._clear_listbox_selection(self.plist)
            self._refresh_load_button_text()
            if requested_project_id is None:
                self._set_status("Project list refreshed", "#d4edda")
            else:
                self._set_status(
                    "Selected project is no longer available; projects refreshed",
                    "#fff3cd",
                )
            self._finish_refresh_buttons()
            self._restore_idle_connection_indicator()
            return

        selected_project_id = self._entity_id(projects[project_index])
        self._pid = selected_project_id
        self._select_listbox_index(
            self.plist,
            self._find_entity_index(self.projects_data, selected_project_id),
        )
        self._all_datasets_data = datasets
        self.datasets_data = list(datasets)
        self._apply_browser_search_filter("datasets")

        if dataset_index is None:
            self._did = None
            self._all_images_data = []
            self.images_data = []
            self._image_selection_anchor = None
            self._replace_listbox_items(self.ilist, [])
            self._clear_listbox_selection(self.dlist)
            self._refresh_load_button_text()
            if requested_dataset_id is None:
                self._set_status("Refresh completed", "#d4edda")
            else:
                self._set_status(
                    "Selected dataset is no longer available; datasets refreshed",
                    "#fff3cd",
                )
            self._finish_refresh_buttons()
            self._restore_idle_connection_indicator()
            return

        selected_dataset_id = self._entity_id(datasets[dataset_index])
        self._did = selected_dataset_id
        self._select_listbox_index(
            self.dlist,
            self._find_entity_index(self.datasets_data, selected_dataset_id),
        )
        self._all_images_data = images
        self.images_data = list(images)
        self._image_selection_anchor = None
        self._apply_browser_search_filter("images")
        self._clear_listbox_selection(self.ilist)
        self._image_selection_anchor = None
        self._refresh_load_button_text()
        self._set_status("OMERO browser refreshed", "#d4edda")
        self._finish_refresh_buttons()
        self._restore_idle_connection_indicator()

    def _finish_refresh_error(self, generation, refresh_error):
        """Show a refresh failure and restore the browser controls.

        Inputs: `generation`, `refresh_error`. Output: None.
        """
        if generation != self._refresh_generation:
            return
        self._set_status("Refresh failed", "#f8d7da")
        self._set_connection_indicator("error")
        self._show_error("Refresh Failed", str(refresh_error))
        _xt_debug(f"Refresh failed: {type(refresh_error).__name__}: {refresh_error}")
        self._finish_refresh_buttons()

    def _finish_refresh_buttons(self):
        """Refresh button availability after project or dataset selection changes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._refresh_in_progress = False
        self._set_refresh_button_state(
            _tk_constant("NORMAL", "normal")
            if getattr(self, "_connected", False)
            and _stringvar_value(getattr(self, "converter_var", None))
            in {"OMERO", "Imaris"}
            and not getattr(self, "_folder_export_in_progress", False)
            and not getattr(self, "_load_in_progress", False)
            else _tk_constant("DISABLED", "disabled")
        )
        self._set_load_button_for_converter()
        self._update_export_button_state()

    @staticmethod
    def _image_cache_subdir(image_id):
        """Return the image cache subdir for `OMEROBrowserDialog`.

        Inputs: `image_id` OMERO image ID. Output: image cache subdir result.
        """
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(image_id)).strip(" .")
        if not safe_id:
            safe_id = "unknown"
        if safe_id.upper() in _WINDOWS_RESERVED_FILENAMES:
            safe_id = f"_{safe_id}"
        return f"img_{safe_id[:80]}"

    @staticmethod
    def _image_display_name(img):
        """Return the image display name for `OMEROBrowserDialog`.

        Inputs: `img`. Output: `str`.
        """
        if isinstance(img, dict):
            name = img.get("name")
            if name:
                return str(name)
            image_id = img.get("id")
            if image_id is not None:
                return f"Image {image_id}"
        return "selected image"

    @staticmethod
    def _download_filename_for_image(img, converter):
        """Return the intended local filename for a selected OMERO image.

        Inputs: `img`, `converter`. Output: safe local filename.
        """
        image_id = img.get("id") if isinstance(img, dict) else None
        fallback_stem = OMEROBrowserDialog._image_cache_subdir(
            image_id if image_id is not None else "unknown"
        )
        image_name = OMEROBrowserDialog._image_display_name(img)
        if converter == "OMERO":
            return _safe_download_filename(
                image_name,
                f"{fallback_stem}.ims",
                default_extension=".ims",
            )
        if converter == "Imaris":
            filename = _safe_download_filename(
                image_name,
                f"{fallback_stem}.ome.tif",
            )
            if os.path.splitext(filename)[1].lower() not in {".tif", ".tiff", ".tf8"}:
                filename = f"{filename}.ome.tif"
            return filename
        raise RuntimeError(f"Unsupported converter: {converter}")

    def _planned_download_filenames(self, images, converter):
        """Return intended local filenames for the selected import.

        Inputs: `images`, `converter`. Output: list of filename strings.
        """
        return [
            self._download_filename_for_image(img, converter)
            for img in list(images or [])
            if isinstance(img, dict)
        ]

    @staticmethod
    def _repeated_download_filenames(filenames):
        """Return planned filenames that repeat within the same selection.

        Inputs: `filenames`. Output: ordered list of filename strings.
        """
        repeated = []
        seen = set()
        emitted = set()
        for filename in filenames:
            safe_filename = _safe_download_filename(filename, "download")
            if safe_filename in seen and safe_filename not in emitted:
                repeated.append(safe_filename)
                emitted.add(safe_filename)
            seen.add(safe_filename)
        return repeated

    @staticmethod
    def _existing_download_filename_conflicts(download_dir, filenames):
        """Return planned filenames that already exist in the download folder.

        Inputs: `download_dir`, `filenames`. Output: ordered list of filename strings.
        """
        conflicts = []
        seen = set()
        for filename in filenames:
            safe_filename = _safe_download_filename(filename, "download")
            if safe_filename in seen:
                continue
            if os.path.exists(os.path.join(download_dir, safe_filename)):
                conflicts.append(safe_filename)
                seen.add(safe_filename)
        return conflicts

    @staticmethod
    def _duplicate_download_prompt_message(conflicts, repeated=None):
        """Return user-facing duplicate download prompt text.

        Inputs: `conflicts`, `repeated`. Output: prompt message.
        """
        names = list(conflicts or [])
        repeated_names = [name for name in list(repeated or []) if name not in names]
        names.extend(repeated_names)
        preview_limit = 8
        preview = "\n".join(f"- {name}" for name in names[:preview_limit])
        if len(names) > preview_limit:
            preview += f"\n- ... and {len(names) - preview_limit} more"
        return (
            "The selected folder already contains one or more planned output "
            "filenames, or the current selection includes repeated names.\n\n"
            f"{preview}\n\n"
            "Choose Yes to replace matching files in the selected folder. If "
            "selected images share one name, later copies will be saved with "
            "unique names so no selected image overwrites another. Choose No "
            "to keep existing files and save this import with unique names, or "
            "Cancel to stop before the export starts."
        )

    def _resolve_duplicate_download_policy(self, images, converter, download_dir):
        """Resolve how the current import should handle existing local files.

        Inputs: `images`, `converter`, `download_dir`. Output: `(proceed, policy)`.
        """
        planned_filenames = self._planned_download_filenames(images, converter)
        repeated = self._repeated_download_filenames(planned_filenames)
        conflicts = self._existing_download_filename_conflicts(
            download_dir,
            planned_filenames,
        )
        if not conflicts and not repeated:
            return True, None
        answer = self._ask_yes_no_cancel_dialog(
            "Duplicate Filenames",
            self._duplicate_download_prompt_message(conflicts, repeated),
        )
        if answer is None:
            return False, None
        if answer:
            return True, DUPLICATE_DOWNLOAD_POLICY_REPLACE
        return True, DUPLICATE_DOWNLOAD_POLICY_UNIQUE

    @staticmethod
    def _per_file_duplicate_download_policy(
        target_filename,
        duplicate_policy,
        planned_names_seen,
    ):
        """Return a per-file duplicate policy that avoids batch self-overwrite.

        Inputs: `target_filename`, `duplicate_policy`, `planned_names_seen`. Output:
        duplicate policy string or None.
        """
        safe_filename = _safe_download_filename(target_filename, "download")
        if safe_filename in planned_names_seen:
            return DUPLICATE_DOWNLOAD_POLICY_UNIQUE
        planned_names_seen.add(safe_filename)
        return duplicate_policy

    def _selected_image_export_key(self, file_path):
        """Return a stable key for a tracked selected-image export path.

        Inputs: `file_path`. Output: key string or empty string.
        """
        path = _coerce_path(file_path)
        if path is None:
            return ""
        try:
            return os.path.normcase(os.path.abspath(os.fspath(path)))
        except (OSError, ValueError):
            return os.path.normcase(os.path.normpath(os.fspath(path)))

    def _mark_selected_image_export_file(self, file_path):
        """Track a selected-image export downloaded by this dialog.

        Inputs: `file_path`. Output: normalized path string.
        """
        candidate = _existing_regular_file_path(file_path)
        if candidate is None:
            raise RuntimeError("Selected-image export is missing after download.")
        if not is_tiff_file(candidate):
            raise RuntimeError("Selected-image export is not a readable TIFF file.")
        tracked_candidate = getattr(self, "_selected_image_export_files", None)
        tracked: Set[Any]
        if isinstance(tracked_candidate, set):
            tracked = tracked_candidate
        else:
            tracked = set()
            self._selected_image_export_files = tracked
        tracked.add(self._selected_image_export_key(candidate))
        return str(candidate)

    def _is_tracked_selected_image_export_file(self, file_path):
        """Return whether `file_path` is a selected-image export from this dialog.

        Inputs: `file_path`. Output: bool.
        """
        tracked_candidate = getattr(self, "_selected_image_export_files", None)
        tracked: Set[Any] = (
            tracked_candidate if isinstance(tracked_candidate, set) else set()
        )
        key = self._selected_image_export_key(file_path)
        return bool(key and key in tracked and is_tiff_file(file_path))

    def _download_selected_image_with_imaris_converter(
        self,
        image_id,
        download_dir,
        target_filename=None,
        duplicate_policy=None,
        cancel_event=None,
    ):
        """Export one OMERO Image ID for direct Imaris handoff.

        Inputs: `image_id`, `download_dir`, `target_filename`, `duplicate_policy`.
        Output: selected-image export path.
        """
        self._set_status(
            f"Imaris converter: exporting selected Image {image_id} as OME-TIFF...",
            "#fff3cd",
        )
        ome_tiff_file = self.client.download_selected_image_ome_tiff(
            image_id,
            download_dir,
            fallback_name=f"{self._image_cache_subdir(image_id)}.ome.tif",
            target_filename=target_filename,
            duplicate_policy=duplicate_policy,
            cancel_event=cancel_event,
        )
        selected_export = self._mark_selected_image_export_file(ome_tiff_file)
        _xt_debug(
            "Imaris converter: selected Image ID exported via standard OMERO.web "
            "for direct Imaris handoff"
        )
        return selected_export

    def _selected_images(self):
        """Return the selected images for `OMEROBrowserDialog`.

        Inputs: none. Output: `selected`.
        """
        selected: List[Any] = []
        ilist = getattr(self, "ilist", None)
        curselection = getattr(ilist, "curselection", None)
        if not callable(curselection):
            return selected
        images_data = list(getattr(self, "images_data", []) or [])
        for raw_index in curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(images_data):
                selected.append(images_data[index])
        return selected

    def _load(self):
        """Load the load for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: loads the described state and returns None.
        """
        if not getattr(self, "_connected", False) or self.client is None:
            self._show_warning_dialog("Not Connected", "Please connect to OMERO first.")
            return
        if getattr(self, "_refresh_in_progress", False):
            self._show_warning_dialog(
                "Refresh In Progress",
                "Please wait for the OMERO browser refresh to finish.",
            )
            return

        selected_path = self._current_local_folder_path()
        if not _is_structurally_valid_folder_path(selected_path):
            self._show_warning_dialog(
                "No Path Selected",
                "Please type or select a folder path first.",
            )
            self._set_load_button_for_converter()
            return
        if not self._mark_folder_path_write_state(selected_path):
            self._show_folder_path_write_error()
            return
        self.export_dir = os.fspath(_coerce_path(selected_path))

        selected_images = self._selected_images()
        if not selected_images:
            self._show_warning_dialog(
                "No Selection", "Please select at least one image"
            )
            self._set_load_button_for_converter()
            return

        converter = _stringvar_value(getattr(self, "converter_var", None))
        available_converter_options = tuple(
            getattr(self, "_available_converter_options", ())
        )
        if converter not in set(available_converter_options):
            self._show_warning_dialog(
                "No Converter",
                "Please connect to OMERO and select an available converter.",
            )
            self._set_converter_options(list(available_converter_options))
            return

        worker_args: Tuple[Any, ...]
        if len(selected_images) == 1:
            img = selected_images[0]
            confirmation = (
                "Download and open:\n"
                f"{self._image_display_name(img)}\n\n"
                f"Converter: {converter}"
            )
            worker_args = (img, converter)
            worker_target = self._load_worker
        else:
            if converter == "OMERO":
                confirmation = (
                    f"Download {len(selected_images)} selected images with the "
                    "OMERO converter?\n\n"
                    + _omero_multi_handoff_notice(
                        self.export_dir,
                        len(selected_images) - 1,
                    )
                    + f"\n\nConverter: {converter}"
                )
            else:
                confirmation = (
                    f"Download {len(selected_images)} selected images and hand them "
                    "to Imaris after all files are ready?\n\n"
                    f"Converter: {converter}"
                )
            worker_args = (selected_images, converter)
            worker_target = self._load_multiple_worker

        if not self._ask_yes_no_dialog(
            "Confirm Load",
            confirmation,
        ):
            return

        proceed, duplicate_policy = self._resolve_duplicate_download_policy(
            selected_images,
            converter,
            self.export_dir,
        )
        if not proceed:
            return
        worker_args = (*worker_args, duplicate_policy)

        self._append_current_path_to_imaris_arena_if_enabled()
        self._set_actions_busy_for_load(True)
        operation_event = getattr(self, "_operation_cancel_event", None)
        operation_generation = getattr(self, "_operation_generation", None)
        if operation_event is not None and operation_generation is not None:
            worker_args = (*worker_args, operation_event, operation_generation)
        threading.Thread(
            target=worker_target,
            args=worker_args,
            daemon=True,
        ).start()

    def _reenable_load_button(self):
        """Re-enable the load button after an asynchronous UI operation.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        clear_busy = getattr(self, "_set_actions_busy_for_load", None)
        if callable(clear_busy):
            clear_busy(False)
            return
        load_btn = getattr(self, "load_btn", None)
        if load_btn is not None:
            load_btn.config(state=_tk_constant("NORMAL", "normal"))

    def _load_worker(
        self,
        img,
        converter,
        duplicate_policy=None,
        operation_event=None,
        operation_generation=None,
    ):
        """Load the worker for `OMEROBrowserDialog`.

        Inputs: `img`, `converter`, `duplicate_policy`. Output: None. Raises:
        RuntimeError when validation or the called operation fails.
        """
        cancel_event = (
            operation_event
            if operation_event is not None
            else getattr(self, "_operation_cancel_event", None)
        )
        workflow_succeeded = False
        workflow_cancelled = False
        try:
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)
            image_id = img.get("id") if isinstance(img, dict) else None
            if image_id is None:
                raise RuntimeError("Selected image is missing an OMERO image id.")
            image_name = self._image_display_name(img)
            _xt_debug(f"Load worker starting image_id={image_id} converter={converter}")
            if (
                converter == "OMERO"
                and not self._ensure_native_open_ready_before_export()
            ):
                raise RuntimeError(
                    "Cannot open files in the running Imaris session because no "
                    "compatible Imaris bridge is available. Download/conversion "
                    "was not started."
                )
            if (
                converter == "Imaris"
                and not self._ensure_imaris_converter_handoff_ready_before_export()
            ):
                raise RuntimeError(
                    "Cannot submit selected Image exports to Imaris because "
                    "ImarisFileConverter.exe could not be discovered. "
                    "Download/export was not started."
                )
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)

            download_dir = self.export_dir
            target_filename = self._download_filename_for_image(img, converter)

            if converter == "OMERO":
                self._set_status(
                    f"OMERO converter: exporting IMS for {image_name}...", "#fff3cd"
                )
                self._set_status(
                    "OMERO converter: running server-side IMS export...", "#fff3cd"
                )
                downloaded_file = self.client.download_ims_export(
                    image_id,
                    download_dir,
                    fallback_name=f"{self._image_cache_subdir(image_id)}.ims",
                    target_filename=target_filename,
                    duplicate_policy=duplicate_policy,
                    cancel_event=cancel_event,
                )
                require_ims = True
                selected_image_export = False
                success_status = "Opened IMS in current Imaris session"
                success_message = "IMS file opened in the current Imaris session."
                failure_message = "Failed to open IMS in the current Imaris session."
            elif converter == "Imaris":
                downloaded_file = self._download_selected_image_with_imaris_converter(
                    image_id,
                    download_dir,
                    target_filename=target_filename,
                    duplicate_policy=duplicate_policy,
                    cancel_event=cancel_event,
                )
                require_ims = False
                selected_image_export = True
                success_status = (
                    "Submitted selected Image export to Imaris File Converter"
                )
                success_message = (
                    "Selected Image export submitted to Imaris File Converter."
                )
                failure_message = (
                    "Failed to submit the selected Image export to "
                    "Imaris File Converter."
                )
            else:
                raise RuntimeError(f"Unsupported converter: {converter}")

            if not downloaded_file or not os.path.exists(downloaded_file):
                raise RuntimeError("Failed to download file from OMERO.")
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)

            if require_ims and not is_ims_file(downloaded_file):
                raise RuntimeError(
                    "Downloaded file is not a valid IMS (HDF5) file. "
                    "Refusing to open the invalid export in Imaris. "
                    "Please verify that the conversion completed successfully."
                )
            if (
                selected_image_export
                and not self._is_tracked_selected_image_export_file(downloaded_file)
            ):
                raise RuntimeError(
                    "Downloaded selected Image export is not a readable TIFF file. "
                    "Refusing to open it in Imaris."
                )

            self._set_status(
                f"Downloaded: {os.path.basename(downloaded_file)}", "#d4edda"
            )
            _xt_debug("Downloaded file stored in selected local connector path")

            self.temp_files.append(downloaded_file)
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)

            # Run the final handoff on the UI thread so IMS opens keep the XT
            # handle in the same thread/apartment as the original dialog.
            success = self._invoke_on_ui_thread(
                lambda: self._open_downloaded_file_in_imaris(
                    downloaded_file,
                    require_ims=require_ims,
                    selected_image_export=selected_image_export,
                )
            )
            success_title = "Success"

            if success:
                self._set_status(success_status, "#d4edda")
                self._show_info(
                    success_title,
                    success_message,
                )
                workflow_succeeded = True
            else:
                raise RuntimeError(failure_message)

        except _ConnectorOperationCancelled as exc:
            workflow_cancelled = True
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("Load into Imaris stopped by user", "#fff3cd")
            _xt_debug(f"Load into Imaris stopped by user in background: {exc}")
        except Exception as e:
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("✗ Failed", "#f8d7da")
                self._show_error("Error", str(e))
                _xt_debug(f"Load worker failed: {type(e).__name__}: {e}")
            else:
                _xt_debug(
                    f"Stopped load background worker failed: {type(e).__name__}: {e}"
                )
        finally:
            if self._operation_is_current(operation_event, operation_generation):
                self._invoke_on_ui_thread(
                    partial(
                        self._finish_load_workflow,
                        workflow_succeeded,
                        workflow_cancelled,
                    ),
                    wait=False,
                )
            else:
                _xt_debug("Stopped load background worker finished.")

    def _load_multiple_worker(
        self,
        images,
        converter,
        duplicate_policy=None,
        operation_event=None,
        operation_generation=None,
    ):
        """Load the multiple worker for `OMEROBrowserDialog`.

        Inputs: `images`, `converter`, `duplicate_policy`. Output: None. Raises:
        RuntimeError when validation or the called operation fails.
        """
        cancel_event = (
            operation_event
            if operation_event is not None
            else getattr(self, "_operation_cancel_event", None)
        )
        workflow_succeeded = False
        workflow_cancelled = False
        try:
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)
            selected_images = [
                img for img in list(images or []) if isinstance(img, dict)
            ]
            if len(selected_images) < 2:
                raise RuntimeError(
                    "Multiple-image loading requires at least two selected images."
                )
            count = len(selected_images)
            _xt_debug(
                f"Multi-image load worker starting count={count} converter={converter}"
            )

            if converter == "OMERO":
                if not self._ensure_native_open_ready_before_export():
                    raise RuntimeError(
                        "Cannot open files in the running Imaris session because no "
                        "compatible Imaris bridge is available. Download/conversion "
                        "was not started."
                    )
            elif converter == "Imaris":
                if not self._ensure_imaris_converter_handoff_ready_before_export():
                    raise RuntimeError(
                        "Cannot submit selected Image exports to Imaris because "
                        "ImarisFileConverter.exe could not be discovered. "
                        "Download/export was not started."
                    )
            else:
                raise RuntimeError(f"Unsupported converter: {converter}")
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)

            downloaded_files = []
            require_ims = converter == "OMERO"
            selected_image_export = converter == "Imaris"
            download_dir = self.export_dir
            planned_names_seen: Set[str] = set()
            for index, img in enumerate(selected_images, start=1):
                self._raise_if_current_operation_cancelled(
                    "Load into Imaris",
                    cancel_event,
                )
                image_id = img.get("id")
                if image_id is None:
                    raise RuntimeError("A selected image is missing an OMERO image id.")
                image_name = self._image_display_name(img)
                target_filename = self._download_filename_for_image(img, converter)
                per_file_duplicate_policy = self._per_file_duplicate_download_policy(
                    target_filename,
                    duplicate_policy,
                    planned_names_seen,
                )

                if converter == "OMERO":
                    self._set_status(
                        f"OMERO converter: exporting IMS {index}/{count}: {image_name}",
                        "#fff3cd",
                    )
                    downloaded_file = self.client.download_ims_export(
                        image_id,
                        download_dir,
                        fallback_name=f"{self._image_cache_subdir(image_id)}.ims",
                        target_filename=target_filename,
                        duplicate_policy=per_file_duplicate_policy,
                        cancel_event=cancel_event,
                    )
                else:
                    self._set_status(
                        f"Imaris converter: exporting selected Image {index}/{count}: "
                        f"{image_name}",
                        "#fff3cd",
                    )
                    downloaded_file = (
                        self._download_selected_image_with_imaris_converter(
                            image_id,
                            download_dir,
                            target_filename=target_filename,
                            duplicate_policy=per_file_duplicate_policy,
                            cancel_event=cancel_event,
                        )
                    )

                if not downloaded_file or not os.path.exists(downloaded_file):
                    raise RuntimeError(
                        "Failed to download one selected file from OMERO."
                    )
                if require_ims and not is_ims_file(downloaded_file):
                    raise RuntimeError(
                        "A downloaded file is not a valid IMS (HDF5) file. "
                        "Refusing to open the selected batch."
                    )
                if (
                    selected_image_export
                    and not self._is_tracked_selected_image_export_file(downloaded_file)
                ):
                    raise RuntimeError(
                        "A downloaded selected Image export is not a readable TIFF "
                        "file. Refusing to open the selected batch."
                    )

                downloaded_files.append(downloaded_file)
                self.temp_files.append(downloaded_file)

            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)
            if require_ims:
                handoff_files = downloaded_files[:1]
                self._set_status(
                    "All selected IMS files are ready; opening the first one in "
                    "Imaris...",
                    "#fff3cd",
                )
            else:
                handoff_files = downloaded_files
                self._set_status(
                    "All selected files are ready; submitting them to Imaris...",
                    "#fff3cd",
                )
            _xt_debug(
                f"Prepared {len(downloaded_files)} selected files before Imaris handoff"
            )
            self._raise_if_current_operation_cancelled("Load into Imaris", cancel_event)

            success = self._invoke_on_ui_thread(
                lambda: self._open_downloaded_files_in_imaris(
                    handoff_files,
                    require_ims=require_ims,
                    selected_image_export=selected_image_export,
                )
            )
            success_title = "Success"
            if require_ims:
                success_status = (
                    "Opened first selected IMS file; remaining IMS files saved"
                )
                success_message = _omero_multi_handoff_notice(
                    download_dir,
                    len(downloaded_files) - 1,
                    completed=True,
                )
                failure_message = "Imaris did not accept the first prepared IMS file."
            else:
                success_status = (
                    "Submitted selected Image exports to Imaris File Converter"
                )
                success_message = (
                    "All selected Image exports were submitted to "
                    "Imaris File Converter after every download completed."
                )
                failure_message = (
                    "Imaris File Converter did not accept the selected Image "
                    "export batch handoff."
                )

            if success:
                self._set_status(success_status, "#d4edda")
                self._show_info(success_title, success_message)
                workflow_succeeded = True
            else:
                raise RuntimeError(failure_message)

        except _ConnectorOperationCancelled as exc:
            workflow_cancelled = True
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("Load into Imaris stopped by user", "#fff3cd")
            _xt_debug(f"Multi-image load stopped by user in background: {exc}")
        except Exception as e:
            if self._operation_is_current(operation_event, operation_generation):
                self._set_status("✗ Failed", "#f8d7da")
                self._show_error("Error", str(e))
                _xt_debug(f"Multi-image load worker failed: {type(e).__name__}: {e}")
            else:
                _xt_debug(
                    "Stopped multi-image load background worker failed: "
                    f"{type(e).__name__}: {e}"
                )
        finally:
            if self._operation_is_current(operation_event, operation_generation):
                self._invoke_on_ui_thread(
                    partial(
                        self._finish_load_workflow,
                        workflow_succeeded,
                        workflow_cancelled,
                    ),
                    wait=False,
                )
            else:
                _xt_debug("Stopped multi-image load background worker finished.")

    def show(self):
        """Start the GUI event loop.

        Inputs: no caller arguments. Output: starts the described state and returns None.
        """
        self.root.mainloop()


# =============================================================================
# XTENSION ENTRY POINT
# =============================================================================


def _xt_log_path():
    """Return the sanitized Imaris XT diagnostic log path.

    Inputs: none. Output: `str` result.
    """
    try:
        return str(_connector_settings_env_path().parent / XT_LOG_FILE_NAME)
    except OSError:
        return ""


def _ensure_xt_log_directory(log_dir):
    """Ensure the connector diagnostic log directory exists privately.

    Inputs: `log_dir`. Output: bool.
    """
    try:
        if log_dir.is_symlink():
            return False
        if log_dir.exists() and not log_dir.is_dir():
            return False
        log_dir.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(os.fspath(log_dir), PRIVATE_DIRECTORY_MODE)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _xt_log_backup_path(log_path, index):
    """Return one rolling backup path for an XT diagnostic log.

    Inputs: `log_path`, backup `index`. Output: `Path`.
    """
    return log_path.with_name(f"{log_path.name}.{int(index)}")


def _safe_unlink_xt_log_path(path):
    """Remove one XT log path only when it is a regular file or symlink.

    Inputs: `path`. Output: None.
    """
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
    except OSError as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )


def _rotate_xt_log_if_needed(log_path, incoming_bytes):
    """Rotate XT diagnostic logs before appending beyond the size limit.

    Inputs: `log_path`, `incoming_bytes`. Output: None.
    """
    try:
        if not log_path.exists() or not log_path.is_file():
            return
        if log_path.stat().st_size + max(0, int(incoming_bytes)) <= XT_LOG_MAX_BYTES:
            return
        oldest = _xt_log_backup_path(log_path, XT_LOG_BACKUP_COUNT)
        _safe_unlink_xt_log_path(oldest)
        for index in range(XT_LOG_BACKUP_COUNT - 1, 0, -1):
            source = _xt_log_backup_path(log_path, index)
            if source.is_symlink():
                _safe_unlink_xt_log_path(source)
                continue
            if source.is_file():
                os.replace(
                    os.fspath(source),
                    os.fspath(_xt_log_backup_path(log_path, index + 1)),
                )
        os.replace(os.fspath(log_path), os.fspath(_xt_log_backup_path(log_path, 1)))
    except (OSError, TypeError, ValueError) as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )


def _xt_write_log(log_path, msg):
    """Append a sanitized diagnostic message to the Imaris XT log.

    Inputs: `log_path`, `msg`. Output: None.
    """
    candidate = _safe_xt_log_file(log_path)
    if candidate is None:
        return
    safe_msg = _sanitize_xt_log_message(msg)
    if not safe_msg.endswith("\n"):
        safe_msg += "\n"
    encoded_length = len(safe_msg.encode("utf-8", errors="replace"))
    descriptor = None
    try:
        if not _ensure_xt_log_directory(candidate.parent):
            return
        with _XT_LOG_LOCK:
            _rotate_xt_log_if_needed(candidate, encoded_length)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
            descriptor = os.open(os.fspath(candidate), flags, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "a", encoding="utf-8", errors="replace") as f:
                descriptor = None
                f.write(safe_msg)
            with contextlib.suppress(OSError):
                os.chmod(os.fspath(candidate), PRIVATE_FILE_MODE)
    except (OSError, TypeError, ValueError) as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _xt_show_fatal(title, message):
    """Show a fatal Imaris XT startup error to the operator.

    Inputs: `title`, `message`. Output: None.
    """
    try:
        messagebox.showerror(title, message)
    except Exception:
        _xt_console_log(title + ": " + message)


def _xt_wait_for_enter_to_close():
    """Prompt the operator before closing a console-launched connector.

    Inputs: none. Output: None.
    """
    _xt_console_log("Press ENTER to close...", end="", flush=True)
    input()


def XTOmeroConnector(aImarisId):
    """Called by Imaris.

    Inputs: `aImarisId`. Output: None.
    """
    platform_status = _windows_platform_status()
    log_path = _xt_log_path()
    _XT_RUNTIME_STATE.log_path = log_path
    if not platform_status.supported:
        block_message = "XTOmeroConnector startup blocked: " + platform_status.message
        _xt_console_log(block_message)
        return

    previous_interrupt_handlers = _install_xt_console_interrupt_guard()
    settings_path = None
    try:
        settings_path = _connector_settings_env_path()
        _prepare_connector_settings_for_current_version(settings_path)
        _ensure_connector_settings_imaris_executable(settings_path)
    except OSError as exc:
        _log_connector_settings_event(
            f"Connector settings startup preparation failed: {type(exc).__name__}"
        )
    _configure_xt_console_visibility(_load_connector_show_log_preference(settings_path))
    _set_process_window_title("OMERO Connector")
    try:
        _xt_write_log(log_path, "=== XTOmeroConnector starting ===")
        _xt_write_log(log_path, platform_status.message)
        _ensure_tk_loaded()
        _xt_write_log(log_path, f"Python: {sys.version}")
        _log_imaris_xt_diagnostics()

        vImaris = None
        try:
            vImaris = _resolve_imaris_application(
                aImarisId,
                retries=IMARIS_HANDLE_RETRY_ATTEMPTS,
                retry_interval=IMARIS_HANDLE_RETRY_INTERVAL,
            )
        except Exception:
            # When run outside Imaris, aImarisId may be None or an app object.
            vImaris = aImarisId if _looks_like_imaris_application(aImarisId) else None

        if vImaris is None:
            _xt_write_log(
                log_path,
                f"Imaris handle resolution returned None for entrypoint={aImarisId!r}",
            )
        else:
            _xt_write_log(
                log_path,
                f"Resolved Imaris handle type={type(vImaris).__name__} "
                f"for entrypoint={aImarisId!r}",
            )

        dialog = OMEROBrowserDialog(vImaris, imaris_id=aImarisId)
        dialog.show()

    except KeyboardInterrupt:
        _xt_write_log(log_path, "Ignored command-window Ctrl+C during XT runtime.")
        _xt_console_log("Ignored connector command-window Ctrl+C.")
    except Exception as e:
        tb = traceback.format_exc()
        _xt_write_log(log_path, tb)
        _xt_show_fatal(
            "XTOmeroConnector crashed",
            f"{e}\n\nA detailed log was written to:\n{log_path}",
        )
        # Keep console open when launched by double-click / Imaris
        if _XT_RUNTIME_STATE.console_output_enabled:
            try:
                _xt_wait_for_enter_to_close()
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
    finally:
        _restore_xt_console_interrupt_guard(previous_interrupt_handlers)


if __name__ == "__main__":
    # Manual debug mode (outside Imaris): keep the console open on error.
    try:
        XTOmeroConnector(None)
    except Exception as e:
        _xt_console_log("Fatal: " + str(e))
        if _XT_RUNTIME_STATE.console_output_enabled:
            try:
                _xt_wait_for_enter_to_close()
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
