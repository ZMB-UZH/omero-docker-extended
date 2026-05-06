#
# <CustomTools>
#  <Menu>
#   <Item name="OMERO Connector" icon="Python3" tooltip="Interact with OMERO">
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
import json
import logging
import ntpath
import os
import posixpath
import random
import re
import socket
import stat
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
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


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

# Default timeout/poll values for client-side export polling.
# These must NOT depend on server-side packages (omero_plugin_common)
# because this script runs inside Imaris on the user's machine.
EXPORT_TIMEOUT = 3600  # seconds
EXPORT_POLL_INTERVAL = 2.0  # seconds
DOWNLOAD_CHUNK_SIZE_ENV = "OMERO_IMARIS_DOWNLOAD_CHUNK_BYTES"
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
NATIVE_BRIDGE_LAUNCH_TIMEOUT = 600
NATIVE_BRIDGE_LAUNCH_POLL_INTERVAL = 1.0
NATIVE_BRIDGE_REVALIDATE_AFTER = 30.0
IMARIS_OPEN_VERIFY_TIMEOUT = 10.0
IMARIS_OPEN_VERIFY_INTERVAL = 0.25
OMERO_CONNECTOR_WINDOW_WIDTH = 1000
OMERO_CONNECTOR_WINDOW_HEIGHT = 760
MINIMUM_WINDOWS_MAJOR = 10
MINIMUM_WINDOWS_MINOR = 0
CONVERTER_MENU_FONT = ("Arial", 10)
ACTION_ROW_HORIZONTAL_PAD = 10
ACTION_BUTTON_PAD = 2
STATUS_TEXT_PAD = ACTION_ROW_HORIZONTAL_PAD + ACTION_BUTTON_PAD
CONNECTION_LABEL_WIDTH = len("Username:")
STATUS_NEUTRAL_BG = "#dfe5eb"
CONNECTOR_HELP_ICON_BG = "#b9e4ff"
CONNECTOR_HELP_ICON_ACTIVE_BG = "#9ed7f6"
CONNECTOR_HELP_ICON_FG = "#174a63"
CONNECTOR_INFO_ICON_BG = "#d8dee6"
CONNECTOR_INFO_ICON_ACTIVE_BG = "#c6ced8"
CONNECTOR_INFO_ICON_FG = "#2f3a45"
CONNECTOR_PANEL_ICON_SIZE = 36
CONNECTOR_PANEL_ICON_FRAME_HEIGHT = 42
CONNECTOR_PANEL_ICON_FONT = ("Segoe UI", 13, "bold")
PASSWORD_REVEAL_DURATION_MS = 30000
PASSWORD_REVEAL_BUTTON_SIZE = 26
PASSWORD_REVEAL_ICON_BG = "#f8fafc"
PASSWORD_REVEAL_ICON_ACTIVE_BG = "#e7f0fb"
PASSWORD_REVEAL_ICON_FG = "#425466"
AUTOSAVE_SETTINGS_FRAME_WIDTH = 168
CONVERTER_MENU_WIDTH = 14
BROWSER_PANEL_DEFAULT_FRACTIONS = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
BROWSER_PANEL_MIN_FRACTION = 0.5 * (1.0 / 3.0)
BROWSER_PANEL_MAX_FRACTION = 1.5 * (1.0 / 3.0)
BROWSER_SPLITTER_WIDTH = 8
BOTTOM_PROGRESS_RESERVED_HEIGHT = 8
FOLDER_PATH_SELECT_BG = "#718096"
FOLDER_PATH_SELECT_ACTIVE_BG = "#60738a"
FOLDER_PATH_PLACEHOLDER = "Type or select local path..."
FOLDER_PATH_PLACEHOLDER_FG = "#9ca3af"
FOLDER_PATH_TEXT_FG = "#111827"
LOCAL_PATH_WRITE_ERROR_TITLE = "Path Not Writable"
LOCAL_PATH_WRITE_ERROR_MESSAGE = (
    "Please select or enter an existing folder that Imaris can write to."
)
LOCAL_PATH_WRITE_TEST_PREFIX = ".omero_connector_write_test_"
PRIVATE_DIRECTORY_MODE = stat.S_IRWXU
PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
AUTOSAVE_SETTINGS_DIR_NAME = ".imaris_omero_connector"
AUTOSAVE_SETTINGS_FILE_NAME = "settings.env"
AUTOSAVE_SETTINGS_ERROR_TITLE = "Settings Not Saved"
AUTOSAVE_SETTINGS_ERROR_MESSAGE = (
    "Autosave settings could not update the OMERO connector settings file."
)
CONNECTOR_INFO_TITLE = "OMERO Connector"
CONNECTOR_INFO_VERSION = "1.0"
CONNECTOR_INFO_AUTHOR = "Efstratios Mitridis"
CONNECTOR_INFO_DISCLAIMER = (
    "This software is provided as-is, without warranty of any kind, express or "
    "implied. Use of the connector is at the user's own risk; the authors and "
    "contributors are not liable for data loss, service interruption, or other "
    "damages arising from its use."
)
CONNECTOR_SETTINGS_KEY_PREFIX = "OMERO_CONNECTOR_"
CONNECTOR_SETTINGS_HOST_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "HOST"
CONNECTOR_SETTINGS_PORT_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "PORT"
CONNECTOR_SETTINGS_USERNAME_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "USER" + "NAME"
CONNECTOR_SETTINGS_HTTPS_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "HTTPS"
CONNECTOR_SETTINGS_PATH_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "PATH"
CONNECTOR_SETTINGS_CONVERTER_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "CONVERTER"
CONNECTOR_SETTINGS_AUTOSAVE_KEY = CONNECTOR_SETTINGS_KEY_PREFIX + "AUTOSAVE_SETTINGS"
CONNECTOR_SETTINGS_KEYS = (
    CONNECTOR_SETTINGS_HOST_KEY,
    CONNECTOR_SETTINGS_PORT_KEY,
    CONNECTOR_SETTINGS_USERNAME_KEY,
    CONNECTOR_SETTINGS_HTTPS_KEY,
    CONNECTOR_SETTINGS_PATH_KEY,
    CONNECTOR_SETTINGS_CONVERTER_KEY,
    CONNECTOR_SETTINGS_AUTOSAVE_KEY,
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
                except Exception:
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
        )
    return (
        ("FileOpen", (file_path,)),
        ("FileOpen", (file_path, "")),
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


def _wait_for_open_observable_effect(app, before, expected_path):
    expected = _normalize_path_for_compare(expected_path)
    deadline = time.time() + OPEN_VERIFY_TIMEOUT
    while time.time() <= deadline:
        current, image_count, data_set_signature = _imaris_app_snapshot(app)
        before_current, before_image_count, before_data_set_signature = before
        if expected and current and current == expected:
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
        if data_set_signature is not None and before_data_set_signature is None:
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
            if getter is None or _wait_for_current_file(getter, file_path):
                return True
            continue
        if _wait_for_open_observable_effect(app, before, file_path):
            return True
    return False


def _open_files_in_imaris(file_paths, app, require_ims=True):
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
        if require_ims and not _is_ims_file(path_text):
            return False
        validated.append(path_text)

    if len(validated) == 1:
        return _open_file_in_imaris(
            validated[0],
            app,
            verification_mode="current_file" if require_ims else "submission_only",
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


def _wait_for_current_file(getter, expected_path):
    expected = _normalize_path_for_compare(expected_path)
    deadline = time.time() + OPEN_VERIFY_TIMEOUT
    while time.time() <= deadline:
        try:
            current = _normalize_path_for_compare(getter())
        except Exception:
            current = ""
        if current and current == expected:
            return True
        time.sleep(OPEN_VERIFY_INTERVAL)
    return False


def _has_open_method(app):
    return callable(getattr(app, "FileOpen", None))


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
    require_ims = bool(payload.get("require_ims", True))
    if not file_paths:
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
    if not _open_files_in_imaris(file_paths, app, require_ims=require_ims):
        print("BRIDGE_RUNNER_OPEN_UNVERIFIED")
        return 3
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
    return Path(path_text)


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
    if not candidate.name.startswith("XTOmeroConnector_") or candidate.suffix != ".log":
        return None
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        parent = candidate.parent.resolve(strict=True)
    except OSError:
        return None
    if parent != temp_root:
        return None
    try:
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
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


def _safe_url_for_log(url):
    """Return a diagnostic URL shape without hostnames, IDs, or query values.

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

    safe_keys = []
    for key, _value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:64] or "param"
        if safe_key not in safe_keys:
            safe_keys.append(safe_key)
    if not safe_keys:
        return path
    query = "&".join(f"{key}=<redacted>" for key in safe_keys)
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
    return all(part not in {".", ".."} for part in Path(path_text).parts)


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
            candidates.append(userprofile)
        home_drive = os.environ.get("HOMEDRIVE", "").strip()
        home_path = os.environ.get("HOMEPATH", "").strip()
        if home_drive and home_path:
            candidates.append(home_drive + home_path)
    with contextlib.suppress(RuntimeError, OSError):
        candidates.append(os.fspath(Path.home()))

    for candidate in candidates:
        home_text = str(candidate or "").strip()
        if not home_text:
            continue
        is_absolute = (
            ntpath.isabs(home_text) if os.name == "nt" else os.path.isabs(home_text)
        )
        if is_absolute:
            return Path(home_text)
    raise OSError("Unable to detect an absolute user home directory")


def _connector_settings_env_path(home_path=None):
    """Return the connector-owned user settings env path.

    Inputs: optional `home_path`. Output: `Path`.
    """
    home = Path(home_path) if home_path is not None else _connector_user_home()
    return home / AUTOSAVE_SETTINGS_DIR_NAME / AUTOSAVE_SETTINGS_FILE_NAME


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
        Path(settings_path)
        if settings_path is not None
        else _connector_settings_env_path()
    )
    try:
        if path.parent.is_symlink():
            _log_connector_settings_event(
                "Connector settings load skipped: settings directory is a symlink"
            )
            return {}
        if path.is_symlink():
            _log_connector_settings_event(
                "Connector settings load skipped: settings file is a symlink"
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


def _filled_connector_setting(settings, key):
    """Return a non-empty connector setting value.

    Inputs: `settings`, `key`. Output: `str`.
    """
    value = settings.get(key, "")
    text = str(value or "")
    return text if text.strip() else ""


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


def _atomic_write_connector_settings(settings, settings_path=None):
    """Atomically write connector settings without storing credentials.

    Inputs: `settings`, optional `settings_path`. Output: None. Raises: OSError.
    """
    descriptor = None
    temp_path = None
    try:
        target = (
            Path(settings_path)
            if settings_path is not None
            else _connector_settings_env_path()
        )
        target_dir = target.parent
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise OSError("Connector settings path is not a regular file")
        if target_dir.is_symlink():
            raise OSError("Connector settings directory is a symlink")
        if target_dir.exists() and not target_dir.is_dir():
            raise OSError("Connector settings directory is not a directory")
        target_dir.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(os.fspath(target_dir), PRIVATE_DIRECTORY_MODE)

        existing_lines = []  # type: List[str]
        if target.exists():
            existing_lines = target.read_text(encoding="utf-8").splitlines()

        normalized = {
            key: str(settings.get(key, "")) for key in CONNECTOR_SETTINGS_KEYS
        }
        content = (
            "\n".join(_connector_settings_output_lines(existing_lines, normalized))
            + "\n"
        )
        temp_path = target_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(os.fspath(temp_path), flags, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(os.fspath(temp_path), os.fspath(target))
        with contextlib.suppress(OSError):
            os.chmod(os.fspath(target), PRIVATE_FILE_MODE)
    except (OSError, TypeError, ValueError) as exc:
        _log_connector_settings_event(
            f"Connector settings write failed: {type(exc).__name__}"
        )
        raise
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
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
    root_path = Path(root)
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

            relative_path = Path(item.path).relative_to(root_path).as_posix()
            if item.is_symlink() or _is_windows_reparse_point(item_stat):
                raise RuntimeError(
                    "Selected folders must not contain symbolic links or reparse-point entries. "
                    f"Blocked entry: {relative_path}"
                )

            if item.is_dir(follow_symlinks=False):
                child_dirs.append(Path(item.path))
                continue
            if not item.is_file(follow_symlinks=False):
                raise RuntimeError(
                    "Selected folders must contain only regular files and directories. "
                    f"Blocked entry: {relative_path}"
                )

            entries.append(
                {
                    "absolute_path": str(Path(item.path)),
                    "relative_path": relative_path,
                    "size": int(getattr(item_stat, "st_size", 0) or 0),
                }
            )

        pending.extend(reversed(child_dirs))

    if not entries:
        raise RuntimeError("The selected folder does not contain any files.")
    return entries


def _xt_debug(message):
    """Write an XT connector debug message when debug logging is enabled.

    Inputs: `message`. Output: None.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {_sanitize_xt_log_message(message)}"
    print(line)
    if _XT_RUNTIME_STATE.log_path:
        _xt_write_log(_XT_RUNTIME_STATE.log_path, line)


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


def _wait_for_imaris_current_file(
    imaris_app,
    expected_path,
    timeout=IMARIS_OPEN_VERIFY_TIMEOUT,
    interval=IMARIS_OPEN_VERIFY_INTERVAL,
):
    """Poll Imaris until its current file matches the expected path.

    Inputs: `imaris_app`, `expected_path`, `timeout`, `interval`. Output: bool.
    """
    getter = _current_imaris_file_getter(imaris_app)
    if getter is None:
        return True

    expected = _normalize_imaris_compare_path(expected_path)
    if not expected:
        return False

    deadline = time.time() + max(0.0, float(timeout))
    while time.time() <= deadline:
        try:
            current = _normalize_imaris_compare_path(getter())
        except Exception as exc:
            _xt_debug(f"Imaris current-file verification failed: {exc}")
            current = ""
        if current and current == expected:
            return True
        time.sleep(max(0.0, float(interval)))
    return False


def _file_open_call_candidates(file_path, verification_mode="current_file"):
    """Return the file open call candidates.

    Inputs: `file_path` file path, `verification_mode`. Output: `tuple`.
    """
    if verification_mode == "current_file":
        return (
            ("FileOpen", (file_path, "")),
            ("FileOpen", (file_path,)),
        )
    return (
        ("FileOpen", (file_path,)),
        ("FileOpen", (file_path, "")),
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
        current, image_count, data_set_signature = _imaris_app_snapshot(imaris_app)
        before_current, before_image_count, before_data_set_signature = before
        if expected and current and current == expected:
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
        if data_set_signature is not None and before_data_set_signature is None:
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
    for method_name, args in _file_open_call_candidates(
        file_path_text,
        verification_mode=verification_mode,
    ):
        method = getattr(imaris_app, method_name, None)
        if not method:
            continue
        try:
            before = _imaris_app_snapshot(imaris_app)
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
                    return True
                last_error = (
                    f"{method_name} returned without an observable Imaris state change"
                )
                continue
            if _wait_for_imaris_current_file(imaris_app, file_path_text):
                return True
            last_error = (
                f"{method_name} returned without making the current Imaris file "
                "match the downloaded file"
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
    """Attempt to open a file in Imaris using FileOpen.

    Inputs: `file_path` file path, `imaris_app`, `require_ims`. Output:
    `_open_file_in_imaris_with_mode` result.
    """
    verification_mode = "current_file" if require_ims else "submission_only"
    return _open_file_in_imaris_with_mode(file_path, imaris_app, verification_mode)


def open_files_in_imaris(file_paths, imaris_app, require_ims=True):
    """Open local IMS files in an existing Imaris application.

    Inputs: `file_paths`, `imaris_app`, `require_ims`. Output:
    `open_files_as_imaris_image_slots` result.
    """
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
        if require_ims and not is_ims_file(candidate):
            _xt_debug(
                "Direct Imaris multi-open skipped: one file is not a valid IMS file"
            )
            return False
        validated_paths.append(str(candidate))

    if len(validated_paths) == 1:
        return open_file_in_imaris(
            validated_paths[0],
            imaris_app,
            require_ims=require_ims,
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
    return callable(getattr(candidate, "FileOpen", None))


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
    ):
        """Create `_RoundedButton` with `master`, `text`, `command`, `bg`, `fg`,
        `activebackground`, `activeforeground`, `font`, `width`, `height`, and `state`.

        Inputs: `master`, `text`, `command`, `bg`, `fg`, `activebackground`,
        `activeforeground`, `font`, `width`, `height`, `state`. Output: None.
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
        self._canvas = tk.Canvas(
            master,
            width=width,
            height=height,
            bd=0,
            highlightthickness=0,
            relief=_tk_constant("FLAT", "flat"),
            bg=_widget_background(master),
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
        self._canvas.create_line(
            left + radius,
            top + 2,
            right - radius,
            top + 2,
            fill=_shade_color(fill, 0.28),
            width=1,
        )
        self._canvas.create_line(
            left + radius,
            bottom - 2,
            right - radius,
            bottom - 2,
            fill=_shade_color(fill, -0.18),
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
            text_fill = _blend_colors(self._fg, "#6f7b84", 0.62)
            shadow = _blend_colors(self._bg, "#d7dde2", 0.82)
        elif pressed:
            fill = self._active_bg
            text_fill = self._active_fg
            shadow = _shade_color(self._bg, -0.45)
        elif self._hover:
            fill = _shade_color(self._bg, 0.1)
            text_fill = self._fg
            shadow = _shade_color(self._bg, -0.38)
        else:
            fill = self._bg
            text_fill = self._fg
            shadow = _shade_color(self._bg, -0.35)

        surface_offset = 1 if pressed else 0
        shadow_shift = 1 if pressed else 2
        diameter = max(12, min(width, height) - 8)
        left = (width - diameter) / 2
        top = (height - diameter - shadow_shift) / 2 + surface_offset
        right = left + diameter
        bottom = top + diameter
        self._canvas.create_oval(
            left + 1,
            top + shadow_shift,
            right + 1,
            bottom + shadow_shift,
            fill=shadow,
            outline="",
        )
        self._canvas.create_oval(
            left,
            top,
            right,
            bottom,
            fill=fill,
            outline="",
        )
        self._canvas.create_text(
            width / 2 + surface_offset / 2,
            height / 2 + surface_offset / 2 - 1,
            text=self._text,
            fill=text_fill,
            font=self._font,
        )


class _PasswordRevealButton(_RoundedButton):
    """Canvas-backed password visibility button with a timed reveal state."""

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
        """Redraw the password reveal button.

        Inputs: no caller arguments. Output: None.
        """
        width = max(int(self._canvas.winfo_width() or self._width), self._width)
        height = max(int(self._canvas.winfo_height() or self._height), self._height)
        self._canvas.delete("all")

        enabled = self._is_enabled()
        pressed = enabled and self._pressed
        visible = self._visible
        if not enabled:
            fill = "#f1f5f9"
            outline = "#cfd7df"
            icon = "#94a3b8"
        elif pressed:
            fill = self._active_bg
            outline = "#9eb7d0"
            icon = self._fg
        elif self._hover:
            fill = _shade_color(self._bg, 0.04)
            outline = "#adc1d5"
            icon = self._fg
        else:
            fill = self._bg
            outline = "#c7d2de"
            icon = self._fg

        pad = 2
        radius = 6
        self._draw_round_rect(
            pad,
            pad,
            width - pad,
            height - pad,
            radius,
            fill=fill,
            outline=outline,
            width=1,
        )

        center_x = width / 2
        center_y = height / 2
        eye_w = max(12, width - 10)
        eye_h = max(7, height - 14)
        left = center_x - eye_w / 2
        top = center_y - eye_h / 2
        right = center_x + eye_w / 2
        bottom = center_y + eye_h / 2
        self._canvas.create_arc(
            left,
            top,
            right,
            bottom,
            start=0,
            extent=180,
            style=_tk_constant("ARC", "arc"),
            outline=icon,
            width=1,
        )
        self._canvas.create_arc(
            left,
            top,
            right,
            bottom,
            start=180,
            extent=180,
            style=_tk_constant("ARC", "arc"),
            outline=icon,
            width=1,
        )
        self._canvas.create_oval(
            center_x - 2,
            center_y - 2,
            center_x + 2,
            center_y + 2,
            fill=icon if visible else "",
            outline=icon,
            width=1,
        )
        if not visible:
            self._canvas.create_line(
                left + 1,
                bottom + 1,
                right - 1,
                top - 1,
                fill=icon,
                width=1,
            )


def _iter_imaris_executable_candidates():
    """Yield plausible Imaris executable paths without requiring admin access.

    Inputs: none. Output: yielded values.
    """
    seen = set()

    def _yield_candidate(path):
        """Yield the candidate.

        Inputs: `path` path. Output: iterator of yielded items.
        """
        normalized = os.path.normpath(path)
        if normalized in seen:
            return
        seen.add(normalized)
        yield normalized

    env_candidate = os.environ.get("IMARIS_EXE", "").strip()
    if env_candidate:
        yield from _yield_candidate(env_candidate)

    winreg_module: Any = None
    try:
        winreg_module = importlib.import_module("winreg")
    except ImportError:
        winreg_module = None

    if winreg_module is not None:
        reg_locations = [
            (
                winreg_module.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Imaris.exe",
            ),
            (
                winreg_module.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Imaris.exe",
            ),
        ]
        for hive, subkey in reg_locations:
            try:
                with winreg_module.OpenKey(hive, subkey) as key:
                    value, _ = winreg_module.QueryValueEx(key, None)
                if value:
                    yield from _yield_candidate(value)
            except (OSError, ValueError):
                continue

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
            if not os.path.isdir(vendor_root):
                continue
            try:
                entries = sorted(os.listdir(vendor_root), reverse=True)
            except Exception:
                entries = []
            for entry in entries:
                if not entry.lower().startswith("imaris"):
                    continue
                candidate = os.path.join(vendor_root, entry, "Imaris.exe")
                if not _is_supported_imaris_install_path(candidate):
                    continue
                yield from _yield_candidate(candidate)


def _find_imaris_executable():
    """Return a launchable Imaris.exe path if present.

    Inputs: none. Output: `candidate` or None.
    """
    if os.name != "nt":
        return None
    for candidate in _iter_imaris_executable_candidates():
        if os.path.isfile(candidate) and _is_supported_imaris_install_path(candidate):
            return candidate
    return None


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
    imaris_id, mode, file_path=None, file_paths=None, require_ims=True
):
    """Return the native bridge payload.

    Inputs: `imaris_id`, `mode`, `file_path` file path, `file_paths`, `require_ims`.
    Output: ID value.
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
    if payload.get("require_ims") is not False:
        return "completed open request in the current Imaris session"
    if stdout == "BRIDGE_RUNNER_OPENED_MANY":
        return (
            "submitted the selected original-file open requests in the current "
            "Imaris session"
        )
    return "submitted the original-file open request in the current Imaris session"


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
            f"Native bridge runner ({context}) resolved Imaris but FileOpen is unavailable"
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
    python_executable, file_path, imaris_id, require_ims=True
):
    """Run the native bridge open helper.

    Inputs: `python_executable`, `file_path` file path, `imaris_id`, `require_ims`.
    Output: `_run_native_bridge_helper` result.
    """
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        return False
    if require_ims and not is_ims_file(candidate):
        return False
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(
            imaris_id,
            "open",
            file_path=candidate,
            require_ims=require_ims,
        ),
        "open",
        NATIVE_BRIDGE_RUNNER_TIMEOUT,
    )


def _run_native_bridge_open_many_helper(
    python_executable, file_paths, imaris_id, require_ims=True
):
    """Run the native bridge open many helper.

    Inputs: `python_executable`, `file_paths`, `imaris_id`, `require_ims`. Output:
    `_run_native_bridge_helper` result.
    """
    candidates = _existing_regular_file_path_list(file_paths)
    if candidates is None:
        return False
    if require_ims and any(not is_ims_file(candidate) for candidate in candidates):
        return False
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(
            imaris_id,
            "open",
            file_paths=candidates,
            require_ims=require_ims,
        ),
        "open_many",
        NATIVE_BRIDGE_RUNNER_TIMEOUT,
    )


def _find_compatible_native_bridge_python(imaris_id):
    """Return an installed Python executable that can use Imaris' native bridge.

    Inputs: `imaris_id`. Output: `python_executable` or None.
    """
    if _coerce_imaris_id(imaris_id) is None:
        return None
    for python_executable in _iter_native_bridge_python_executables():
        if _run_native_bridge_probe_helper(python_executable, imaris_id):
            return python_executable
    return None


def _imaris_server_executable_for_imaris(imaris_executable):
    """Return the adjacent ImarisServerIce executable when present.

    Inputs: `imaris_executable`. Output: `str` result or None.
    """
    candidate = _coerce_path(imaris_executable)
    if candidate is None:
        return None
    server_name = "ImarisServerIce.exe" if os.name == "nt" else "ImarisServerIce"
    server_path = candidate.with_name(server_name)
    if server_path.is_file():
        return str(server_path)
    return None


def _start_imaris_server_ice_if_available(imaris_executable):
    """Best-effort start for ImarisServerIce before launching a fresh Imaris.

    Inputs: `imaris_executable`. Output: bool.
    """
    server_executable = _imaris_server_executable_for_imaris(imaris_executable)
    if not server_executable:
        return False

    import subprocess

    try:
        subprocess.Popen(
            [server_executable],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _xt_debug("Started ImarisServerIce for fresh Imaris launch")
        return True
    except Exception as exc:
        _xt_debug(f"Unable to start ImarisServerIce: {type(exc).__name__}: {exc}")
        return False


def _generate_imaris_application_id():
    """Generate a non-reserved Imaris application id for a launched instance.

    Inputs: none. Output: ID value.
    """
    return 1000 + random.randint(0, 100000)


def _launch_imaris_process(imaris_executable, app_id):
    """Launch Imaris with the requested XT application id.

    Inputs: `imaris_executable`, `app_id`. Output: bool.
    """
    exe_path = _existing_regular_file_path(imaris_executable)
    if exe_path is None:
        return False

    import subprocess

    try:
        subprocess.Popen(
            [str(exe_path), f"id{int(app_id)}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _xt_debug(f"Launched a fresh Imaris session with application id {int(app_id)}")
        return True
    except Exception as exc:
        _xt_debug(f"Unable to launch Imaris: {type(exc).__name__}: {exc}")
        return False


def _launch_imaris_and_find_bridge_python():
    """Launch a fresh Imaris session and return its id plus bridge Python.

    Inputs: none. Output: tuple.
    """
    if os.name != "nt":
        return None, None
    imaris_executable = _find_imaris_executable()
    if not imaris_executable:
        _xt_debug("Fresh Imaris launch unavailable: Imaris.exe was not found")
        return None, None

    _start_imaris_server_ice_if_available(imaris_executable)
    app_id = _generate_imaris_application_id()
    if not _launch_imaris_process(imaris_executable, app_id):
        return None, None

    deadline = time.time() + NATIVE_BRIDGE_LAUNCH_TIMEOUT
    while time.time() < deadline:
        bridge_python = _find_compatible_native_bridge_python(app_id)
        if bridge_python:
            return app_id, bridge_python
        time.sleep(NATIVE_BRIDGE_LAUNCH_POLL_INTERVAL)

    _xt_debug("Fresh Imaris launch did not expose a compatible bridge before timeout")
    return None, None


def _open_file_in_imaris_with_native_bridge_runner(
    file_path, imaris_id, preferred_python_executable=None, require_ims=True
):
    """Try compatible installed Python runtimes while staying on ImarisLib/FileOpen.

    Inputs: `file_path`, `imaris_id`, `preferred_python_executable`, `require_ims`.
    Output: bool.
    """
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
    file_paths, imaris_id, preferred_python_executable=None, require_ims=True
):
    """Try compatible installed Python runtimes while staying on ImarisLib/FileOpen.

    Inputs: `file_paths`, `imaris_id`, `preferred_python_executable`, `require_ims`.
    Output: `bool`.
    """
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


def _collect_imaris_xt_diagnostics():
    """Collect imaris XT diagnostics.

    Inputs: none. Output: dict.
    """
    exe_path = _find_imaris_executable()
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
        "imaris_home_env": os.environ.get("IMARIS_HOME", ""),
        "imaris_executable": exe_path or "",
        "imaris_executable_exists": _safe_path_exists(exe_path),
        "install_roots": install_roots,
        "xt_candidate_paths": [
            {"path": candidate, "exists": _safe_path_exists(candidate)}
            for candidate in deduped_xt_paths
        ],
        "has_add_dll_directory": callable(getattr(os, "add_dll_directory", None)),
        "imarislib_import": _probe_module_import("ImarisLib"),
        "icepy_import": _probe_module_import("IcePy"),
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
        f"imaris_exe_exists={diagnostics['imaris_executable_exists']}"
    )
    _xt_debug(
        "XT diagnostics env: "
        f"IMARIS_HOME={diagnostics['imaris_home_env'] or '<unset>'} "
        f"IMARIS_EXE={diagnostics['imaris_exe_env'] or '<unset>'}"
    )
    for install_root in diagnostics["install_roots"]:
        _xt_debug(f"XT diagnostics install_root={install_root}")
    for entry in diagnostics["xt_candidate_paths"]:
        _xt_debug(f"XT diagnostics path={entry['path']} exists={entry['exists']}")
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
            prepared = _prepare_imaris_xt_environment()
            added_paths = prepared.get("paths", [])
            added_dll_dirs = prepared.get("dll_dirs", [])
            if added_paths:
                _xt_debug(
                    "Prepared Imaris XT environment paths: " + "; ".join(added_paths)
                )
            if added_dll_dirs:
                _xt_debug(
                    "Prepared Imaris XT DLL directories: " + "; ".join(added_dll_dirs)
                )
            import ImarisLib

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
            version_info = ".".join(str(part) for part in sys.version_info[:3])
            _xt_debug(
                "Direct Imaris XT bridge is unavailable in this Python: "
                f"{exc}. Current Python={version_info}. "
                "The connector will use the compatible native bridge runner if available."
            )
            break

        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(retry_interval)))

    return None


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

    @staticmethod
    def _build_base_url(host, port, scheme):
        """Build the base URL for `OMEROWebClient`.

        Inputs: `host`, `port`, `scheme`. Output: URL string.
        """
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"{scheme}://{host}:{port}"

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
        if "/webclient/login/" in str(final_url):
            _xt_debug(
                "Authentication failed during "
                f"{context}: redirected to {_safe_url_for_log(final_url)}"
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
    def _with_all_groups(endpoint):
        """API endpoints query all groups accessible to the user.

        Inputs: `endpoint`. Output: with all groups result.
        """
        if "group=" in endpoint:
            return endpoint
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}group=-1"

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
            self.opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self.cookie_jar)
            )
            # Set default timeout
            urllib.request.install_opener(self.opener)

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
            self.password = ""

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
            "original_file": None,
        }

        fileset = data.get("Fileset") or data.get("fileset") or {}
        files = fileset.get("Files") or fileset.get("files") or []
        if files:
            result["original_file"] = files[0].get("Name") or files[0].get("name")

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

    def has_omero_ims_export_capability(self):
        """Return True when this OMERO.web instance exposes server-side IMS export.

        Inputs: none. Output: `available`.
        """
        if not self.session_id:
            return False
        base = self.base_url.rstrip("/")
        capability_url = (
            f"{base}/omeroweb_imaris_connector/imaris-export/?capabilities=1"
        )
        _xt_debug(
            "Checking OMERO IMS export capability endpoint="
            f"{_safe_url_for_log(capability_url)}"
        )
        req = self._create_request_with_cookies(capability_url)
        try:
            with self.opener.open(req, timeout=30) as response:
                if self._check_login_redirect(response, "IMS export capability check"):
                    return False
                raw_body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw_body)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if exc.code == 400 and "missing image id" in body.lower():
                _xt_debug(
                    "Legacy IMS export endpoint detected; enabling OMERO converter"
                )
                return True
            _xt_debug(f"OMERO IMS export capability unavailable: HTTP {exc.code}")
            return False
        except Exception as exc:
            _xt_debug(f"OMERO IMS export capability unavailable: {exc}")
            return False
        if not isinstance(payload, dict):
            _xt_debug("OMERO IMS export capability returned non-object JSON")
            return False
        converters = payload.get("converters")
        converter_available = (
            isinstance(converters, dict) and converters.get("OMERO") is True
        )
        available = bool(payload.get("omero_ims_export") or converter_available)
        _xt_debug(f"OMERO IMS export capability available={available}")
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

        for key in ("upload_url", "import_step_url", "status_url", "confirm_url"):
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

    def list_projects(self, *, timeout=30, raise_on_error=False, retry_transient=False):
        """Return the projects for `OMEROWebClient`.

        Inputs: `timeout` timeout seconds, `raise_on_error`, `retry_transient`. Output:
        `_build_named_entities` result.
        """
        data = self._api_request(
            self._with_all_groups("m/projects/"),
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
            out.append(
                {
                    "id": image_id,
                    "name": img.get("Name") or img.get("name") or f"Image {image_id}",
                    "sizeX": pixels.get("SizeX", pixels.get("sizeX", 0)),
                    "sizeY": pixels.get("SizeY", pixels.get("sizeY", 0)),
                    "sizeZ": pixels.get("SizeZ", pixels.get("sizeZ", 1)),
                    "sizeC": pixels.get("SizeC", pixels.get("sizeC", 1)),
                    "sizeT": pixels.get("SizeT", pixels.get("sizeT", 1)),
                }
            )
        return out

    def download_ims_export(
        self,
        image_id,
        download_dir,
        fallback_name="export.ims",
    ):
        """Download an Imaris .ims export for a given image_id.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`. Output:
        `local_path`. Raises: RuntimeError when validation or the called operation fails.
        """
        if download_dir is None:
            download_dir = os.path.join(tempfile.gettempdir(), "ImarisOMEROExports")

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
        export_url = f"{base}/omeroweb_imaris_connector/imaris-export/?{encoded_query}"
        _xt_debug(f"Requesting IMS export endpoint={_safe_url_for_log(export_url)}")

        os.makedirs(download_dir, exist_ok=True)

        # Create request with explicit cookies
        req = self._create_request_with_cookies(export_url)

        try:
            with self.opener.open(req, timeout=30) as response:
                if self._check_login_redirect(response, "IMS export request"):
                    if not self._attempt_reauth("IMS export request"):
                        raise RuntimeError(
                            "Not authenticated to OMERO.web (redirected to login). "
                            "Please login again."
                        )
                    return self.download_ims_export(
                        image_id,
                        download_dir,
                        fallback_name=fallback_name,
                    )

                raw_body = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "IMS export failed: server returned a non-JSON response. "
                        "Please verify the OMERO.web Imaris connector is healthy."
                    ) from exc

                job_id = payload.get("job_id")
                status_url = payload.get("status_url")
                if not job_id or not status_url:
                    raise RuntimeError(f"Unexpected response from server: {payload}")

                status_url = self._normalize_url(status_url, base)
                _xt_debug(
                    "IMS export started; polling endpoint="
                    f"{_safe_url_for_log(status_url)}"
                )

            # Poll for completion
            deadline = time.time() + EXPORT_TIMEOUT
            download_url = None
            last_state = None
            poll_count = 0
            reauth_attempted = False

            while time.time() < deadline:
                poll_count += 1
                _xt_debug(
                    f"IMS export poll #{poll_count} endpoint="
                    f"{_safe_url_for_log(status_url)}"
                )

                # Create poll request with explicit cookies
                poll_req = self._create_request_with_cookies(status_url)

                try:
                    with self.opener.open(poll_req, timeout=30) as poll_response:
                        if self._check_login_redirect(poll_response, "IMS export poll"):
                            # Try to re-extract cookies in case they were updated
                            self._extract_cookies_from_jar()
                            _xt_debug(
                                "Session state after redirect: "
                                f"sessionid_present={bool(self.session_id)}"
                            )
                            if not reauth_attempted:
                                reauth_attempted = True
                                if self._attempt_reauth("IMS export poll"):
                                    continue
                            raise RuntimeError(
                                "Not authenticated to OMERO.web (redirected to login) "
                                "while polling IMS export. "
                                "Session may have expired. Please try again."
                            )

                        poll_body = poll_response.read().decode(
                            "utf-8", errors="replace"
                        )
                        try:
                            poll_payload = json.loads(poll_body)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                "IMS export poll failed: server returned a non-JSON response. "
                                "Please verify the OMERO.web Imaris connector is healthy."
                            ) from exc

                except urllib.error.HTTPError as e:
                    if e.code in (401, 403):
                        if not reauth_attempted:
                            reauth_attempted = True
                            if self._attempt_reauth("IMS export poll HTTP error"):
                                continue
                        raise RuntimeError(
                            f"Authentication error ({e.code}) while polling IMS export. "
                            "Session may have expired. Please try again."
                        )
                    raise

                last_state = poll_payload.get("state")
                _xt_debug(
                    "IMS export poll state="
                    f"{last_state} finished={bool(poll_payload.get('finished'))} "
                    f"failed={bool(poll_payload.get('failed'))} "
                    f"status={poll_payload.get('status') or '<unset>'}"
                )

                if poll_payload.get("failed"):
                    error_msg = poll_payload.get("error", "unknown error")
                    raise RuntimeError(f"IMS export failed: {error_msg}")

                if poll_payload.get("finished"):
                    download_url = poll_payload.get("download_url")
                    if download_url:
                        download_url = self._normalize_url(download_url, base)
                    break

                time.sleep(EXPORT_POLL_INTERVAL)

            if not download_url:
                raise RuntimeError(f"IMS export timed out (last state: {last_state})")

            # Download the file
            _xt_debug(f"Downloading IMS endpoint={_safe_url_for_log(download_url)}")
            download_req = self._create_request_with_cookies(download_url)

            with self.opener.open(
                download_req, timeout=EXPORT_TIMEOUT + 60
            ) as response:
                if self._check_login_redirect(response, "IMS export download"):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web (redirected to login) "
                        "while downloading IMS export."
                    )

                cd = response.headers.get("Content-Disposition", "")
                filename = _extract_content_disposition_filename(cd)
                safe_filename = _safe_download_filename(
                    filename,
                    fallback_name,
                    default_extension=".ims",
                )
                local_path = _unique_download_path(download_dir, safe_filename)

                total_size = int(response.headers.get("content-length", 0) or 0)
                downloaded = 0
                chunk_size = _download_chunk_size_bytes()

                _xt_debug("Downloading IMS to connector export cache")
                with open(local_path, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            progress_mb = downloaded / DOWNLOAD_PROGRESS_UNIT_BYTES
                            print(
                                f"  Progress: {percent:.1f}% ({progress_mb:.1f} MB)",
                                end="\r",
                            )

                if total_size:
                    print()

            if not os.path.exists(local_path):
                raise RuntimeError(
                    f"Download completed but file not found at {local_path}"
                )
            if os.path.getsize(local_path) <= 0:
                raise RuntimeError("Downloaded IMS file is empty")

            _xt_debug("IMS export downloaded OK")
            return local_path

        except urllib.error.HTTPError as e:
            try:
                body_length = len(e.read())
            except Exception as exc:
                body_length = 0
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            _xt_debug(f"IMS export HTTP error body omitted length={body_length}")
            raise RuntimeError(f"IMS export HTTPError {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"IMS export failed (URLError): {e}") from e

    def download_original_file(
        self,
        image_id,
        download_dir,
        fallback_name="original",
    ):
        """Download the archived original file for local Imaris opening.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`. Output:
        `local_path`. Raises: RuntimeError when validation or the called operation fails.
        """
        if download_dir is None:
            download_dir = os.path.join(tempfile.gettempdir(), "ImarisOMEROExports")
        if not self.session_id:
            raise RuntimeError("Not logged in to OMERO.web (missing session key).")

        base = self.base_url.rstrip("/")
        download_url = f"{base}/webgateway/archived_files/download/{int(image_id)}/"
        _xt_debug(
            "Requesting original file download endpoint="
            f"{_safe_url_for_log(download_url)}"
        )
        os.makedirs(download_dir, exist_ok=True)
        req = self._create_request_with_cookies(download_url)

        try:
            with self.opener.open(req, timeout=EXPORT_TIMEOUT + 60) as response:
                if self._check_login_redirect(response, "original file download"):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web while downloading original file."
                    )

                cd = response.headers.get("Content-Disposition", "")
                filename = _extract_content_disposition_filename(cd)
                safe_filename = _safe_download_filename(filename, fallback_name)
                local_path = _unique_download_path(download_dir, safe_filename)
                total_size = int(response.headers.get("content-length", 0) or 0)
                downloaded = 0
                chunk_size = _download_chunk_size_bytes()

                _xt_debug("Downloading original file to connector export cache")
                with open(local_path, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            progress_mb = downloaded / DOWNLOAD_PROGRESS_UNIT_BYTES
                            print(
                                f"  Progress: {percent:.1f}% ({progress_mb:.1f} MB)",
                                end="\r",
                            )

                if total_size:
                    print()

            if not os.path.exists(local_path):
                raise RuntimeError(
                    f"Download completed but file not found at {local_path}"
                )
            if os.path.getsize(local_path) <= 0:
                raise RuntimeError("Downloaded original file is empty")

            _xt_debug("Original file downloaded OK")
            return local_path
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
                f"Original file download HTTP error body omitted length={body_length}"
            )
            raise RuntimeError(
                f"Original file download HTTPError {e.code}: {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Original file download failed (URLError): {e}") from e

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
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
        self.temp_files = []
        self._pid = None
        self._did = None
        self._refresh_generation = 0
        self._refresh_in_progress = False
        self._native_bridge_probe_lock = threading.Lock()
        self._native_bridge_probe_done = threading.Event()
        self._native_bridge_probe_started = False
        self._native_bridge_probe_in_progress = False
        self._native_bridge_available = _looks_like_imaris_application(self.imaris)
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
        self._folder_export_initial_path_hint_consumed = False
        self._last_folder_export_selection = ""
        self._load_in_progress = False
        self._image_selection_anchor = None
        self._health_ping_generation = 0
        self._health_ping_in_progress = False
        self._health_ping_after_id: Optional[str] = None
        self._browser_panel_fractions = tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)
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
        try:
            self._settings_file_path = _connector_settings_env_path()
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
        default_folder_path = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_PATH_KEY
        )
        default_converter = _filled_connector_setting(
            saved_settings, CONNECTOR_SETTINGS_CONVERTER_KEY
        )
        default_autosave_settings = _connector_settings_bool(
            saved_settings.get(CONNECTOR_SETTINGS_AUTOSAVE_KEY), True
        )

        self._connection_label(conn_frame, "Host:").grid(
            row=0, column=0, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.host_entry = tk.Entry(conn_frame, width=25)
        self.host_entry.insert(0, default_host)
        self.host_entry.grid(row=0, column=1, pady=5, padx=5)

        self._connection_label(conn_frame, "Port:").grid(
            row=0, column=2, sticky=_tk_constant("NSEW", "nsew"), pady=5
        )
        self.port_entry = tk.Entry(conn_frame, width=8)
        self.port_entry.insert(0, default_port)
        self.port_entry.grid(row=0, column=3, pady=5, padx=5)

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
            ipady=5,
        )
        self.password_reveal_btn = _PasswordRevealButton(
            self.password_frame,
            command=self._toggle_password_reveal,
            bg=PASSWORD_REVEAL_ICON_BG,
            fg=PASSWORD_REVEAL_ICON_FG,
            activebackground=PASSWORD_REVEAL_ICON_ACTIVE_BG,
            activeforeground=PASSWORD_REVEAL_ICON_FG,
            width=PASSWORD_REVEAL_BUTTON_SIZE,
            height=PASSWORD_REVEAL_BUTTON_SIZE,
        )
        self.password_reveal_btn.grid(row=0, column=1, padx=(2, 3), pady=2)

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

        self._preferred_converter_setting = default_converter
        self.converter_var = tk.StringVar(value="")
        self.converter_frame = tk.Frame(conn_frame)
        tk.Label(self.converter_frame, text="Converter:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.converter_menu = tk.Menubutton(
            self.converter_frame,
            textvariable=self.converter_var,
            relief=_tk_constant("RAISED", "raised"),
            bd=1,
            bg="#f8f9fa",
            fg="#2c3e50",
            activebackground="#e9eef3",
            activeforeground="#2c3e50",
            font=CONVERTER_MENU_FONT,
            width=CONVERTER_MENU_WIDTH,
            padx=10,
            pady=4,
            anchor=tk.W,
            justify=tk.LEFT,
            indicatoron=True,
        )
        self.converter_menu_menu = tk.Menu(
            self.converter_menu,
            tearoff=0,
            font=CONVERTER_MENU_FONT,
            bg="#f8f9fa",
            fg="#2c3e50",
            activebackground="#e9eef3",
            activeforeground="#2c3e50",
            activeborderwidth=0,
        )
        self.converter_menu.config(menu=self.converter_menu_menu)
        self.converter_menu.pack(side=tk.LEFT)
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
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(16, 0))
        self.converter_frame.grid(
            row=2,
            column=8,
            sticky=tk.E,
            padx=(12, 12),
            pady=5,
        )
        self.converter_frame.grid_remove()
        conn_frame.grid_columnconfigure(8, weight=1)

        self.folder_path_var = tk.StringVar(value=default_folder_path)
        self._folder_path_placeholder_visible = False
        self._folder_path_trace_suppressed = False
        self._folder_path_write_state = "empty"
        self._connection_label(conn_frame, "Path:").grid(
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
        )
        self.select_folder_btn.grid(row=2, column=5, padx=(10, 12), pady=5, sticky=tk.W)
        self.autosave_settings_var = tk.BooleanVar(value=default_autosave_settings)
        self.autosave_settings_frame = tk.Frame(
            conn_frame,
            width=AUTOSAVE_SETTINGS_FRAME_WIDTH,
            height=38,
        )
        self.autosave_settings_frame.grid(
            row=2,
            column=7,
            sticky=tk.W,
            padx=(14, 0),
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
        self.autosave_settings_check.pack(side=tk.RIGHT)
        panel_icon_frame = tk.Frame(conn_frame)
        panel_icon_frame.grid(
            row=0,
            column=8,
            rowspan=2,
            sticky=tk.NE,
            padx=(12, 12),
            pady=(0, 2),
        )
        self.help_btn = _CircularIconButton(
            panel_icon_frame,
            text="?",
            bg=CONNECTOR_HELP_ICON_BG,
            fg=CONNECTOR_HELP_ICON_FG,
            activebackground=CONNECTOR_HELP_ICON_ACTIVE_BG,
            activeforeground=CONNECTOR_HELP_ICON_FG,
            font=CONNECTOR_PANEL_ICON_FONT,
            width=CONNECTOR_PANEL_ICON_SIZE,
            height=CONNECTOR_PANEL_ICON_SIZE,
        )
        self.info_btn = _CircularIconButton(
            panel_icon_frame,
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
        self._show_folder_path_placeholder()

        # Browser
        browser = tk.Frame(self.root)
        browser.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.browser_frame = browser
        browser.grid_rowconfigure(0, weight=1)

        # Projects
        p_frame = tk.LabelFrame(browser, text="Projects")
        p_frame.grid(row=0, column=0, sticky=tk.NSEW)
        self.plist = self._build_scrolled_listbox(p_frame)
        self.plist.bind("<<ListboxSelect>>", lambda e: self._sel_proj())

        self.browser_sash_1 = self._build_browser_sash(browser, 0)
        self.browser_sash_1.grid(row=0, column=1, sticky=tk.NS)

        # Datasets
        d_frame = tk.LabelFrame(browser, text="Datasets")
        d_frame.grid(row=0, column=2, sticky=tk.NSEW)
        self.dlist = self._build_scrolled_listbox(d_frame)
        self.dlist.bind("<<ListboxSelect>>", lambda e: self._sel_ds())

        self.browser_sash_2 = self._build_browser_sash(browser, 1)
        self.browser_sash_2.grid(row=0, column=3, sticky=tk.NS)

        # Images
        i_frame = tk.LabelFrame(browser, text="Images")
        i_frame.grid(row=0, column=4, sticky=tk.NSEW)
        self.ilist = self._build_scrolled_listbox(
            i_frame,
            selectmode=_tk_constant("EXTENDED", "extended"),
        )
        self._configure_image_selection_bindings()
        self._apply_browser_panel_layout()
        browser.bind("<Configure>", lambda _event: self._apply_browser_panel_layout())

        # Actions
        actions = tk.Frame(self.root)
        actions.pack(fill=tk.X, padx=ACTION_ROW_HORIZONTAL_PAD, pady=10)
        actions.grid_columnconfigure(2, weight=1)

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
        self.export_btn.grid(row=0, column=1, sticky=tk.W, padx=ACTION_BUTTON_PAD)

        close_btn = _RoundedButton(
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
        close_btn.grid(row=0, column=3, sticky=tk.E, padx=ACTION_BUTTON_PAD)

        # Reserved for a later progress bar.
        bottom_progress_margin = tk.Frame(
            self.root,
            height=BOTTOM_PROGRESS_RESERVED_HEIGHT,
            bg=STATUS_NEUTRAL_BG,
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
        self.connection_indicator.pack(side=tk.RIGHT, padx=(4, 10), pady=2)
        self._draw_connection_indicator("disconnected")

    @staticmethod
    def _build_scrolled_listbox(parent, selectmode=None):
        """Build the scrolled listbox for `OMEROBrowserDialog`.

        Inputs: `parent`, `selectmode`. Output: `listbox`.
        """
        y_scroll = tk.Scrollbar(parent, orient=_tk_constant("VERTICAL", "vertical"))
        x_scroll = tk.Scrollbar(parent, orient=_tk_constant("HORIZONTAL", "horizontal"))
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        listbox = tk.Listbox(
            parent,
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
            exportselection=False,
            activestyle=_tk_constant("NONE", "none"),
        )
        if selectmode is not None:
            listbox.config(selectmode=selectmode)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
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

    def _current_window_minimum_size(self, root):
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

    def _get_converter_menu(self):
        """Return converter menu.

        Inputs: none. Output: get converter menu result.
        """
        dialog_menu = getattr(self, "converter_menu_menu", None)
        if dialog_menu is not None:
            return dialog_menu
        menu = getattr(self.converter_menu, "menu", None)
        if menu is not None:
            return menu
        return self.converter_menu["menu"]

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
        menu = self._get_converter_menu()
        menu.delete(0, _tk_constant("END", "end"))
        if not options:
            self.converter_var.set("")
            self._hide_converter_frame()
            self._set_load_button_for_converter()
            self._set_refresh_button_state(_tk_constant("DISABLED", "disabled"))
            return

        for option in options:
            menu.add_command(
                label=option,
                font=CONVERTER_MENU_FONT,
                hidemargin=True,
                command=partial(self._select_converter, option),
            )
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
        value = str(folder_path or "")
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

    def _connector_settings_snapshot(self):
        """Return the connector settings that may be persisted.

        Inputs: none. Output: dict. Passwords are intentionally excluded.
        """
        https_variable = getattr(self, "https_var", None)
        https_getter: Any = getattr(https_variable, "get", None)
        https_value = https_getter() if callable(https_getter) else False
        return {
            CONNECTOR_SETTINGS_HOST_KEY: self._entry_text("host_entry").strip(),
            CONNECTOR_SETTINGS_PORT_KEY: self._entry_text("port_entry").strip(),
            CONNECTOR_SETTINGS_USERNAME_KEY: self._entry_text("user_entry").strip(),
            CONNECTOR_SETTINGS_HTTPS_KEY: _connector_settings_bool_text(https_value),
            CONNECTOR_SETTINGS_PATH_KEY: self._current_local_folder_path(),
            CONNECTOR_SETTINGS_CONVERTER_KEY: _stringvar_value(
                getattr(self, "converter_var", None)
            ),
            CONNECTOR_SETTINGS_AUTOSAVE_KEY: _connector_settings_bool_text(
                self._autosave_settings_enabled()
            ),
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

    @staticmethod
    def _show_autosave_settings_error():
        """Show the generic autosave-settings write error.

        Inputs: none. Output: None.
        """
        messagebox.showwarning(
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

    def _on_autosave_settings_changed(self):
        """Persist the autosave status immediately after a user toggle.

        Inputs: none. Output: None.
        """
        if not getattr(self, "_connected", False):
            self._set_autosave_settings_control_state(False)
            return
        if not self._write_autosave_settings():
            self._show_autosave_settings_error()

    def _enable_autosave_after_verified_connection(self):
        """Enable autosave controls and persist verified connection settings.

        Inputs: none. Output: None.
        """
        self._set_autosave_settings_control_state(True)
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

    @staticmethod
    def _show_folder_path_write_error():
        """Show the common local-folder write error.

        Inputs: no caller arguments. Output: None.
        """
        messagebox.showerror(
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
            elif (
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
            messagebox.showwarning(
                "Refresh In Progress",
                "Please wait for the OMERO browser refresh to finish.",
            )
            return
        if not self._connected or self.client is None:
            messagebox.showwarning("Not Connected", "Please connect to OMERO first.")
            return
        if not self._folder_export_available:
            messagebox.showwarning(
                "Export Unavailable",
                self._folder_export_reason
                or "Folder export is not available on this OMERO.web instance.",
            )
            return

        selected_folder = self._select_folder_for_omero_export()
        if not selected_folder:
            return

        if _coerce_path(selected_folder) is None:
            messagebox.showerror(
                "Invalid Folder",
                "Please select or enter an existing folder.",
            )
            return

        folder_name = _folder_display_name(selected_folder)
        if _is_filesystem_root(selected_folder) or not folder_name:
            messagebox.showerror(
                "Invalid Folder",
                "Please select a regular folder, not a filesystem root.",
            )
            return

        if not _safe_is_directory(selected_folder):
            messagebox.showerror(
                "Invalid Folder",
                "Please select or enter an existing folder.",
            )
            return

        confirmation = (
            "Export the selected folder to OMERO root path as a dataset?\n\n"
            f"Dataset name: {folder_name}\n"
            "\n"
            "This uploads every file inside the selected folder."
        )
        if not messagebox.askyesno("Confirm folder export", confirmation):
            return

        self._set_actions_busy_for_export(True)
        self._set_status("Preparing folder export to OMERO...", "#fff3cd")
        threading.Thread(
            target=self._export_folder_worker,
            args=(selected_folder, folder_name),
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
                lambda: messagebox.askyesno(
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
    ):
        """Wait for folder export completion for `OMEROBrowserDialog`.

        Inputs: `folder_name`, `status_url`, `confirm_url`. Output: `status_payload`.
        Raises: RuntimeError when validation or the called operation fails.
        """
        deadline = time.time() + FOLDER_EXPORT_TIMEOUT
        while time.time() < deadline:
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
                self._set_status("Confirming compatible OMERO export...", "#fff3cd")
                self.client.confirm_folder_export(confirm_url)
            time.sleep(FOLDER_EXPORT_POLL_INTERVAL)

        raise RuntimeError("Folder export timed out while waiting for OMERO.")

    def _export_folder_worker(self, selected_folder, folder_name):
        """Export the folder through the OMERO.web folder export workflow.

        Inputs: `selected_folder`, `folder_name`. Output: None. Raises: RuntimeError
        when validation or the called operation fails.
        """
        export_succeeded = False
        try:
            self._set_status("Scanning selected folder...", "#fff3cd")
            local_entries = _collect_local_folder_entries(selected_folder)
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
            upload_url = job_payload.get("upload_url")
            import_step_url = job_payload.get("import_step_url")
            status_url = job_payload.get("status_url")
            confirm_url = job_payload.get("confirm_url")

            if (
                not upload_url
                or not import_step_url
                or not status_url
                or not confirm_url
            ):
                raise RuntimeError(
                    "OMERO returned an incomplete folder-export job response."
                )

            chunk_size = _upload_chunk_size_bytes()
            uploaded_bytes = 0
            file_count = len(local_entries)

            for file_index, entry in enumerate(local_entries, start=1):
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
                        chunk_start += len(chunk)
                        uploaded_bytes += len(chunk)
                        if is_last_chunk:
                            break

                if chunk_start != file_size:
                    raise RuntimeError(
                        f"Folder upload size verification failed for {relative_path}."
                    )

            self._set_status("Starting OMERO folder export...", "#fff3cd")
            self.client.trigger_folder_export(import_step_url)
            final_status = self._wait_for_folder_export_completion(
                folder_name,
                status_url,
                confirm_url,
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
        except Exception as exc:
            self._set_status("Folder export failed", "#f8d7da")
            self._show_error("Folder Export Failed", str(exc))
            _xt_debug(f"Folder export failed: {type(exc).__name__}: {exc}")
        finally:
            self._invoke_on_ui_thread(
                partial(self._finish_export_workflow, export_succeeded),
                wait=False,
            )

    def _hide_converter_frame(self):
        """Hide the converter frame for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if hasattr(self.converter_frame, "grid_remove"):
            self.converter_frame.grid_remove()
            return
        self.converter_frame.pack_forget()

    def _show_converter_frame(self):
        """Show the converter frame for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        if hasattr(self.converter_frame, "grid"):
            self.converter_frame.grid()
            self._enforce_window_minimum_for_current_layout()
            return
        self.converter_frame.pack(side=tk.LEFT, padx=(0, 8))
        self._enforce_window_minimum_for_current_layout()

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
        self.root.update_idletasks()

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
            self.client.password = ""
            self.client.csrf_token = None
            self.client.session_id = None
            self.client.session_key = None
        self.client = None
        self._connected = False
        self._pid = None
        self._did = None
        self._refresh_generation += 1
        self._refresh_in_progress = False
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
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

    def _detect_converter_options_after_connection(self):
        """Populate converter options only after login and native-open checks.

        Inputs: none. Output: `options`.
        """
        self._reset_native_bridge_probe_for_converter_detection()
        self._start_native_bridge_probe()
        if not self._native_bridge_probe_done.wait(timeout=NATIVE_BRIDGE_PROBE_TIMEOUT):
            _xt_debug("Native bridge probe timed out during converter detection")
            native_available = False
            bridge_error = "probe timed out"
        else:
            with self._native_bridge_probe_lock:
                native_available = self._native_bridge_available
                bridge_error = self._native_bridge_probe_error
        if not native_available:
            _xt_debug(f"Same-session Imaris bridge unavailable: {bridge_error}")

        can_attempt_imaris_handoff = (
            native_available or self._has_imaris_handoff_target()
        )
        options = []
        omero_available = False
        if can_attempt_imaris_handoff and self.client:
            omero_available = self.client.has_omero_ims_export_capability()
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
        return _looks_like_imaris_application(getattr(self, "imaris", None)) or (
            _coerce_imaris_id(getattr(self, "imaris_id", None)) is not None
        )

    def _detect_folder_export_after_connection(self):
        """Detect folder export availability after connection.

        Inputs: none. Output: `capability`.
        """
        if not self.client:
            return {"available": False, "reason": "No OMERO.web client is available."}
        capability = self.client.get_folder_export_capability()
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
            self.root.update_idletasks()

        self.root.after(0, update)

    def _draw_connection_indicator(self, state):
        """Draw a compact status indicator in the bottom status row.

        Inputs: `state`. Output: None.
        """
        canvas = getattr(self, "connection_indicator", None)
        if canvas is None:
            return
        palette = {
            "connected": ("#1f9d55", "#7ee2a8", "#0f5f34"),
            "busy": (
                ("#2f80ed", "#93c5fd", "#1d4ed8")
                if self._indicator_blink_on
                else ("#93c5fd", "#dbeafe", "#2f80ed")
            ),
            "error": ("#d64545", "#ff9b9b", "#8f1d1d"),
            "disconnected": ("#8a949e", "#d5dadd", "#5e666e"),
        }
        fill, highlight, shadow = palette.get(state, palette["disconnected"])
        canvas.delete("all")
        canvas.create_oval(7, 5, 29, 27, fill=shadow, outline="")
        canvas.create_oval(5, 3, 27, 25, fill=fill, outline="#ffffff", width=1)
        canvas.create_oval(9, 6, 16, 13, fill=highlight, outline="")

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
        messagebox.showerror(
            "Connection Lost",
            "The OMERO connection was lost. Please reconnect to continue.",
        )

    def _show_error(self, title, message):
        """Show the error for `OMEROBrowserDialog`.

        Inputs: `title`, `message`. Output: None.
        """
        self.root.after(0, lambda: messagebox.showerror(title, message))

    def _show_info(self, title, message):
        """Show the info for `OMEROBrowserDialog`.

        Inputs: `title`, `message`. Output: None.
        """
        self.root.after(0, lambda: messagebox.showinfo(title, message))

    def _show_connector_info(self):
        """Show the modal OMERO connector information window.

        Inputs: none. Output: None.
        """
        info_window = tk.Toplevel(self.root)
        info_window.title(CONNECTOR_INFO_TITLE)
        info_window.resizable(False, False)
        info_window.transient(self.root)
        info_window.configure(bg="#f8fafc")

        frame = tk.Frame(info_window, padx=18, pady=16, bg="#f8fafc")
        frame.grid(row=0, column=0, sticky=tk.NSEW)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)

        title_label = tk.Label(
            frame,
            text=CONNECTOR_INFO_TITLE,
            font=("Arial", 11, "bold"),
            bg="#f8fafc",
            fg="#1f2937",
            anchor=tk.W,
        )
        title_label.grid(row=0, column=0, columnspan=2, sticky=tk.EW)

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
            row=1,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(10, 14),
        )

        metadata_font = ("Arial", 9)
        tk.Label(
            frame,
            text=f"Author: {CONNECTOR_INFO_AUTHOR}",
            font=metadata_font,
            bg="#f8fafc",
            fg="#1f2937",
            anchor=tk.W,
        ).grid(row=2, column=0, sticky=tk.W, pady=(0, 3))
        tk.Label(
            frame,
            text=f"Version: {CONNECTOR_INFO_VERSION}",
            font=metadata_font,
            bg="#f8fafc",
            fg="#1f2937",
            anchor=tk.W,
        ).grid(row=3, column=0, sticky=tk.W)

        close_button = tk.Button(
            frame,
            text="Close",
            command=info_window.destroy,
            font=("Arial", 9),
            width=10,
            default=_tk_constant("ACTIVE", "active"),
        )
        close_button.grid(row=2, column=1, rowspan=2, sticky=tk.SE, padx=(18, 0))

        info_window.protocol("WM_DELETE_WINDOW", info_window.destroy)
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

    def _launch_fresh_imaris_bridge(self):
        """Launch a fresh Imaris session and cache its native bridge.

        Inputs: none. Output: bool.
        """
        self._set_status("Opening a new Imaris session...", "#fff3cd")
        launched_app_id, launched_bridge_python = (
            _launch_imaris_and_find_bridge_python()
        )
        if launched_app_id is None or not launched_bridge_python:
            return False

        self.imaris = None
        self.imaris_id = launched_app_id
        with self._native_bridge_probe_lock:
            self._native_bridge_python_executable = launched_bridge_python
            self._native_bridge_available = True
            self._native_bridge_probe_error = ""
            self._native_bridge_last_verified_at = time.time()
            self._native_bridge_probe_started = True
            self._native_bridge_probe_in_progress = False
            self._native_bridge_probe_done.set()
        _xt_debug("Fresh Imaris session is ready for connector handoff")
        return True

    def _open_with_native_bridge_runner(self, downloaded_file, require_ims=True):
        """Open the with native bridge runner for `OMEROBrowserDialog`.

        Inputs: `downloaded_file`, `require_ims`. Output:
        `_open_file_in_imaris_with_native_bridge_runner` result.
        """
        bridge_python = self._get_native_bridge_python_executable()
        return _open_file_in_imaris_with_native_bridge_runner(
            downloaded_file,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
        )

    def _open_files_with_native_bridge_runner(self, downloaded_files, require_ims=True):
        """Open the files with native bridge runner for `OMEROBrowserDialog`.

        Inputs: `downloaded_files`, `require_ims`. Output:
        `_open_files_in_imaris_with_native_bridge_runner` result.
        """
        bridge_python = self._get_native_bridge_python_executable()
        return _open_files_in_imaris_with_native_bridge_runner(
            downloaded_files,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
        )

    def _open_downloaded_file_in_imaris(self, downloaded_file, require_ims=True):
        """Open one downloaded IMS file in the connected Imaris application.

        Inputs: `downloaded_file`, `require_ims`. Output: `bool`.
        """
        self._set_status("Opening file in Imaris...", "#fff3cd")

        if self.imaris is None and self._get_native_bridge_python_executable():
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
            try:
                self.imaris = _resolve_imaris_application(
                    self.imaris_id,
                    retries=IMARIS_HANDLE_RETRY_ATTEMPTS,
                    retry_interval=IMARIS_HANDLE_RETRY_INTERVAL,
                )
            except Exception as exc:
                _xt_debug(f"Failed to re-acquire Imaris application handle: {exc}")

        if self.imaris is None:
            _xt_debug(
                "Direct Imaris handle remains unavailable in this Python; "
                "continuing with native bridge runner if available"
            )
        else:
            _xt_debug(
                f"Using Imaris handle type={type(self.imaris).__name__} for file open"
            )

        if open_file_in_imaris(downloaded_file, self.imaris, require_ims=require_ims):
            return True

        _xt_debug(
            "Direct Imaris handle path did not open the file; "
            "trying compatible native bridge runner"
        )
        if self._open_with_native_bridge_runner(
            downloaded_file,
            require_ims=require_ims,
        ):
            return True

        _xt_debug(
            "Native bridge runner did not open the file; attempting fresh Imaris launch"
        )
        if self._launch_fresh_imaris_bridge():
            return self._open_with_native_bridge_runner(
                downloaded_file,
                require_ims=require_ims,
            )
        return False

    def _open_downloaded_files_in_imaris(self, downloaded_files, require_ims=True):
        """Open downloaded IMS files in the connected Imaris application.

        Inputs: `downloaded_files`, `require_ims`. Output: `bool`.
        """
        downloaded_files = list(downloaded_files or [])
        if not downloaded_files:
            return False
        if len(downloaded_files) == 1:
            return self._open_downloaded_file_in_imaris(
                downloaded_files[0],
                require_ims=require_ims,
            )

        self._set_status("Opening selected files in Imaris...", "#fff3cd")

        if self.imaris is None and self._get_native_bridge_python_executable():
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
            try:
                self.imaris = _resolve_imaris_application(
                    self.imaris_id,
                    retries=IMARIS_HANDLE_RETRY_ATTEMPTS,
                    retry_interval=IMARIS_HANDLE_RETRY_INTERVAL,
                )
            except Exception as exc:
                _xt_debug(f"Failed to re-acquire Imaris application handle: {exc}")

        if open_files_in_imaris(downloaded_files, self.imaris, require_ims=require_ims):
            return True

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
            "Native bridge runner did not complete the batch open; "
            "attempting fresh Imaris launch"
        )
        if self._launch_fresh_imaris_bridge():
            return self._open_files_with_native_bridge_runner(
                downloaded_files,
                require_ims=require_ims,
            )
        return False

    def _start_native_bridge_probe(self):
        """Probe native Imaris opening capability in the background.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
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
            if _looks_like_imaris_application(self.imaris):
                self._native_bridge_available = True
                self._native_bridge_last_verified_at = time.time()
                self._native_bridge_probe_in_progress = False
                self._native_bridge_probe_done.set()
                _xt_debug("Native bridge probe skipped: current Imaris handle is live")
                return

        threading.Thread(target=self._native_bridge_probe_worker, daemon=True).start()

    def _reset_native_bridge_probe(self):
        """Cached native-bridge probe state so a later Imaris session is detected.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        with self._native_bridge_probe_lock:
            self._native_bridge_probe_done.clear()
            self._native_bridge_probe_started = False
            self._native_bridge_probe_in_progress = False
            self._native_bridge_available = _looks_like_imaris_application(
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
        self._reset_native_bridge_probe()
        self._start_native_bridge_probe()
        return self._native_bridge_probe_done.wait(timeout=max(0.0, float(timeout)))

    def _native_bridge_probe_worker(self):
        """Probe native bridge readiness in the background refresh worker.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
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

    def _revalidate_native_bridge(self):
        """Synchronously verify that the cached native bridge still resolves Imaris.

        Inputs: none. Output: `bool`.
        """
        if _looks_like_imaris_application(self.imaris):
            with self._native_bridge_probe_lock:
                self._native_bridge_available = True
                self._native_bridge_probe_error = ""
                self._native_bridge_last_verified_at = time.time()
            return True

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
        if _looks_like_imaris_application(self.imaris):
            return True

        self._set_status("Checking Imaris same-session open support...", "#fff3cd")
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

        if self._launch_fresh_imaris_bridge():
            return True

        with self._native_bridge_probe_lock:
            bridge_error = self._native_bridge_probe_error
        _xt_debug(
            "Imaris same-session open bridge failed revalidation before export: "
            f"{bridge_error}"
        )
        return False

    def _connect(self):
        """Open the connection for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: opens the described state and returns None.
        """
        h = self.host_entry.get().strip()
        p = self.port_entry.get().strip()
        u = self.user_entry.get().strip()
        pw = self.pass_entry.get()

        if not all([h, p, u, pw]):
            messagebox.showwarning(
                "Missing Fields", "Please fill all connection fields"
            )
            return

        self._set_converter_options([])
        self._set_folder_export_capability(False, "Detecting OMERO folder export...")

        port = _parse_port(p)
        if port is None:
            messagebox.showerror(
                "Invalid Port",
                "Please enter a valid numeric port (1-65535) for the OMERO.web server.",
            )
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
        self.client = OMEROWebClient(h, port, u, pw, scheme=scheme)

        try:
            if self.client.connect():
                self._connected = True
                self._clear_password_entry()
                self.client.password = ""
                self._set_connect_button(
                    "Disconnect",
                    _tk_constant("NORMAL", "normal"),
                    "#f39c12",
                    active_bg="#d68910",
                )
                self._set_status("Connected to OMERO", "#d4edda")
                self._set_connection_indicator("connected")
                self._schedule_health_ping()
                self._load_projects()
                self._set_status("Detecting connector capabilities...", "#fff3cd")
                converter_options = self._detect_converter_options_after_connection()
                folder_export_capability = self._detect_folder_export_after_connection()
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
            else:
                self._connected = False
                self.client.password = ""
                self.client.csrf_token = None
                self.client.session_id = None
                self.client.session_key = None
                self.client = None
                self._set_folder_export_capability(False, "Connect to OMERO first.")
                self._set_connect_button(
                    "Connect",
                    _tk_constant("NORMAL", "normal"),
                    "#3498db",
                    active_bg="#2f85c7",
                )
                self._set_autosave_settings_control_state(False)
                self._set_status("Connection failed", "#f8d7da")
                self._set_connection_indicator("error")
                messagebox.showerror(
                    "Connection Failed",
                    "Cannot connect to OMERO server.\nPlease check your credentials.",
                )
        finally:
            self._connection_in_progress = False

    def _load_projects(self):
        """Load the projects for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: loads the described state and returns None.
        """
        self.plist.delete(0, _tk_constant("END", "end"))
        self.projects_data = self.client.list_projects()
        self._pid = None
        self._did = None
        self.datasets_data = []
        self.images_data = []
        self._image_selection_anchor = None
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        for p in self.projects_data:
            self.plist.insert(_tk_constant("END", "end"), self._project_list_label(p))

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
        self.images_data = []
        self.datasets_data = self.client.list_datasets(self._pid)
        for d in self.datasets_data:
            self.dlist.insert(_tk_constant("END", "end"), self._dataset_list_label(d))
        self._refresh_load_button_text()

    def _load_imgs(self, did):
        """Load the imgs for `OMEROBrowserDialog`.

        Inputs: `did`. Output: None.
        """
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._did = did
        self.images_data = self.client.list_images(did)
        self._image_selection_anchor = None
        for img in self.images_data:
            self.ilist.insert(_tk_constant("END", "end"), self._image_list_label(img))
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
        self.ilist.bind("<Control-a>", self._on_images_select_all)
        self.ilist.bind("<Control-A>", self._on_images_select_all)

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
        load_btn = getattr(self, "load_btn", None)
        if load_btn is not None:
            load_btn.config(text=self._load_button_text())

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
            self._set_connection_indicator("busy")
            if load_btn is not None:
                load_btn.config(state=disabled)
            self._set_export_button_state(disabled)
            self._set_refresh_button_state(disabled)
            if connect_btn is not None:
                connect_btn.config(state=disabled)
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

    def _clear_actions_busy_for_export(self):
        """Clear the actions busy for export for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._set_actions_busy_for_export(False)

    def _finish_export_workflow(self, succeeded):
        """Restore export action state and reflect final connection indicator state.

        Inputs: `succeeded`. Output: None.
        """
        self._set_actions_busy_for_export(False)
        if succeeded:
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
            self._set_connection_indicator("busy")
            if load_btn is not None:
                load_btn.config(state=disabled, text=self._load_button_text())
            self._set_export_button_state(disabled)
            self._set_refresh_button_state(disabled)
            if connect_btn is not None:
                connect_btn.config(state=disabled)
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

    def _clear_actions_busy_for_load(self):
        """Clear the actions busy for load for `OMEROBrowserDialog`.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        self._set_actions_busy_for_load(False)

    def _finish_load_workflow(self, succeeded):
        """Restore load action state and reflect final connection indicator state.

        Inputs: `succeeded`. Output: None.
        """
        self._set_actions_busy_for_load(False)
        if succeeded:
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
            messagebox.showwarning("Not Connected", "Please connect to OMERO first.")
            return

        self._refresh_in_progress = True
        self._refresh_generation += 1
        generation = self._refresh_generation
        project_id = self._current_selected_project_id()
        dataset_id = self._current_selected_dataset_id()
        self._set_refresh_button_state(_tk_constant("DISABLED", "disabled"))
        self._set_status("Refreshing OMERO browser...", "#fff3cd")
        self._set_connection_indicator("busy")
        threading.Thread(
            target=self._refresh_worker,
            args=(project_id, dataset_id, generation),
            daemon=True,
        ).start()

    def _fetch_browser_state_for_refresh(self, project_id, dataset_id):
        """Fetch the browser state for refresh for `OMEROBrowserDialog`.

        Inputs: `project_id` OMERO project ID, `dataset_id` OMERO dataset ID. Output:
        `tuple`.
        """
        timeout = _refresh_request_timeout_seconds()
        projects = self.client.list_projects(
            timeout=timeout,
            raise_on_error=True,
            retry_transient=True,
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

    def _refresh_worker(self, project_id, dataset_id, generation):
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
                    ) = self._fetch_browser_state_for_refresh(project_id, dataset_id)
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
                    self._set_status(
                        f"Refresh failed; reconnecting ({attempt + 1}/{attempts})...",
                        "#fff3cd",
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

        self.projects_data = projects
        self._replace_listbox_items(
            self.plist,
            [self._project_list_label(project) for project in projects],
        )

        if project_index is None:
            self._pid = None
            self._did = None
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

        self._pid = self._entity_id(projects[project_index])
        self._select_listbox_index(self.plist, project_index)
        self.datasets_data = datasets
        self._replace_listbox_items(
            self.dlist,
            [self._dataset_list_label(dataset) for dataset in datasets],
        )

        if dataset_index is None:
            self._did = None
            self.images_data = []
            self._image_selection_anchor = None
            self._replace_listbox_items(self.ilist, [])
            self._clear_listbox_selection(self.dlist)
            self._refresh_load_button_text()
            if requested_dataset_id is None:
                self._set_status("Datasets refreshed", "#d4edda")
            else:
                self._set_status(
                    "Selected dataset is no longer available; datasets refreshed",
                    "#fff3cd",
                )
            self._finish_refresh_buttons()
            self._restore_idle_connection_indicator()
            return

        self._did = self._entity_id(datasets[dataset_index])
        self._select_listbox_index(self.dlist, dataset_index)
        self.images_data = images
        self._image_selection_anchor = None
        self._replace_listbox_items(
            self.ilist,
            [self._image_list_label(img) for img in images],
        )
        self._clear_listbox_selection(self.ilist)
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
            messagebox.showwarning("Not Connected", "Please connect to OMERO first.")
            return
        if getattr(self, "_refresh_in_progress", False):
            messagebox.showwarning(
                "Refresh In Progress",
                "Please wait for the OMERO browser refresh to finish.",
            )
            return

        selected_path = self._current_local_folder_path()
        if not _is_structurally_valid_folder_path(selected_path):
            messagebox.showwarning(
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
            messagebox.showwarning("No Selection", "Please select at least one image")
            return

        converter = _stringvar_value(getattr(self, "converter_var", None))
        if converter not in {"OMERO", "Imaris"}:
            messagebox.showwarning(
                "No Converter",
                "Please connect to OMERO and select an available converter.",
            )
            return

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
            confirmation = (
                f"Download {len(selected_images)} selected images and hand them "
                "to Imaris after all files are ready?\n\n"
                f"Converter: {converter}"
            )
            worker_args = (selected_images, converter)
            worker_target = self._load_multiple_worker

        if not messagebox.askyesno(
            "Confirm Load",
            confirmation,
        ):
            return

        self._set_actions_busy_for_load(True)
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

    def _load_worker(self, img, converter):
        """Load the worker for `OMEROBrowserDialog`.

        Inputs: `img`, `converter`. Output: None. Raises: RuntimeError when validation or the
        called operation fails.
        """
        workflow_succeeded = False
        try:
            image_id = img.get("id") if isinstance(img, dict) else None
            if image_id is None:
                raise RuntimeError("Selected image is missing an OMERO image id.")
            image_name = self._image_display_name(img)
            _xt_debug(f"Load worker starting image_id={image_id} converter={converter}")
            if (
                converter in {"OMERO", "Imaris"}
                and not self._ensure_native_open_ready_before_export()
            ):
                blocked_action = (
                    "Download/conversion" if converter == "OMERO" else "Download"
                )
                raise RuntimeError(
                    "Cannot open files in the running Imaris session because no "
                    f"compatible Imaris bridge is available. {blocked_action} "
                    "was not started."
                )

            # Download directory
            download_dir = os.path.join(
                self.export_dir,
                self._image_cache_subdir(image_id),
            )
            os.makedirs(download_dir, exist_ok=True)

            require_ims = converter == "OMERO"
            if converter == "OMERO":
                self._set_status(f"Exporting IMS for {image_name}...", "#fff3cd")
                self._set_status("Running server-side IMS export...", "#fff3cd")
                downloaded_file = self.client.download_ims_export(
                    image_id,
                    download_dir,
                    fallback_name=f"{self._image_cache_subdir(image_id)}.ims",
                )
            elif converter == "Imaris":
                self._set_status(
                    f"Downloading original file for {image_name}...", "#fff3cd"
                )
                downloaded_file = self.client.download_original_file(
                    image_id,
                    download_dir,
                    fallback_name=img.get("name") or self._image_cache_subdir(image_id),
                )
            else:
                raise RuntimeError(f"Unsupported converter: {converter}")

            if not downloaded_file or not os.path.exists(downloaded_file):
                raise RuntimeError("Failed to download file from OMERO.")

            if require_ims and not is_ims_file(downloaded_file):
                raise RuntimeError(
                    "Downloaded file is not a valid IMS (HDF5) file. "
                    "Refusing to open the invalid server-side export in Imaris. "
                    "Please verify that the server-side conversion completed successfully."
                )

            self._set_status(
                f"Downloaded: {os.path.basename(downloaded_file)}", "#d4edda"
            )
            _xt_debug("Downloaded file stored in connector export cache")

            self.temp_files.append(downloaded_file)

            if converter == "OMERO":
                # Open in Imaris on the UI thread so the XT handle stays in the
                # same thread/apartment as the original dialog.
                success = self._invoke_on_ui_thread(
                    lambda: self._open_downloaded_file_in_imaris(
                        downloaded_file,
                        require_ims=True,
                    )
                )
                success_status = "Opened IMS in current Imaris session"
                success_title = "Success"
                success_message = "IMS file opened in the current Imaris session."
                failure_message = "Failed to open IMS in the current Imaris session."
            else:
                self._set_status("Submitting original file to Imaris...", "#fff3cd")
                success = self._invoke_on_ui_thread(
                    lambda: self._open_downloaded_file_in_imaris(
                        downloaded_file,
                        require_ims=False,
                    )
                )
                success_status = "Submitted original file to Imaris"
                success_title = "Submitted to Imaris"
                success_message = (
                    "Imaris accepted the original-file open request in the current "
                    "session. A loaded dataset may not be observable yet because the "
                    "native Imaris import workflow can continue interactively there."
                )
                failure_message = "Failed to submit the original file to Imaris."

            if success:
                self._set_status(success_status, "#d4edda")
                self._show_info(
                    success_title,
                    success_message,
                )
                workflow_succeeded = True
            else:
                raise RuntimeError(failure_message)

        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            _xt_debug(f"Load worker failed: {type(e).__name__}: {e}")
        finally:
            self._invoke_on_ui_thread(
                partial(self._finish_load_workflow, workflow_succeeded),
                wait=False,
            )

    def _load_multiple_worker(self, images, converter):
        """Load the multiple worker for `OMEROBrowserDialog`.

        Inputs: `images`, `converter`. Output: None. Raises: RuntimeError when validation or the
        called operation fails.
        """
        workflow_succeeded = False
        try:
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
                if not self._ensure_native_open_ready_before_export():
                    raise RuntimeError(
                        "Cannot open files in the running Imaris session because no "
                        "compatible Imaris bridge is available. Download was not started."
                    )
            else:
                raise RuntimeError(f"Unsupported converter: {converter}")

            downloaded_files = []
            require_ims = converter == "OMERO"
            for index, img in enumerate(selected_images, start=1):
                image_id = img.get("id")
                if image_id is None:
                    raise RuntimeError("A selected image is missing an OMERO image id.")
                image_name = self._image_display_name(img)
                download_dir = os.path.join(
                    self.export_dir,
                    self._image_cache_subdir(image_id),
                )
                os.makedirs(download_dir, exist_ok=True)

                if converter == "OMERO":
                    self._set_status(
                        f"Exporting IMS {index}/{count}: {image_name}", "#fff3cd"
                    )
                    downloaded_file = self.client.download_ims_export(
                        image_id,
                        download_dir,
                        fallback_name=f"{self._image_cache_subdir(image_id)}.ims",
                    )
                else:
                    self._set_status(
                        f"Downloading original {index}/{count}: {image_name}",
                        "#fff3cd",
                    )
                    downloaded_file = self.client.download_original_file(
                        image_id,
                        download_dir,
                        fallback_name=img.get("name")
                        or self._image_cache_subdir(image_id),
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

                downloaded_files.append(downloaded_file)
                self.temp_files.append(downloaded_file)

            self._set_status(
                "All selected files are ready; submitting them to Imaris...",
                "#fff3cd",
            )
            _xt_debug(
                f"Prepared {len(downloaded_files)} selected files before Imaris handoff"
            )

            if converter == "OMERO":
                success = self._invoke_on_ui_thread(
                    lambda: self._open_downloaded_files_in_imaris(
                        downloaded_files,
                        require_ims=True,
                    )
                )
                success_status = "Submitted selected IMS files to Imaris"
                success_title = "Success"
                success_message = (
                    "All selected IMS files were handed to the current Imaris session "
                    "after every download completed."
                )
                failure_message = "Imaris did not accept the prepared IMS file batch."
            else:
                success = self._invoke_on_ui_thread(
                    lambda: self._open_downloaded_files_in_imaris(
                        downloaded_files,
                        require_ims=False,
                    )
                )
                success_status = "Submitted selected original files to Imaris"
                success_title = "Submitted to Imaris"
                success_message = (
                    "Imaris accepted the selected original-file open requests in the "
                    "current session after every download completed. Loaded datasets "
                    "may not be observable yet because native Imaris import can "
                    "continue interactively there."
                )
                failure_message = (
                    "Failed to submit the selected original files to Imaris."
                )

            if success:
                self._set_status(success_status, "#d4edda")
                self._show_info(success_title, success_message)
                workflow_succeeded = True
            else:
                raise RuntimeError(failure_message)

        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            _xt_debug(f"Multi-image load worker failed: {type(e).__name__}: {e}")
        finally:
            self._invoke_on_ui_thread(
                partial(self._finish_load_workflow, workflow_succeeded),
                wait=False,
            )

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
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    except Exception:
        ts = "unknown"
    return str(Path(tempfile.gettempdir()) / f"XTOmeroConnector_{ts}.log")


def _xt_write_log(log_path, msg):
    """Append a sanitized diagnostic message to the Imaris XT log.

    Inputs: `log_path`, `msg`. Output: None.
    """
    candidate = _safe_xt_log_file(log_path)
    if candidate is None:
        return
    safe_msg = _sanitize_xt_log_message(msg)
    try:
        with candidate.open("a", encoding="utf-8", errors="replace") as f:
            f.write(safe_msg)
            if not safe_msg.endswith("\n"):
                f.write("\n")
    except Exception as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )


def _xt_show_fatal(title, message):
    """Show a fatal Imaris XT startup error to the operator.

    Inputs: `title`, `message`. Output: None.
    """
    try:
        messagebox.showerror(title, message)
    except Exception:
        print(title + ": " + message)


def XTOmeroConnector(aImarisId):
    """Called by Imaris.

    Inputs: `aImarisId`. Output: None.
    """
    platform_status = _windows_platform_status()
    log_path = _xt_log_path()
    _XT_RUNTIME_STATE.log_path = log_path
    if not platform_status.supported:
        block_message = "XTOmeroConnector startup blocked: " + platform_status.message
        _xt_write_log(log_path, block_message)
        print(block_message)
        return

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

    except Exception as e:
        tb = traceback.format_exc()
        _xt_write_log(log_path, tb)
        _xt_show_fatal(
            "XTOmeroConnector crashed",
            f"{e}\n\nA detailed log was written to:\n{log_path}",
        )
        # Keep console open when launched by double-click / Imaris
        try:
            input("Press ENTER to close...")
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
            )


if __name__ == "__main__":
    # Manual debug mode (outside Imaris): keep the console open on error.
    try:
        XTOmeroConnector(None)
    except Exception as e:
        print("Fatal:", e)
        try:
            input("Press ENTER to close...")
        except Exception as exc:
            logger.debug(
                "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
            )
