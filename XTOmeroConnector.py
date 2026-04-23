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
import tkinter as tk
from tkinter import messagebox
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
from pathlib import Path
from typing import Any, List, Optional

# Default timeout/poll values for client-side export polling.
# These must NOT depend on server-side packages (omero_plugin_common)
# because this script runs inside Imaris on the user's machine.
EXPORT_TIMEOUT = 3600  # seconds
EXPORT_POLL_INTERVAL = 2.0  # seconds
IMARIS_HANDLE_RETRY_ATTEMPTS = 10
IMARIS_HANDLE_RETRY_INTERVAL = 0.25
NATIVE_BRIDGE_RUNNER_TIMEOUT = 600
NATIVE_BRIDGE_PROBE_TIMEOUT = 60
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
                    pass
            added.append(normalized)
    os.environ["PATH"] = os.pathsep.join(path_parts)
    return added


def _get_imaris_application(app_id, retries, retry_interval):
    import ImarisLib

    attempts = max(1, int(retries or 1))
    for attempt in range(attempts):
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

        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(retry_interval)))

    return None


def _open_file_in_imaris(file_path, app):
    for method_name, args in (
        ("FileOpen", (file_path, "")),
        ("FileOpen", (file_path,)),
        ("OpenFile", (file_path,)),
        ("LoadFile", (file_path,)),
    ):
        method = getattr(app, method_name, None)
        if not callable(method):
            continue
        method(*args)
        return True
    return False


def _has_open_method(app):
    for method_name in ("FileOpen", "OpenFile", "LoadFile"):
        if callable(getattr(app, method_name, None)):
            return True
    return False


def main():
    payload = json.loads(sys.stdin.read())
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
    file_path = os.fspath(payload["file_path"])
    require_ims = bool(payload.get("require_ims", True))
    if not os.path.isfile(file_path):
        print("BRIDGE_RUNNER_MISSING_FILE")
        return 64
    if require_ims and not _is_ims_file(file_path):
        print("BRIDGE_RUNNER_INVALID_IMS")
        return 64
    if not _open_file_in_imaris(file_path, app):
        print("BRIDGE_RUNNER_OPEN_FAILED")
        return 3
    print("BRIDGE_RUNNER_OPENED")
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


def _xt_debug(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
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


def open_file_in_imaris(file_path, imaris_app, require_ims=True):
    """Attempt to open a file in Imaris using available API methods."""
    candidate = _existing_regular_file_path(file_path)
    if candidate is None:
        print("Imaris open failed: file does not exist.")
        return False
    if require_ims and not is_ims_file(candidate):
        print("Imaris open failed: file is not a valid IMS file.")
        return False

    if imaris_app is None:
        print("Imaris application handle is not available.")
        return False

    last_error = None
    file_path_text = str(candidate)
    candidates = [
        ("FileOpen", (file_path_text, "")),
        ("FileOpen", (file_path_text,)),
        ("OpenFile", (file_path_text,)),
        ("LoadFile", (file_path_text,)),
    ]
    for method_name, args in candidates:
        method = getattr(imaris_app, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            return True
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        print(f"Imaris open failed: {last_error}")
    else:
        print("Imaris open failed: no supported API method found.")
    return False


def _looks_like_imaris_application(candidate):
    """Return True when the object looks like a live Imaris application handle."""
    if candidate is None:
        return False
    for method_name in ("FileOpen", "OpenFile", "LoadFile"):
        if callable(getattr(candidate, method_name, None)):
            return True
    return False


def _tk_constant(name, fallback):
    return getattr(tk, name, fallback)


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
        os.environ.get("ProgramW6432", r"C:\Program Files"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
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
                yield from _yield_candidate(candidate)


def _find_imaris_executable():
    """Return a launchable Imaris.exe path if present."""
    if os.name != "nt":
        return None
    for candidate in _iter_imaris_executable_candidates():
        if os.path.isfile(candidate):
            return candidate
    return None


def _iter_imaris_install_roots():
    """Yield plausible Imaris installation roots."""
    seen = set()

    env_root = os.environ.get("IMARIS_HOME", "").strip()
    if env_root:
        normalized = os.path.normpath(env_root)
        if normalized not in seen:
            seen.add(normalized)
            yield normalized

    exe_path = _find_imaris_executable()
    if exe_path:
        install_root = os.path.dirname(exe_path)
        normalized = os.path.normpath(install_root)
        if normalized not in seen:
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


def _native_bridge_payload(imaris_id, mode, file_path=None, require_ims=True):
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
    }
    if file_path is not None:
        payload["file_path"] = str(file_path)
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
        _xt_debug(f"Native bridge runner ({context}) stdout: {stdout[:4000]}")
    if stderr:
        _xt_debug(f"Native bridge runner ({context}) stderr: {stderr[:4000]}")
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
                "Imaris XT bridge import failed: "
                f"{exc}. Current Python={version_info}. "
                "The live Imaris session handle is unavailable, so same-session open cannot work."
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
                _xt_debug(f"Extracted sessionid: {cookie.value[:8]}...")
            elif cookie.name == "csrftoken":
                self.csrf_token = cookie.value
                _xt_debug(f"Extracted csrftoken: {cookie.value[:8]}...")

    @staticmethod
    def _check_login_redirect(response, context="request"):
        """Check if a response was redirected to login page.

        Returns True if redirected to login (authentication failed).
        """
        final_url = getattr(response, "geturl", lambda: "")()
        if "/webclient/login/" in str(final_url):
            _xt_debug(
                f"Authentication failed during {context}: redirected to {final_url}"
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
            _xt_debug(f"Connecting to OMERO.web login url={login_url}")

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
                _xt_debug(f"Login POST final url={post_url}")

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

            _xt_debug(
                f"Login succeeded; session cookie received (sessionid={self.session_id[:8]}...)"
            )
            return True

        except urllib.error.HTTPError as e:
            _xt_debug(f"Login HTTP error {e.code}: {e.reason}")
            return False
        except urllib.error.URLError as e:
            _xt_debug(f"Login URL error: {e}")
            return False
        except Exception as e:
            _xt_debug(f"Connection error: {e}")
            import traceback

            _xt_debug(traceback.format_exc())
            return False

    def _api_request(self, endpoint):
        """Make API request with explicit cookie handling."""
        if not self.session_id:
            _xt_debug("API request skipped: no session")
            return None

        url = f"{self.api_url}/{endpoint}"
        _xt_debug(f"API GET url={url}")

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
                f"API POST url={url} response={getattr(response, 'status', 'unknown')}"
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
                _xt_debug(e.read().decode("utf-8"))
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            return None
        except Exception as e:
            _xt_debug(f"API POST error: {e}")
            return None

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
        _xt_debug(f"Checking OMERO IMS export capability: {capability_url}")
        req = self._create_request_with_cookies(capability_url)
        try:
            with self.opener.open(req, timeout=30) as response:
                if self._check_login_redirect(response, "IMS export capability check"):
                    return False
                raw_body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw_body)
        except Exception as exc:
            _xt_debug(f"OMERO IMS export capability unavailable: {exc}")
            return False
        if not isinstance(payload, dict):
            _xt_debug("OMERO IMS export capability returned non-object JSON")
            return False
        available = bool(payload.get("omero_ims_export"))
        _xt_debug(f"OMERO IMS export capability available={available}")
        return available

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
            download_dir = os.path.join(
                os.path.expanduser("~"), "Downloads", "OMERO_Imaris_Exports"
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

        export_url = f"{base}/omeroweb_imaris_connector/imaris-export/?{urllib.parse.urlencode(query_params)}"
        _xt_debug(f"Requesting IMS export from: {export_url}")

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
                    snippet = raw_body[:2000].strip()
                    raise RuntimeError(
                        "IMS export failed: server returned a non-JSON response. "
                        "Please verify the OMERO.web Imaris connector is healthy.\n\n"
                        f"Response preview:\n{snippet}"
                    ) from exc

                job_id = payload.get("job_id")
                status_url = payload.get("status_url")
                if not job_id or not status_url:
                    raise RuntimeError(f"Unexpected response from server: {payload}")

                status_url = self._normalize_url(status_url, base)
                _xt_debug(f"IMS export started job_id={job_id} status_url={status_url}")

            # Poll for completion
            deadline = time.time() + EXPORT_TIMEOUT
            download_url = None
            last_state = None
            poll_count = 0
            reauth_attempted = False

            while time.time() < deadline:
                poll_count += 1
                _xt_debug(f"IMS export poll #{poll_count} url={status_url}")

                # Create poll request with explicit cookies
                poll_req = self._create_request_with_cookies(status_url)

                try:
                    with self.opener.open(poll_req, timeout=30) as poll_response:
                        if self._check_login_redirect(poll_response, "IMS export poll"):
                            # Try to re-extract cookies in case they were updated
                            self._extract_cookies_from_jar()
                            _xt_debug(
                                "Session state after redirect: "
                                f"sessionid={self.session_id[:8] if self.session_id else 'None'}..."
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
                            snippet = poll_body[:2000].strip()
                            raise RuntimeError(
                                "IMS export poll failed: server returned a non-JSON response. "
                                "Please verify the OMERO.web Imaris connector is healthy.\n\n"
                                f"Response preview:\n{snippet}"
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
                _xt_debug(f"IMS export poll state={last_state} payload={poll_payload}")

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
            _xt_debug(f"Downloading IMS from: {download_url}")
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
                chunk_size = 1024 * 1024  # 1MB

                _xt_debug(f"Downloading to: {local_path}")
                with open(local_path, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            print(
                                f"  Progress: {percent:.1f}% ({downloaded / (1024 * 1024):.1f} MB)",
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

            _xt_debug(f"IMS export downloaded OK: {local_path}")
            return local_path

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            raise RuntimeError(
                f"IMS export HTTPError {e.code}: {e.reason}\n{body[:2000]}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"IMS export failed (URLError): {e}") from e

    def download_original_file(
        self,
        image_id,
        download_dir,
        fallback_name="original",
    ):
        """Download the archived original file for local Imaris conversion."""
        if download_dir is None:
            download_dir = os.path.join(
                os.path.expanduser("~"), "Downloads", "OMERO_Imaris_Originals"
            )
        if not self.session_id:
            raise RuntimeError("Not logged in to OMERO.web (missing session key).")

        base = self.base_url.rstrip("/")
        download_url = f"{base}/webgateway/archived_files/download/{int(image_id)}/"
        _xt_debug(f"Requesting original file download from: {download_url}")
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
                chunk_size = 1024 * 1024

                _xt_debug(f"Downloading original file to: {local_path}")
                with open(local_path, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = (downloaded / total_size) * 100.0
                            print(
                                f"  Progress: {percent:.1f}% ({downloaded / (1024 * 1024):.1f} MB)",
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

            _xt_debug(f"Original file downloaded OK: {local_path}")
            return local_path
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in XTOmeroConnector.py",
                    exc_info=exc,
                )
            raise RuntimeError(
                f"Original file download HTTPError {e.code}: {e.reason}\n{body[:2000]}"
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
                _xt_debug(f"Normalized URL: {url} -> {rebuilt}")
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
        self._native_bridge_probe_lock = threading.Lock()
        self._native_bridge_probe_done = threading.Event()
        self._native_bridge_probe_started = False
        self._native_bridge_available = _looks_like_imaris_application(self.imaris)
        self._native_bridge_python_executable = None
        self._native_bridge_probe_error = ""

        # Get export directory
        self.export_dir = self._get_export_dir()

        self.root = tk.Tk()
        self.root.title("OMERO Connector")
        self.root.geometry("1000x700")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._start_native_bridge_probe()

    def _on_close(self):
        """Handle window close - don't delete temp files as Imaris might still be using them."""
        self.root.destroy()

    def _build_ui(self):
        # Connection frame
        conn_frame = tk.LabelFrame(self.root, text="OMERO Connection", padx=10, pady=10)
        conn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.host_entry = tk.Entry(conn_frame, width=25)
        self.host_entry.insert(0, "172.23.208.90")
        self.host_entry.grid(row=0, column=1, pady=5, padx=5)

        tk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky=tk.W, pady=5)
        self.port_entry = tk.Entry(conn_frame, width=8)
        self.port_entry.insert(0, "4090")
        self.port_entry.grid(row=0, column=3, pady=5, padx=5)

        self.https_var = tk.BooleanVar(value=False)
        tk.Checkbutton(conn_frame, text="Use HTTPS", variable=self.https_var).grid(
            row=0, column=4, pady=5, padx=5
        )

        tk.Label(conn_frame, text="Username:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.user_entry = tk.Entry(conn_frame, width=25)
        self.user_entry.insert(0, "test")
        self.user_entry.grid(row=1, column=1, pady=5, padx=5)

        tk.Label(conn_frame, text="Password:").grid(
            row=1, column=2, sticky=tk.W, pady=5
        )
        self.pass_entry = tk.Entry(conn_frame, show="*", width=25)
        self.pass_entry.grid(row=1, column=3, columnspan=2, pady=5, padx=5, sticky=tk.W)

        tk.Button(
            conn_frame,
            text="Connect",
            command=self._connect,
            bg="#3498db",
            fg="white",
            font=("Arial", 10, "bold"),
            width=15,
        ).grid(row=0, column=5, rowspan=2, padx=10, pady=5)

        # Browser
        browser = tk.Frame(self.root)
        browser.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Projects
        p_frame = tk.LabelFrame(browser, text="Projects")
        p_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        p_scroll = tk.Scrollbar(p_frame)
        p_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.plist = tk.Listbox(
            p_frame, yscrollcommand=p_scroll.set, exportselection=False
        )
        self.plist.pack(fill=tk.BOTH, expand=True)
        p_scroll.config(command=self.plist.yview)
        self.plist.bind("<<ListboxSelect>>", lambda e: self._sel_proj())

        # Datasets
        d_frame = tk.LabelFrame(browser, text="Datasets")
        d_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        d_scroll = tk.Scrollbar(d_frame)
        d_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.dlist = tk.Listbox(
            d_frame, yscrollcommand=d_scroll.set, exportselection=False
        )
        self.dlist.pack(fill=tk.BOTH, expand=True)
        d_scroll.config(command=self.dlist.yview)
        self.dlist.bind("<<ListboxSelect>>", lambda e: self._sel_ds())

        # Images
        i_frame = tk.LabelFrame(browser, text="Images")
        i_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        i_scroll = tk.Scrollbar(i_frame)
        i_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.ilist = tk.Listbox(
            i_frame, yscrollcommand=i_scroll.set, exportselection=False
        )
        self.ilist.pack(fill=tk.BOTH, expand=True)
        i_scroll.config(command=self.ilist.yview)

        # Actions
        actions = tk.Frame(self.root)
        actions.pack(fill=tk.X, padx=10, pady=10)

        self.converter_var = tk.StringVar(value="")
        self.converter_frame = tk.Frame(actions)
        tk.Label(self.converter_frame, text="Converter:").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self.converter_menu = tk.OptionMenu(
            self.converter_frame, self.converter_var, ""
        )
        self.converter_menu.config(width=10)
        self.converter_menu.pack(side=tk.LEFT)

        self.load_btn = tk.Button(
            actions,
            text="Load into Imaris",
            command=self._load,
            bg="#27ae60",
            fg="white",
            font=("Arial", 12, "bold"),
            state=_tk_constant("DISABLED", "disabled"),
            height=2,
        )
        self.load_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        tk.Button(
            actions,
            text="Close",
            command=self._on_close,
            bg="#95a5a6",
            fg="white",
            font=("Arial", 12, "bold"),
            height=2,
        ).pack(side=tk.LEFT, padx=2)

        # Status
        self.status = tk.Label(
            self.root,
            text="Ready - Please connect to OMERO",
            bg="#ecf0f1",
            anchor=tk.W,
            padx=10,
            pady=5,
            font=("Arial", 9),
        )
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _set_converter_options(self, options):
        options = list(options or [])
        menu = self.converter_menu["menu"]
        menu.delete(0, _tk_constant("END", "end"))
        if not options:
            self.converter_var.set("")
            self.converter_frame.pack_forget()
            self.load_btn.config(state=_tk_constant("DISABLED", "disabled"))
            return

        for option in options:
            menu.add_command(
                label=option,
                command=lambda value=option: self.converter_var.set(value),
            )
        self.converter_var.set(options[0])
        self.converter_frame.pack(
            side=tk.LEFT,
            padx=(0, 8),
            before=self.load_btn,
        )
        self.load_btn.config(state=_tk_constant("NORMAL", "normal"))

    def _detect_converter_options_after_connection(self):
        """Populate converter options only after login and native-open checks."""
        self._start_native_bridge_probe()
        if not self._native_bridge_probe_done.wait(timeout=NATIVE_BRIDGE_PROBE_TIMEOUT):
            _xt_debug("Native bridge probe timed out during converter detection")
            return []
        with self._native_bridge_probe_lock:
            native_available = self._native_bridge_available
            bridge_error = self._native_bridge_probe_error
        if not native_available:
            _xt_debug(
                f"No converter options: native bridge unavailable: {bridge_error}"
            )
            return []

        options = ["Imaris"]
        if self.client and self.client.has_omero_ims_export_capability():
            options.insert(0, "OMERO")
        _xt_debug(f"Detected converter options after connection: {options}")
        return options

    @staticmethod
    def _get_export_dir():
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        if os.path.isdir(desktop):
            base = desktop
        else:
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

    def _open_downloaded_file_in_imaris(self, downloaded_file, require_ims=True):
        """Resolve the Imaris handle on the UI thread and open the file."""
        self._set_status("Opening file in Imaris...", "#fff3cd")

        if self.imaris is None:
            _xt_debug(
                "Imaris handle missing before open; attempting UI-thread re-acquisition"
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
                "Imaris handle is still unavailable after re-acquisition attempts"
            )
        else:
            _xt_debug(
                f"Using Imaris handle type={type(self.imaris).__name__} for file open"
            )

        if open_file_in_imaris(downloaded_file, self.imaris, require_ims=require_ims):
            return True

        _xt_debug(
            "Current Python could not open through the live handle; "
            "trying compatible native bridge runner"
        )
        with self._native_bridge_probe_lock:
            bridge_python = self._native_bridge_python_executable
        return _open_file_in_imaris_with_native_bridge_runner(
            downloaded_file,
            self.imaris_id,
            preferred_python_executable=bridge_python,
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
                self._native_bridge_probe_done.set()
                _xt_debug("Native bridge probe skipped: current Imaris handle is live")
                return

        threading.Thread(target=self._native_bridge_probe_worker, daemon=True).start()

    def _native_bridge_probe_worker(self):
        bridge_python = None
        bridge_error = ""
        try:
            if _coerce_imaris_id(self.imaris_id) is None:
                bridge_error = "No numeric Imaris application id was provided."
            else:
                bridge_python = _find_compatible_native_bridge_python(self.imaris_id)
                if bridge_python:
                    _xt_debug(
                        f"Native bridge probe found compatible Python: {bridge_python}"
                    )
                else:
                    bridge_error = (
                        "No installed Python listed by the Windows launcher could "
                        "load ImarisLib/IcePy for the live Imaris application."
                    )
        except Exception as exc:
            bridge_error = str(exc)
            _xt_debug(f"Native bridge probe failed: {exc}")
        finally:
            with self._native_bridge_probe_lock:
                self._native_bridge_python_executable = bridge_python
                self._native_bridge_available = bool(bridge_python)
                self._native_bridge_probe_error = bridge_error
                self._native_bridge_probe_done.set()

    def _ensure_native_open_ready_before_export(self):
        """Return True only when the final open can use a native Imaris bridge."""
        if _looks_like_imaris_application(self.imaris):
            return True
        self._start_native_bridge_probe()
        self._set_status("Checking native Imaris bridge...", "#fff3cd")
        if not self._native_bridge_probe_done.wait(timeout=NATIVE_BRIDGE_PROBE_TIMEOUT):
            _xt_debug("Native bridge probe timed out before export")
            return False
        with self._native_bridge_probe_lock:
            available = self._native_bridge_available
            bridge_error = self._native_bridge_probe_error
        if not available:
            _xt_debug(f"Native bridge is unavailable before export: {bridge_error}")
        return available

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

        port = _parse_port(p)
        if port is None:
            messagebox.showerror(
                "Invalid Port",
                "Please enter a valid numeric port (1-65535) for the OMERO.web server.",
            )
            return

        self._set_status("Connecting to OMERO...", "#fff3cd")

        scheme = "https" if self.https_var.get() else "http"
        self.client = OMEROWebClient(h, port, u, pw, scheme=scheme)

        if self.client.connect():
            self._set_status(f"✓ Connected to {h}:{p} as {u}", "#d4edda")
            self._load_projects()
            self._set_status("Detecting converter capabilities...", "#fff3cd")
            converter_options = self._detect_converter_options_after_connection()
            self._set_converter_options(converter_options)
            if converter_options:
                self._set_status(f"✓ Connected to {h}:{p} as {u}", "#d4edda")
            else:
                self._set_status(
                    "Connected, but no native Imaris converter path is available",
                    "#f8d7da",
                )
        else:
            self._set_status("✗ Connection failed", "#f8d7da")
            messagebox.showerror(
                "Connection Failed",
                "Cannot connect to OMERO server.\nPlease check your credentials.",
            )

    def _load_projects(self):
        self.plist.delete(0, _tk_constant("END", "end"))
        self.projects_data = self.client.list_projects()
        for p in self.projects_data:
            self.plist.insert(_tk_constant("END", "end"), p["name"])

    def _sel_proj(self):
        sel = self.plist.curselection()
        if not sel:
            return
        p = self.projects_data[sel[0]]
        if self._pid != p["id"]:
            self._pid = p["id"]
            self._load_ds()

    def _sel_ds(self):
        sel = self.dlist.curselection()
        if not sel:
            return
        d = self.datasets_data[sel[0]]
        self._load_imgs(d["id"])

    def _load_ds(self):
        self.dlist.delete(0, _tk_constant("END", "end"))
        self.ilist.delete(0, _tk_constant("END", "end"))
        self.datasets_data = self.client.list_datasets(self._pid)
        for d in self.datasets_data:
            self.dlist.insert(_tk_constant("END", "end"), d["name"])

    def _load_imgs(self, did):
        self.ilist.delete(0, _tk_constant("END", "end"))
        self.images_data = self.client.list_images(did)
        for img in self.images_data:
            size_info = f"{img['sizeX']}×{img['sizeY']}×{img['sizeZ']}"
            if img["sizeC"] > 1:
                size_info += f" C{img['sizeC']}"
            if img["sizeT"] > 1:
                size_info += f" T{img['sizeT']}"
            self.ilist.insert(
                _tk_constant("END", "end"), f"{img['name']} [{size_info}]"
            )

    def _load(self):
        sel = self.ilist.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select an image")
            return

        img = self.images_data[sel[0]]
        converter = self.converter_var.get()
        if converter not in {"OMERO", "Imaris"}:
            messagebox.showwarning(
                "No Converter",
                "Please connect to OMERO and select an available converter.",
            )
            return

        if not messagebox.askyesno(
            "Confirm Load",
            f"Download and open:\n{img['name']}\n\nConverter: {converter}",
        ):
            return

        self.load_btn.config(state=_tk_constant("DISABLED", "disabled"))
        threading.Thread(
            target=self._load_worker,
            args=(img, converter),
            daemon=True,
        ).start()

    def _reenable_load_button(self):
        self.load_btn.config(state=_tk_constant("NORMAL", "normal"))

    def _load_worker(self, img, converter):
        try:
            _xt_debug(
                f"Load worker starting image_id={img['id']} "
                f"name={img['name']} converter={converter}"
            )
            if not self._ensure_native_open_ready_before_export():
                raise RuntimeError(
                    "Cannot open files in the running Imaris session because the native "
                    "Imaris XT bridge is unavailable. Download/conversion was not started."
                )

            # Download directory
            download_dir = os.path.join(self.export_dir, f"img_{img['id']}")
            os.makedirs(download_dir, exist_ok=True)

            require_ims = converter == "OMERO"
            if converter == "OMERO":
                self._set_status(f"Exporting IMS for {img['name']}...", "#fff3cd")
                self._set_status("Running server-side IMS export...", "#fff3cd")
                downloaded_file = self.client.download_ims_export(
                    img["id"],
                    download_dir,
                    fallback_name=f"img_{img['id']}.ims",
                )
            elif converter == "Imaris":
                self._set_status(
                    f"Downloading original file for {img['name']}...", "#fff3cd"
                )
                downloaded_file = self.client.download_original_file(
                    img["id"],
                    download_dir,
                    fallback_name=img.get("name") or f"img_{img['id']}",
                )
            else:
                raise RuntimeError(f"Unsupported converter: {converter}")

            if not downloaded_file or not os.path.exists(downloaded_file):
                raise RuntimeError("Failed to download file from OMERO.")

            if require_ims and not is_ims_file(downloaded_file):
                raise RuntimeError(
                    "Downloaded file is not a valid IMS (HDF5) file. "
                    "Refusing to open to avoid triggering Imaris File Converter. "
                    "Please verify that the server-side conversion completed successfully."
                )

            self._set_status(
                f"Downloaded: {os.path.basename(downloaded_file)}", "#d4edda"
            )
            _xt_debug(f"Downloaded: {downloaded_file}")

            self.temp_files.append(downloaded_file)

            # Open in Imaris on the UI thread so the XT handle stays in the
            # same thread/apartment as the original dialog.
            success = self._invoke_on_ui_thread(
                lambda: self._open_downloaded_file_in_imaris(
                    downloaded_file,
                    require_ims=require_ims,
                )
            )

            if success:
                self._set_status("✓ Opened in Imaris", "#d4edda")
                self._show_info(
                    "Success",
                    f"File opened in Imaris!\nOpened file: {downloaded_file}",
                )
            else:
                raise RuntimeError(
                    f"Failed to open in Imaris.\n\nFile: {downloaded_file}"
                )

        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            import traceback

            traceback.print_exc()
            _xt_debug(f"Load worker failed: {e}")
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
    try:
        with candidate.open("a", encoding="utf-8", errors="replace") as f:
            f.write(msg)
            if not msg.endswith("\n"):
                f.write("\n")
    except Exception as exc:
        logger.debug(
            "Suppressed non-fatal exception in XTOmeroConnector.py", exc_info=exc
        )


def _xt_show_fatal(title, message):
    try:
        import tkinter.messagebox as _mb

        _mb.showerror(title, message)
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
        _xt_write_log(log_path, f"argv: {sys.argv}")
        _xt_write_log(log_path, f"cwd: {os.getcwd()}")
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
