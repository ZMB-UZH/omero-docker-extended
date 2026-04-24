import logging
import traceback
import importlib

logger = logging.getLogger(__name__)
#
# <CustomTools>
#  <Menu>
#   <Item name="OMERO Connector" icon="Python3" tooltip="Load images from OMERO server">
#    <Command>Python3XT::XTOmeroConnector(%i)</Command>
#   </Item>
#  </Menu>
# </CustomTools>
#

"""
ImarisXT OMERO Connector
Requests server-side IMS conversion and opens the resulting IMS in Imaris.
"""

import sys
import os
import json
import ntpath
import stat
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import re
import tempfile
import time
import datetime
import posixpath
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
from pathlib import Path, PurePosixPath
from typing import Any, List, Optional

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
FOLDER_IMPORT_TIMEOUT = 3600
FOLDER_IMPORT_POLL_INTERVAL = 2.0
FOLDER_IMPORT_CONFIRM_PREVIEW_LIMIT = 10
IMARIS_HANDLE_RETRY_ATTEMPTS = 10
IMARIS_HANDLE_RETRY_INTERVAL = 0.25
NATIVE_BRIDGE_RUNNER_TIMEOUT = 600
NATIVE_BRIDGE_PROBE_TIMEOUT = 60
NATIVE_BRIDGE_REVALIDATE_AFTER = 30.0
IMARIS_OPEN_VERIFY_TIMEOUT = 10.0
IMARIS_OPEN_VERIFY_INTERVAL = 0.25
OMERO_CONNECTOR_WINDOW_WIDTH = 1000
OMERO_CONNECTOR_WINDOW_HEIGHT = 700
_XT_LOG_PATH: Optional[str] = None
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
        print("BRIDGE_RUNNER_EXCEPTION: " + str(exc))
        raise
"""


def _coerce_path(value):
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
    candidate = _coerce_path(file_path)
    if candidate is None:
        return None
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _safe_xt_log_file(log_path):
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
    """Redact credentials, session material, and local user paths from diagnostics."""
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
    """Return a diagnostic URL shape without hostnames, IDs, or query values."""
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
    """Return a bounded download buffer size for streaming HTTP responses."""
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


def _upload_chunk_size_bytes():
    """Return a bounded upload chunk size for streaming multipart requests."""
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


def _stringvar_value(variable):
    if variable is None:
        return ""
    getter = getattr(variable, "get", None)
    if callable(getter):
        value = getter()
    else:
        value = getattr(variable, "value", "")
    return str(value or "")


def _multipart_form_body(fields, file_field_name, file_name, file_bytes):
    boundary = f"----OMEROConnector{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{os.getpid()}{int(time.time() * 1000000)}"
    body = bytearray()

    def append_text(value):
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
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _collect_local_folder_entries(folder_path):
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
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {_sanitize_xt_log_message(message)}"
    print(line)
    if _XT_LOG_PATH:
        _xt_write_log(_XT_LOG_PATH, line)


def _parse_port(port_value):
    """Parse a port value into an integer or return None if invalid."""
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
    """Check if a file looks like an Imaris IMS (HDF5) file."""
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
    for method_name in ("GetCurrentFileName", "GetCurrentFilePath"):
        method = getattr(imaris_app, method_name, None)
        if callable(method):
            return method
    return None


def _normalize_imaris_compare_path(path_value):
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
    """Attempt to open a file in Imaris using FileOpen."""
    verification_mode = "current_file" if require_ims else "submission_only"
    return _open_file_in_imaris_with_mode(file_path, imaris_app, verification_mode)


def open_files_in_imaris(file_paths, imaris_app, require_ims=True):
    """Open already prepared files in the current Imaris application handle."""
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
    """Open prepared files as separate images in the current Imaris application."""
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
    """Return True when the object looks like a live Imaris application handle."""
    if candidate is None:
        return False
    return callable(getattr(candidate, "FileOpen", None))


def _infer_imaris_major_version_from_path(path_value):
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
    major = _infer_imaris_major_version_from_path(path_value)
    return major is not None and major >= 11


def _tk_constant(name, fallback):
    return getattr(tk, name, fallback)


def _widget_background(widget):
    try:
        return widget.cget("bg")
    except Exception:
        return "#f0f0f0"


def _hex_to_rgb(value, fallback=(128, 128, 128)):
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
    red = max(0, min(255, int(rgb[0])))
    green = max(0, min(255, int(rgb[1])))
    blue = max(0, min(255, int(rgb[2])))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _blend_colors(first, second, second_weight):
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
    target = "#ffffff" if amount >= 0 else "#000000"
    return _blend_colors(value, target, abs(amount))


def _normalized_tk_state(state):
    return str(state or _tk_constant("NORMAL", "normal")).lower()


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

    def pack(self, *args, **kwargs):
        return self._canvas.pack(*args, **kwargs)

    def grid(self, *args, **kwargs):
        return self._canvas.grid(*args, **kwargs)

    def place(self, *args, **kwargs):
        return self._canvas.place(*args, **kwargs)

    def pack_forget(self):
        return self._canvas.pack_forget()

    def grid_remove(self):
        return self._canvas.grid_remove()

    def config(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        for key, value in kwargs.items():
            if key in {"bg", "background"}:
                self._bg = value
            elif key == "activebackground":
                self._active_bg = value
            elif key in {"fg", "foreground"}:
                self._fg = value
            elif key == "activeforeground":
                self._active_fg = value
            elif key == "text":
                self._text = value
            elif key == "command":
                self._command = value
            elif key == "font":
                self._font = value
            elif key == "state":
                self._state = value
                if not self._is_enabled():
                    self._pressed = False
                    self._hover = False
            elif key == "width":
                self._width = int(value)
                self._canvas.config(width=self._width)
            elif key == "height":
                self._height = int(value)
                self._canvas.config(height=self._height)
            else:
                self._canvas.config(**{key: value})
        self._sync_cursor()
        self._redraw()

    configure = config

    def cget(self, key):
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
        if self._is_enabled() and self._command is not None:
            return self._command()
        return None

    def _is_enabled(self):
        return _normalized_tk_state(self._state) != _normalized_tk_state(
            _tk_constant("DISABLED", "disabled")
        )

    def _sync_cursor(self):
        cursor = "hand2" if self._is_enabled() else "arrow"
        self._canvas.config(cursor=cursor)

    def _on_enter(self, _event):
        if self._is_enabled():
            self._hover = True
            self._redraw()

    def _on_leave(self, _event):
        self._hover = False
        self._pressed = False
        self._redraw()

    def _on_press(self, _event):
        if self._is_enabled():
            self._pressed = True
            self._redraw()

    def _on_release(self, event):
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


def _iter_imaris_executable_candidates():
    """Yield plausible Imaris executable paths without requiring admin access."""
    seen = set()

    def _yield_candidate(path):
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
    """Return a launchable Imaris.exe path if present."""
    if os.name != "nt":
        return None
    for candidate in _iter_imaris_executable_candidates():
        if os.path.isfile(candidate) and _is_supported_imaris_install_path(candidate):
            return candidate
    return None


def _existing_regular_file_path_list(file_paths):
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
    """Yield plausible Imaris installation roots."""
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
    """Yield native Imaris XT directories that may contain modules or DLLs."""
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
    """Parse `py -0p` output into Python executable paths."""
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
    """Yield installed Python executables other than the current process."""
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


def _run_native_bridge_helper(python_executable, payload, context, timeout):
    """Run a fixed native bridge helper under a candidate Python executable."""
    if payload is None:
        return False

    resolved_python = _resolve_python_executable_candidate(python_executable)
    if resolved_python is None:
        return False

    import subprocess

    _xt_debug(f"Trying native Imaris bridge runner ({context}) with {resolved_python}")
    try:
        completed = subprocess.run(
            [resolved_python, "-c", _NATIVE_BRIDGE_OPEN_HELPER],
            check=False,
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
    except Exception as exc:
        _xt_debug(f"Native Imaris bridge runner ({context}) failed to start: {exc}")
        return False

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if stdout:
        if stdout == "BRIDGE_RUNNER_PROBE_OK":
            _xt_debug(
                f"Native bridge runner ({context}) resolved the current Imaris session"
            )
        elif stdout in {"BRIDGE_RUNNER_OPENED", "BRIDGE_RUNNER_OPENED_MANY"}:
            if payload.get("require_ims") is False:
                action = (
                    "submitted the selected original-file open requests in the "
                    "current Imaris session"
                    if stdout == "BRIDGE_RUNNER_OPENED_MANY"
                    else "submitted the original-file open request in the current "
                    "Imaris session"
                )
            else:
                action = "completed open request in the current Imaris session"
            _xt_debug(f"Native bridge runner ({context}) {action}")
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
        else:
            _xt_debug(f"Native bridge runner ({context}) stdout: {stdout[:4000]}")
    if stderr:
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
        else:
            _xt_debug(
                f"Native bridge runner ({context}) suppressed benign Ice shutdown warning"
            )
    _xt_debug(f"Native bridge runner ({context}) exit code: {completed.returncode}")
    return completed.returncode == 0


def _run_native_bridge_probe_helper(python_executable, imaris_id):
    """Check whether a candidate Python can load ImarisLib and resolve the app."""
    return _run_native_bridge_helper(
        python_executable,
        _native_bridge_payload(imaris_id, "probe"),
        "probe",
        NATIVE_BRIDGE_PROBE_TIMEOUT,
    )


def _run_native_bridge_open_helper(
    python_executable, file_path, imaris_id, require_ims=True
):
    """Open an IMS via ImarisLib using a compatible native Python process."""
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
    """Open prepared files via ImarisLib using a compatible native Python process."""
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
    """Return an installed Python executable that can use Imaris' native bridge."""
    if _coerce_imaris_id(imaris_id) is None:
        return None
    for python_executable in _iter_native_bridge_python_executables():
        if _run_native_bridge_probe_helper(python_executable, imaris_id):
            return python_executable
    return None


def _open_file_in_imaris_with_native_bridge_runner(
    file_path, imaris_id, preferred_python_executable=None, require_ims=True
):
    """Try compatible installed Python runtimes while staying on ImarisLib/FileOpen."""
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
    """Try compatible installed Python runtimes while staying on ImarisLib/FileOpen."""
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
    normalized = os.path.normpath(candidate)
    if normalized in values:
        return False
    values.insert(0, normalized)
    return True


def _prepare_imaris_xt_environment():
    """Add bundled Imaris XT Python paths and DLL directories so ImarisLib/IcePy can load."""
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
    try:
        return bool(path_value) and os.path.exists(path_value)
    except Exception:
        return False


def _probe_module_import(module_name):
    try:
        __import__(module_name)
        return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _set_process_window_title(title):
    """Best-effort Windows console title update without shelling out."""
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


def _extract_content_disposition_filename(content_disposition):
    """Extract an HTTP Content-Disposition filename without trusting path parts."""
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
    """Return a single safe filename for connector-managed downloads."""
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
    """Build a download path inside download_dir without overwriting locked files."""
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
    """Collect host-side diagnostics for the Imaris XT runtime."""
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

    return {
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "python_version_short": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
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
    """Normalize XT entrypoint values to an integer application id when possible."""
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
    """Resolve the live Imaris application handle from the XT entrypoint value."""
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
            version_info = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
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
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"{scheme}://{host}:{port}"

    def _create_request_with_cookies(self, url, data=None, method=None):
        """Create a request and let urllib's cookie jar manage session cookies."""
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
        """Extract session and CSRF cookies from the cookie jar."""
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
        """Check if a response was redirected to login page.

        Returns True if redirected to login (authentication failed).
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
        """Best-effort detection for HTML login content returned with 200."""
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
        """Ensure API endpoints query all groups accessible to the user."""
        if "group=" in endpoint:
            return endpoint
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}group=-1"

    def _extract_items(self, payload, collection_keys=None):
        """Extract list payloads from common API response wrappers."""
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
        """Normalize API rows into [{'id': ..., 'name': ...}] objects."""
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
        """Attempt to re-authenticate and return True on success."""
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

    def connect(self):
        """Authenticate with OMERO.web."""
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
                    "password": self.password,
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

    def _api_request(self, endpoint):
        """Make API request with explicit cookie handling."""
        if not self.session_id:
            _xt_debug("API request skipped: no session")
            return None

        url = f"{self.api_url}/{endpoint}"
        _xt_debug(f"API GET endpoint={_safe_url_for_log(url)}")

        # Create request with explicit cookies
        req = self._create_request_with_cookies(url)

        try:
            # Use opener for cookie jar updates, but we've also set explicit headers
            response = self.opener.open(req, timeout=30)

            if self._check_login_redirect(response, "API request"):
                return None

            _xt_debug(f"API GET response={getattr(response, 'status', 'unknown')}")
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw = response.read()
            if "text/html" in content_type and self._looks_like_login_page(raw):
                _xt_debug("API request returned login HTML instead of JSON")
                return None
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            _xt_debug(f"API error: invalid JSON response ({e})")
            return None
        except urllib.error.HTTPError as e:
            _xt_debug(f"API error ({e.code}): {e.reason}")
            return None
        except Exception as e:
            _xt_debug(f"API error: {e}")
            return None

    def _api_post(self, endpoint, payload=None):
        """POST JSON to OMERO.web API with explicit cookie handling."""
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
    ):
        if not self.session_id:
            raise RuntimeError("Not authenticated to OMERO.web. Please connect again.")

        data = raw_data
        if data is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
            if content_type is None:
                content_type = "application/json"

        request_method = method or ("POST" if data is not None else "GET")
        req = self._create_request_with_cookies(url, data=data, method=request_method)
        if content_type:
            req.add_header("Content-Type", content_type)
        for key, value in list((headers or {}).items()):
            req.add_header(key, value)

        raw_body = b""
        try:
            with self.opener.open(req, timeout=timeout) as response:
                if self._check_login_redirect(response, context):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web. Please connect again."
                    )
                status_code = getattr(response, "status", 200)
                raw_body = response.read()
                if self._looks_like_login_page(raw_body):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web. Please connect again."
                    )
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            try:
                raw_body = exc.read()
            except Exception:
                raw_body = b""
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{context} failed: {exc}") from exc

        raw_text = raw_body.decode("utf-8", errors="replace") if raw_body else ""
        decoded = None
        if raw_text.strip():
            try:
                decoded = json.loads(raw_text)
            except json.JSONDecodeError:
                decoded = None
        return status_code, decoded, raw_text

    def get_image_metadata(self, image_id):
        """Get image metadata including original filename."""
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
        """List available scripts."""
        data = self._api_request("scripts/")
        if data and isinstance(data, dict):
            scripts = data.get("data") or data.get("scripts") or []
            if isinstance(scripts, dict):
                scripts = scripts.get("data") or scripts.get("scripts") or []
            return scripts
        return []

    def find_script_id(self, script_name):
        """Find script ID by matching script name or path."""
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
        """Run a script with provided inputs."""
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
        """Return True when this OMERO.web instance exposes server-side IMS export."""
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

    def get_folder_import_capability(self):
        """Detect whether the current OMERO.web instance exposes folder import."""
        if not self.session_id:
            return {
                "available": False,
                "reason": "Not authenticated to OMERO.web.",
            }

        capability_url = f"{self.base_url.rstrip('/')}/omeroweb_import/start/"
        _xt_debug(
            "Checking OMERO folder import capability endpoint="
            f"{_safe_url_for_log(capability_url)}"
        )
        try:
            status_code, payload, raw_text = self._request_json_url(
                capability_url,
                method="POST",
                payload={},
                timeout=30,
                context="folder import capability check",
            )
        except Exception as exc:
            _xt_debug(f"OMERO folder import capability unavailable: {exc}")
            return {"available": False, "reason": str(exc)}

        message = self._payload_error_message(
            payload,
            raw_text,
            f"HTTP {status_code}",
        )
        lowered = message.lower()
        if message == "No files provided.":
            _xt_debug("OMERO folder import capability available=True")
            return {"available": True, "reason": ""}
        if "please login as regular user" in lowered:
            _xt_debug(
                "OMERO folder import capability unavailable: regular user required"
            )
            return {
                "available": False,
                "reason": "Folder import is unavailable for the OMERO root user.",
            }
        if isinstance(payload, dict) and payload.get("ok") is False and message:
            _xt_debug(f"OMERO folder import capability unavailable: {message}")
            return {"available": False, "reason": message}

        _xt_debug(
            "OMERO folder import capability unavailable: "
            f"unexpected status={status_code}"
        )
        return {
            "available": False,
            "reason": "Folder import is not available on this OMERO.web instance.",
        }

    def start_folder_import_job(self, dataset_name, file_entries):
        """Create a folder-import job using the detected OMERO.web upload flow."""
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
            "Starting OMERO folder import job via endpoint="
            f"{_safe_url_for_log(start_url)}"
        )
        status_code, payload, raw_text = self._request_json_url(
            start_url,
            method="POST",
            payload={
                "files": files,
                "dataset_name_override": dataset_name.strip(),
                "compatibility_enabled": True,
            },
            timeout=60,
            context="folder import start",
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
                    "Failed to start OMERO folder import.",
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
        if not upload_url:
            raise RuntimeError("The OMERO upload URL is missing.")
        safe_relative_path = str(relative_path or "").strip()
        if not safe_relative_path:
            raise RuntimeError("A folder import file path is missing.")
        boundary, body = _multipart_form_body(
            {
                "upload_mode": "chunked",
                "relative_path": safe_relative_path,
                "chunk_start": int(chunk_start),
                "chunk_end": int(chunk_start) + len(chunk_bytes or b""),
                "file_size": int(file_size),
                "is_last_chunk": "1" if is_last_chunk else "0",
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
            context="folder import chunk upload",
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

    def trigger_folder_import(self, import_step_url):
        if not import_step_url:
            raise RuntimeError("The OMERO import-step URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            import_step_url,
            method="POST",
            payload={},
            timeout=60,
            context="folder import trigger",
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
                    "Failed to start the OMERO import.",
                )
            )
        return payload

    def confirm_folder_import(self, confirm_url):
        if not confirm_url:
            raise RuntimeError("The OMERO confirmation URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            confirm_url,
            method="POST",
            payload={},
            timeout=60,
            context="folder import confirmation",
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
                    "Failed to confirm the OMERO import.",
                )
            )
        return payload

    def get_folder_import_status(self, status_url):
        if not status_url:
            raise RuntimeError("The OMERO status URL is missing.")
        status_code, payload, raw_text = self._request_json_url(
            status_url,
            method="GET",
            timeout=30,
            context="folder import status poll",
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
                    "Failed to poll the OMERO import status.",
                )
            )
        return payload

    def poll_activity(self, job_id, timeout=900, interval=2):
        """Poll a script activity until completion."""
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

    def list_projects(self):
        """List all projects."""
        data = self._api_request(self._with_all_groups("m/projects/"))
        if not data:
            return []
        projects = self._extract_items(
            data,
            collection_keys=("data", "projects", "results", "items", "objects"),
        )
        return self._build_named_entities(projects, default_prefix="Project")

    def list_datasets(self, project_id):
        """List datasets in a project."""
        data = self._api_request(
            self._with_all_groups(f"m/projects/{project_id}/datasets/")
        )
        datasets = self._extract_items(
            data,
            collection_keys=("data", "datasets", "results", "items", "objects"),
        )
        if datasets:
            return self._build_named_entities(datasets, default_prefix="Dataset")

        data = self._api_request(self._with_all_groups(f"m/projects/{project_id}/"))
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

    def list_images(self, dataset_id):
        """List images in a dataset."""
        data = self._api_request(
            self._with_all_groups(f"m/datasets/{dataset_id}/images/")
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
        """
        Download an Imaris .ims export for a given image_id.

        Uses the OMERO.web plugin endpoint:
            /omeroweb_imaris_connector/imaris-export/?image=<id>

        This intentionally avoids /api/v0/scripts/ (often not available).
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

        export_url = f"{base}/omeroweb_imaris_connector/imaris-export/?{urllib.parse.urlencode(query_params)}"
        _xt_debug(f"Requesting IMS export endpoint={_safe_url_for_log(export_url)}")

        os.makedirs(download_dir, exist_ok=True)

        # Create request with explicit cookies
        req = self._create_request_with_cookies(export_url)

        try:
            with self.opener.open(req, timeout=30) as response:
                if self._check_login_redirect(response, "IMS export request"):
                    if not self._attempt_reauth("IMS export request"):
                        raise RuntimeError(
                            "Not authenticated to OMERO.web (redirected to login). Please login again."
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
                                "Not authenticated to OMERO.web (redirected to login) while polling IMS export. "
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
                        "Not authenticated to OMERO.web (redirected to login) while downloading IMS export."
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
        """Download the archived original file for local Imaris opening."""
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
        """Normalize a URL to use the base_url's scheme and host.

        This ensures all URLs point to the same server the client authenticated with.
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
        self._native_bridge_available = _looks_like_imaris_application(self.imaris)
        self._native_bridge_python_executable = None
        self._native_bridge_probe_error = ""
        self._native_bridge_last_verified_at = (
            time.time() if self._native_bridge_available else 0.0
        )
        self._connected = False
        self._connection_in_progress = False
        self._folder_import_available = False
        self._folder_import_reason = "Connect to OMERO first."
        self._import_in_progress = False
        self._image_selection_anchor = None

        # Get export directory
        self.export_dir = self._get_export_dir()

        self.root = tk.Tk()
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
        """Handle window close - don't delete temp files as Imaris might still be using them."""
        self.root.destroy()

    def _build_ui(self):
        # Connection frame
        conn_frame = tk.LabelFrame(
            self.root, text="OMERO connection & settings", padx=10, pady=10
        )
        conn_frame.pack(fill=tk.X, padx=10, pady=10)

        default_host = (
            os.environ.get("OMERO_WEB_HOST")
            or os.environ.get("OMERO_HOST")
            or os.environ.get("OMEROHOST")
            or ""
        )
        default_port = (
            os.environ.get("OMERO_WEB_PORT")
            or os.environ.get("OMERO_WEB_PUBLIC_PORT")
            or os.environ.get("OMERO_PORT")
            or ""
        )
        default_user = os.environ.get("OMERO_USER") or os.environ.get("OMERO_USERNAME")
        default_user = default_user or ""

        tk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.host_entry = tk.Entry(conn_frame, width=25)
        self.host_entry.insert(0, default_host)
        self.host_entry.grid(row=0, column=1, pady=5, padx=5)

        tk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky=tk.W, pady=5)
        self.port_entry = tk.Entry(conn_frame, width=8)
        self.port_entry.insert(0, default_port)
        self.port_entry.grid(row=0, column=3, pady=5, padx=5)

        self.https_var = tk.BooleanVar(value=False)
        tk.Checkbutton(conn_frame, text="Use HTTPS", variable=self.https_var).grid(
            row=0, column=4, pady=5, padx=5
        )

        tk.Label(conn_frame, text="Username:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.user_entry = tk.Entry(conn_frame, width=25)
        self.user_entry.insert(0, default_user)
        self.user_entry.grid(row=1, column=1, pady=5, padx=5)

        tk.Label(conn_frame, text="Password:").grid(
            row=1, column=2, sticky=tk.W, pady=5
        )
        self.pass_entry = tk.Entry(conn_frame, show="*", width=25)
        self.pass_entry.grid(row=1, column=3, columnspan=2, pady=5, padx=5, sticky=tk.W)

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
            font=("Arial", 10),
            width=10,
            padx=10,
            pady=4,
            anchor=tk.W,
            indicatoron=True,
        )
        self.converter_menu_menu = tk.Menu(self.converter_menu, tearoff=0)
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
            row=0,
            column=6,
            rowspan=2,
            sticky=tk.W,
            padx=(14, 0),
            pady=5,
        )
        self.converter_frame.grid_remove()
        conn_frame.grid_columnconfigure(7, weight=1)

        # Browser
        browser = tk.Frame(self.root)
        browser.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Projects
        p_frame = tk.LabelFrame(browser, text="Projects")
        p_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.plist = self._build_scrolled_listbox(p_frame)
        self.plist.bind("<<ListboxSelect>>", lambda e: self._sel_proj())

        # Datasets
        d_frame = tk.LabelFrame(browser, text="Datasets")
        d_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.dlist = self._build_scrolled_listbox(d_frame)
        self.dlist.bind("<<ListboxSelect>>", lambda e: self._sel_ds())

        # Images
        i_frame = tk.LabelFrame(browser, text="Images")
        i_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.ilist = self._build_scrolled_listbox(
            i_frame,
            selectmode=_tk_constant("EXTENDED", "extended"),
        )
        self._configure_image_selection_bindings()

        # Actions
        actions = tk.Frame(self.root)
        actions.pack(fill=tk.X, padx=10, pady=10)

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
        self.load_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.import_btn = _RoundedButton(
            actions,
            text="Import folder into OMERO",
            command=self._import_into_omero,
            bg="#3498db",
            fg="white",
            activebackground="#2f85c7",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            state=_tk_constant("DISABLED", "disabled"),
            width=260,
            height=52,
        )
        self.import_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        close_btn = _RoundedButton(
            actions,
            text="Close",
            command=self._on_close,
            bg="#95a5a6",
            fg="white",
            activebackground="#7f8c8d",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            width=120,
            height=52,
        )
        close_btn.pack(side=tk.LEFT, padx=2)

        # Status
        self.status = tk.Label(
            self.root,
            text="Ready - Please connect to OMERO",
            bg="#ecf0f1",
            anchor=tk.W,
            padx=10,
            pady=5,
            font=("Arial", 9),
            height=2,
        )
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    @staticmethod
    def _build_scrolled_listbox(parent, selectmode=None):
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

    def _configure_initial_window_constraints(self):
        self.root.update_idletasks()
        width = max(
            OMERO_CONNECTOR_WINDOW_WIDTH,
            int(self.root.winfo_width() or 0),
            int(self.root.winfo_reqwidth() or 0),
        )
        height = max(
            OMERO_CONNECTOR_WINDOW_HEIGHT,
            int(self.root.winfo_height() or 0),
            int(self.root.winfo_reqheight() or 0),
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)
        self.root.resizable(True, True)

    def _get_converter_menu(self):
        dialog_menu = getattr(self, "converter_menu_menu", None)
        if dialog_menu is not None:
            return dialog_menu
        menu = getattr(self.converter_menu, "menu", None)
        if menu is not None:
            return menu
        return self.converter_menu["menu"]

    def _set_converter_options(self, options):
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
                command=lambda value=option: self.converter_var.set(value),
            )
        self.converter_var.set(options[0])
        self._show_converter_frame()
        self._set_load_button_for_converter()
        self._set_refresh_button_state(
            _tk_constant("DISABLED", "disabled")
            if getattr(self, "_import_in_progress", False)
            else _tk_constant("NORMAL", "normal")
        )

    def _import_into_omero(self):
        if self._import_in_progress:
            return
        if not self._connected or self.client is None:
            messagebox.showwarning("Not Connected", "Please connect to OMERO first.")
            return
        if not self._folder_import_available:
            messagebox.showwarning(
                "Import Unavailable",
                self._folder_import_reason
                or "Folder import is not available on this OMERO.web instance.",
            )
            return

        selected_folder = filedialog.askdirectory(
            parent=self.root,
            mustexist=True,
            title="Select folder to import into OMERO",
        )
        if not selected_folder:
            return

        folder_name = _folder_display_name(selected_folder)
        if _is_filesystem_root(selected_folder) or not folder_name:
            messagebox.showerror(
                "Invalid Folder",
                "Please select a regular folder, not a filesystem root.",
            )
            return

        confirmation = (
            "Import the selected folder into OMERO root as a dataset?\n\n"
            f"Dataset name: {folder_name}\n"
            "Target: OMERO root (no project)\n\n"
            "This uploads every file inside the selected folder."
        )
        if not messagebox.askyesno("Confirm Folder Import", confirmation):
            return

        self._set_actions_busy_for_import(True)
        self._set_status("Preparing folder import into OMERO...", "#fff3cd")
        threading.Thread(
            target=self._import_folder_worker,
            args=(selected_folder, folder_name),
            daemon=True,
        ).start()

    @staticmethod
    def _folder_import_failure_message(status_payload):
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
        return "OMERO reported that the folder import failed."

    @staticmethod
    def _folder_import_progress_percent(current_value, total_value):
        try:
            current = float(current_value or 0)
            total = float(total_value or 0)
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None
        return max(0.0, min((current / total) * 100.0, 100.0))

    def _folder_import_status_text(self, folder_name, status_payload):
        status = str(status_payload.get("status") or "").strip().lower()
        total_bytes = status_payload.get("total_bytes") or 0

        if status == "uploading":
            percent = self._folder_import_progress_percent(
                status_payload.get("uploaded_bytes"),
                total_bytes,
            )
            if percent is not None:
                return f"Uploading folder to OMERO... {percent:.1f}%"
            return f"Uploading folder '{folder_name}' to OMERO..."

        if status == "checking":
            return "Checking folder import compatibility in OMERO..."
        if status == "awaiting_confirmation":
            return "Waiting for confirmation to continue the OMERO import..."
        if status == "ready":
            return "Starting OMERO import..."
        if status == "importing":
            percent = self._folder_import_progress_percent(
                status_payload.get("import_progress_bytes")
                or status_payload.get("imported_bytes"),
                total_bytes,
            )
            if percent is not None:
                return f"Importing folder into OMERO... {percent:.1f}%"
            return f"Importing folder '{folder_name}' into OMERO..."
        if status == "done":
            return "Folder import completed in OMERO"
        if status == "error":
            return "Folder import failed"
        if status:
            return f"Folder import status: {status}"
        return f"Importing folder '{folder_name}' into OMERO..."

    def _confirm_folder_import_with_incompatible_files(self, status_payload):
        incompatible_files = [
            str(path).strip()
            for path in list(status_payload.get("incompatible_files") or [])
            if str(path).strip()
        ]
        preview = incompatible_files[:FOLDER_IMPORT_CONFIRM_PREVIEW_LIMIT]
        lines = [
            "OMERO reported incompatible files in the selected folder.",
            "",
            "Continue importing the remaining compatible files?",
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
                    "Confirm Compatible OMERO Import",
                    prompt,
                )
            )
        )

    def _wait_for_folder_import_completion(
        self,
        folder_name,
        status_url,
        confirm_url,
    ):
        deadline = time.time() + FOLDER_IMPORT_TIMEOUT
        while time.time() < deadline:
            status_payload = self.client.get_folder_import_status(status_url)
            self._set_status(
                self._folder_import_status_text(folder_name, status_payload),
                "#fff3cd",
            )
            status = str(status_payload.get("status") or "").strip().lower()
            if status == "done":
                return status_payload
            if status == "error":
                raise RuntimeError(self._folder_import_failure_message(status_payload))
            if status_payload.get("confirmation_required"):
                if not self._confirm_folder_import_with_incompatible_files(
                    status_payload
                ):
                    raise RuntimeError(
                        "Folder import was cancelled after OMERO reported incompatible files."
                    )
                self._set_status("Confirming compatible OMERO import...", "#fff3cd")
                self.client.confirm_folder_import(confirm_url)
            time.sleep(FOLDER_IMPORT_POLL_INTERVAL)

        raise RuntimeError("Folder import timed out while waiting for OMERO.")

    def _import_folder_worker(self, selected_folder, folder_name):
        try:
            self._set_status("Scanning selected folder...", "#fff3cd")
            local_entries = _collect_local_folder_entries(selected_folder)
            total_bytes = sum(int(entry.get("size") or 0) for entry in local_entries)
            _xt_debug(
                "Folder import starting "
                f"dataset_name={folder_name!r} file_count={len(local_entries)} "
                f"total_bytes={total_bytes}"
            )

            self._set_status("Creating OMERO upload job...", "#fff3cd")
            job_payload = self.client.start_folder_import_job(
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
                    "OMERO returned an incomplete folder-import job response."
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

            self._set_status("Starting OMERO import...", "#fff3cd")
            self.client.trigger_folder_import(import_step_url)
            final_status = self._wait_for_folder_import_completion(
                folder_name,
                status_url,
                confirm_url,
            )

            incompatible_files = list(final_status.get("incompatible_files") or [])
            if incompatible_files:
                self._set_status(
                    "Folder import completed with compatibility skips",
                    "#fff3cd",
                )
                self._show_info(
                    "Folder Import Completed",
                    (
                        f"The folder was imported into OMERO root as dataset "
                        f"'{folder_name}'.\n\n"
                        f"{len(incompatible_files)} incompatible file(s) were skipped."
                    ),
                )
            else:
                self._set_status("Folder import completed in OMERO", "#d4edda")
                self._show_info(
                    "Folder Import Completed",
                    (
                        f"The folder was imported into OMERO root as dataset "
                        f"'{folder_name}'."
                    ),
                )
        except Exception as exc:
            self._set_status("Folder import failed", "#f8d7da")
            self._show_error("Folder Import Failed", str(exc))
            _xt_debug(f"Folder import failed: {type(exc).__name__}: {exc}")
        finally:
            self._invoke_on_ui_thread(
                self._clear_actions_busy_for_import,
                wait=False,
            )

    def _hide_converter_frame(self):
        if hasattr(self.converter_frame, "grid_remove"):
            self.converter_frame.grid_remove()
            return
        self.converter_frame.pack_forget()

    def _show_converter_frame(self):
        if hasattr(self.converter_frame, "grid"):
            self.converter_frame.grid()
            return
        self.converter_frame.pack(side=tk.LEFT, padx=(0, 8))

    def _set_connect_button(self, text, state, bg, active_bg=None):
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
        if self._connection_in_progress:
            return
        if self._connected:
            self._disconnect()
            return
        self._connect()

    def _disconnect(self):
        """Clear the current OMERO.web session and reset browser state."""
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
        self._set_folder_import_capability(False, "Connect to OMERO first.")
        self.plist.delete(0, _tk_constant("END", "end"))
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        self.pass_entry.delete(0, _tk_constant("END", "end"))
        self._set_converter_options([])
        self._set_connect_button(
            "Connect",
            _tk_constant("NORMAL", "normal"),
            "#3498db",
            active_bg="#2f85c7",
        )
        self._set_status("Disconnected", "#ecf0f1")

    def _detect_converter_options_after_connection(self):
        """Populate converter options only after login and native-open checks."""
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

        options = []
        omero_available = False
        if native_available and self.client:
            omero_available = self.client.has_omero_ims_export_capability()
        if omero_available and native_available:
            options.append("OMERO")
        if native_available:
            options.append("Imaris")
        _xt_debug(f"Detected converter options after connection: {options}")
        return options

    def _detect_folder_import_after_connection(self):
        if not self.client:
            return {"available": False, "reason": "No OMERO.web client is available."}
        capability = self.client.get_folder_import_capability()
        _xt_debug(
            "Detected OMERO folder import capability "
            f"available={bool(capability.get('available'))}"
        )
        return capability

    @staticmethod
    def _get_export_dir():
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

    def _set_status(self, text, color="#ecf0f1"):
        def update():
            self.status.config(text=text, bg=color)
            self.root.update_idletasks()

        self.root.after(0, update)

    def _show_error(self, title, message):
        self.root.after(0, lambda: messagebox.showerror(title, message))

    def _show_info(self, title, message):
        self.root.after(0, lambda: messagebox.showinfo(title, message))

    def _invoke_on_ui_thread(self, callback, wait=True):
        """Run a callback on Tk's UI thread and optionally wait for the result."""
        value: Any = None
        error: Optional[BaseException] = None
        completed = threading.Event()

        def runner():
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
        with self._native_bridge_probe_lock:
            return self._native_bridge_python_executable

    def _open_with_native_bridge_runner(self, downloaded_file, require_ims=True):
        bridge_python = self._get_native_bridge_python_executable()
        return _open_file_in_imaris_with_native_bridge_runner(
            downloaded_file,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
        )

    def _open_files_with_native_bridge_runner(self, downloaded_files, require_ims=True):
        bridge_python = self._get_native_bridge_python_executable()
        return _open_files_in_imaris_with_native_bridge_runner(
            downloaded_files,
            self.imaris_id,
            preferred_python_executable=bridge_python,
            require_ims=require_ims,
        )

    def _open_downloaded_file_in_imaris(self, downloaded_file, require_ims=True):
        """Resolve the Imaris handle on the UI thread and open the file."""
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
        return self._open_with_native_bridge_runner(
            downloaded_file,
            require_ims=require_ims,
        )

    def _open_downloaded_files_in_imaris(self, downloaded_files, require_ims=True):
        """Open a fully prepared batch in the current Imaris session."""
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
                "Opening selected files in the current Imaris session via compatible native bridge runner"
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
        return self._open_files_with_native_bridge_runner(
            downloaded_files,
            require_ims=require_ims,
        )

    def _start_native_bridge_probe(self):
        """Probe native Imaris opening capability in the background."""
        with self._native_bridge_probe_lock:
            if self._native_bridge_probe_started:
                return
            self._native_bridge_probe_started = True
            if _looks_like_imaris_application(self.imaris):
                self._native_bridge_available = True
                self._native_bridge_last_verified_at = time.time()
                self._native_bridge_probe_done.set()
                _xt_debug("Native bridge probe skipped: current Imaris handle is live")
                return

        threading.Thread(target=self._native_bridge_probe_worker, daemon=True).start()

    def _native_bridge_probe_worker(self):
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
                self._native_bridge_probe_done.set()

    def _revalidate_native_bridge(self):
        """Synchronously verify that the cached native bridge still resolves Imaris."""
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
        """Return True only when the final open can use a native Imaris bridge."""
        if _looks_like_imaris_application(self.imaris):
            return True
        self._start_native_bridge_probe()
        self._set_status("Checking Imaris same-session open support...", "#fff3cd")
        if not self._native_bridge_probe_done.wait(timeout=NATIVE_BRIDGE_PROBE_TIMEOUT):
            _xt_debug("Native bridge probe timed out before export")
            return False
        with self._native_bridge_probe_lock:
            available = self._native_bridge_available
            bridge_error = self._native_bridge_probe_error
            last_verified_at = self._native_bridge_last_verified_at
        if not available:
            _xt_debug(
                "Imaris same-session open bridge is unavailable before export: "
                f"{bridge_error}"
            )
            return False
        if time.time() - last_verified_at <= NATIVE_BRIDGE_REVALIDATE_AFTER:
            return True
        if self._revalidate_native_bridge():
            return True
        with self._native_bridge_probe_lock:
            bridge_error = self._native_bridge_probe_error
        _xt_debug(
            "Imaris same-session open bridge failed revalidation before export: "
            f"{bridge_error}"
        )
        return False

    def _connect(self):
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
        self._set_folder_import_capability(False, "Detecting OMERO folder import...")

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

        scheme = "https" if self.https_var.get() else "http"
        self.client = OMEROWebClient(h, port, u, pw, scheme=scheme)

        try:
            if self.client.connect():
                self._connected = True
                self._set_connect_button(
                    "Disconnect",
                    _tk_constant("NORMAL", "normal"),
                    "#f39c12",
                    active_bg="#d68910",
                )
                self._set_status("Connected to OMERO", "#d4edda")
                self._load_projects()
                self._set_status("Detecting connector capabilities...", "#fff3cd")
                converter_options = self._detect_converter_options_after_connection()
                folder_import_capability = self._detect_folder_import_after_connection()
                self._set_converter_options(converter_options)
                self._set_folder_import_capability(
                    folder_import_capability.get("available"),
                    folder_import_capability.get("reason", ""),
                )
                if converter_options or folder_import_capability.get("available"):
                    self._set_status("Connected to OMERO", "#d4edda")
                else:
                    self._set_status(
                        "Connected, but no supported connector workflow is available",
                        "#f8d7da",
                    )
            else:
                self._connected = False
                self.client.password = ""
                self.client.csrf_token = None
                self.client.session_id = None
                self.client.session_key = None
                self.client = None
                self._set_folder_import_capability(False, "Connect to OMERO first.")
                self._set_connect_button(
                    "Connect",
                    _tk_constant("NORMAL", "normal"),
                    "#3498db",
                    active_bg="#2f85c7",
                )
                self._set_status("Connection failed", "#f8d7da")
                messagebox.showerror(
                    "Connection Failed",
                    "Cannot connect to OMERO server.\nPlease check your credentials.",
                )
        finally:
            self._connection_in_progress = False

    def _load_projects(self):
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
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._did = None
        self.images_data = []
        self.datasets_data = self.client.list_datasets(self._pid)
        for d in self.datasets_data:
            self.dlist.insert(_tk_constant("END", "end"), self._dataset_list_label(d))

    def _load_imgs(self, did):
        self.ilist.delete(0, _tk_constant("END", "end"))
        self._did = did
        self.images_data = self.client.list_images(did)
        self._image_selection_anchor = None
        for img in self.images_data:
            self.ilist.insert(_tk_constant("END", "end"), self._image_list_label(img))

    @classmethod
    def _project_list_label(cls, project):
        if isinstance(project, dict):
            project_id = cls._entity_id(project)
            return project.get("name") or (
                f"Project {project_id}" if project_id is not None else "Project"
            )
        return "Project"

    @classmethod
    def _dataset_list_label(cls, dataset):
        if isinstance(dataset, dict):
            dataset_id = cls._entity_id(dataset)
            return dataset.get("name") or (
                f"Dataset {dataset_id}" if dataset_id is not None else "Dataset"
            )
        return "Dataset"

    @classmethod
    def _image_list_label(cls, image):
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
        if entity_id is None:
            return None
        target = str(entity_id)
        for index, entity in enumerate(list(entities or [])):
            if cls._entity_id(entity) == target:
                return index
        return None

    @staticmethod
    def _clear_listbox_selection(listbox):
        selection_clear = getattr(listbox, "selection_clear", None)
        if callable(selection_clear):
            selection_clear(0, _tk_constant("END", "end"))

    @classmethod
    def _select_listbox_index(cls, listbox, index):
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
        listbox.delete(0, _tk_constant("END", "end"))
        for label in labels:
            listbox.insert(_tk_constant("END", "end"), label)

    def _configure_image_selection_bindings(self):
        self.ilist.bind("<Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind("<Control-Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind("<Shift-Button-1>", self._on_image_listbox_click, add="+")
        self.ilist.bind(
            "<Control-Shift-Button-1>",
            self._on_image_listbox_click,
            add="+",
        )

    @staticmethod
    def _listbox_size(listbox):
        size_getter = getattr(listbox, "size", None)
        if callable(size_getter):
            try:
                return int(size_getter())
            except Exception:
                return 0
        return 0

    @staticmethod
    def _set_listbox_anchor(listbox, index):
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

    def _on_image_listbox_click(self, event):
        listbox = getattr(event, "widget", None)
        if listbox is not self.ilist:
            return None

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
            return "break"

        if ctrl_pressed:
            if index in current_selection:
                listbox.selection_clear(index)
            else:
                listbox.selection_set(index)
            self._image_selection_anchor = index
            self._set_listbox_anchor(listbox, index)
            listbox.see(index)
            return "break"

        self._clear_listbox_selection(listbox)
        listbox.selection_set(index)
        self._image_selection_anchor = index
        self._set_listbox_anchor(listbox, index)
        listbox.see(index)
        return "break"

    def _current_selected_project_id(self):
        for raw_index in self.plist.curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.projects_data):
                return self._entity_id(self.projects_data[index])
        return str(self._pid) if self._pid is not None else None

    def _current_selected_dataset_id(self):
        for raw_index in self.dlist.curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.datasets_data):
                return self._entity_id(self.datasets_data[index])
        return str(self._did) if self._did is not None else None

    def _set_refresh_button_state(self, state):
        refresh_btn = getattr(self, "refresh_btn", None)
        if refresh_btn is not None:
            refresh_btn.config(state=state)

    def _set_import_button_state(self, state):
        import_btn = getattr(self, "import_btn", None)
        if import_btn is not None:
            import_btn.config(state=state)

    def _update_import_button_state(self):
        enabled = (
            getattr(self, "_connected", False)
            and getattr(self, "_folder_import_available", False)
            and not getattr(self, "_connection_in_progress", False)
            and not getattr(self, "_refresh_in_progress", False)
            and not getattr(self, "_import_in_progress", False)
        )
        self._set_import_button_state(
            _tk_constant("NORMAL", "normal")
            if enabled
            else _tk_constant("DISABLED", "disabled")
        )

    def _set_folder_import_capability(self, available, reason=""):
        self._folder_import_available = bool(available)
        self._folder_import_reason = str(reason or "").strip()
        self._update_import_button_state()

    def _set_load_button_for_converter(self):
        converter_value = _stringvar_value(getattr(self, "converter_var", None))
        state = (
            _tk_constant("NORMAL", "normal")
            if (
                converter_value in {"OMERO", "Imaris"}
                and not getattr(self, "_import_in_progress", False)
            )
            else _tk_constant("DISABLED", "disabled")
        )
        self.load_btn.config(state=state)

    def _set_actions_busy_for_import(self, active):
        self._import_in_progress = bool(active)
        disabled = _tk_constant("DISABLED", "disabled")
        if active:
            self.load_btn.config(state=disabled)
            self._set_import_button_state(disabled)
            self._set_refresh_button_state(disabled)
            self.connect_btn.config(state=disabled)
            return

        if self._connected:
            self._set_connect_button(
                "Disconnect",
                _tk_constant("NORMAL", "normal"),
                "#f39c12",
                active_bg="#d68910",
            )
        else:
            self._set_connect_button(
                "Connect",
                _tk_constant("NORMAL", "normal"),
                "#3498db",
                active_bg="#2f85c7",
            )
        self._set_load_button_for_converter()
        self._update_import_button_state()
        if self._connected and _stringvar_value(
            getattr(self, "converter_var", None)
        ) in {
            "OMERO",
            "Imaris",
        }:
            self._set_refresh_button_state(_tk_constant("NORMAL", "normal"))

    def _clear_actions_busy_for_import(self):
        self._set_actions_busy_for_import(False)

    def _refresh_browser(self):
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
        self.load_btn.config(state=_tk_constant("DISABLED", "disabled"))
        self._set_import_button_state(_tk_constant("DISABLED", "disabled"))
        self._set_status("Refreshing OMERO browser...", "#fff3cd")
        threading.Thread(
            target=self._refresh_worker,
            args=(project_id, dataset_id, generation),
            daemon=True,
        ).start()

    def _refresh_worker(self, project_id, dataset_id, generation):
        try:
            projects = self.client.list_projects()
            project_index = self._find_entity_index(projects, project_id)
            datasets = []
            dataset_index = None
            images = []

            if project_index is not None:
                refreshed_project_id = self._entity_id(projects[project_index])
                datasets = self.client.list_datasets(refreshed_project_id)
                dataset_index = self._find_entity_index(datasets, dataset_id)
                if dataset_index is not None:
                    refreshed_dataset_id = self._entity_id(datasets[dataset_index])
                    images = self.client.list_images(refreshed_dataset_id)

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
            if requested_project_id is None:
                self._set_status("Project list refreshed", "#d4edda")
            else:
                self._set_status(
                    "Selected project is no longer available; projects refreshed",
                    "#fff3cd",
                )
            self._finish_refresh_buttons()
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
            if requested_dataset_id is None:
                self._set_status("Datasets refreshed", "#d4edda")
            else:
                self._set_status(
                    "Selected dataset is no longer available; datasets refreshed",
                    "#fff3cd",
                )
            self._finish_refresh_buttons()
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
        self._set_status("OMERO browser refreshed", "#d4edda")
        self._finish_refresh_buttons()

    def _finish_refresh_error(self, generation, refresh_error):
        if generation != self._refresh_generation:
            return
        self._set_status("Refresh failed", "#f8d7da")
        self._show_error("Refresh Failed", str(refresh_error))
        _xt_debug(f"Refresh failed: {type(refresh_error).__name__}: {refresh_error}")
        self._finish_refresh_buttons()

    def _finish_refresh_buttons(self):
        self._refresh_in_progress = False
        self._set_refresh_button_state(
            _tk_constant("NORMAL", "normal")
            if self._connected
            and _stringvar_value(getattr(self, "converter_var", None))
            in {"OMERO", "Imaris"}
            and not getattr(self, "_import_in_progress", False)
            else _tk_constant("DISABLED", "disabled")
        )
        self._set_load_button_for_converter()
        self._update_import_button_state()

    @staticmethod
    def _image_cache_subdir(image_id):
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(image_id)).strip(" .")
        if not safe_id:
            safe_id = "unknown"
        if safe_id.upper() in _WINDOWS_RESERVED_FILENAMES:
            safe_id = f"_{safe_id}"
        return f"img_{safe_id[:80]}"

    @staticmethod
    def _image_display_name(img):
        if isinstance(img, dict):
            name = img.get("name")
            if name:
                return str(name)
            image_id = img.get("id")
            if image_id is not None:
                return f"Image {image_id}"
        return "selected image"

    def _selected_images(self):
        selected = []
        for raw_index in self.ilist.curselection():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.images_data):
                selected.append(self.images_data[index])
        return selected

    def _load(self):
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

        self.load_btn.config(state=_tk_constant("DISABLED", "disabled"))
        threading.Thread(
            target=worker_target,
            args=worker_args,
            daemon=True,
        ).start()

    def _reenable_load_button(self):
        self.load_btn.config(state=_tk_constant("NORMAL", "normal"))

    def _load_worker(self, img, converter):
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
            else:
                raise RuntimeError(failure_message)

        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            _xt_debug(f"Load worker failed: {type(e).__name__}: {e}")
        finally:
            self._invoke_on_ui_thread(self._reenable_load_button, wait=False)

    def _load_multiple_worker(self, images, converter):
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
            else:
                raise RuntimeError(failure_message)

        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            _xt_debug(f"Multi-image load worker failed: {type(e).__name__}: {e}")
        finally:
            self._invoke_on_ui_thread(self._reenable_load_button, wait=False)

    def show(self):
        self.root.mainloop()


# =============================================================================
# XTENSION ENTRY POINT
# =============================================================================


def _xt_log_path():
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    except Exception:
        ts = "unknown"
    return str(Path(tempfile.gettempdir()) / f"XTOmeroConnector_{ts}.log")


def _xt_write_log(log_path, msg):
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
    try:
        messagebox.showerror(title, message)
    except Exception:
        print(title + ": " + message)


def XTOmeroConnector(aImarisId):
    """Called by Imaris."""
    _set_process_window_title("OMERO Connector")
    log_path = _xt_log_path()
    global _XT_LOG_PATH
    _XT_LOG_PATH = log_path
    try:
        _xt_write_log(log_path, "=== XTOmeroConnector starting ===")
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
            # When run outside Imaris (manual debug), aImarisId may be None or already an app object.
            vImaris = aImarisId if _looks_like_imaris_application(aImarisId) else None

        if vImaris is None:
            _xt_write_log(
                log_path,
                f"Imaris handle resolution returned None for entrypoint={aImarisId!r}",
            )
        else:
            _xt_write_log(
                log_path,
                f"Resolved Imaris handle type={type(vImaris).__name__} for entrypoint={aImarisId!r}",
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
