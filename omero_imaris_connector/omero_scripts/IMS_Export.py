#!/usr/bin/env python
# -*- coding: utf-8 -*-
import hashlib
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

import omero.rtypes
from omero import scripts
from omero.gateway import BlitzGateway
from omero.rtypes import rstring
from omero_plugin_common import process_utils
from omero_plugin_common.env_utils import (
    ENV_FILE_OMEROSERVER,
    get_env,
)
from omero_plugin_common.logging_utils import summarize_process_output

logger = logging.getLogger(__name__)

IMARISCONVERT_INSTALL_DIR = "/opt/omero/imarisconvert"
BIOFORMATS_SUBDIR = "bioformats"
BIOFORMATS_ARTIFACTS_SUBDIR = os.path.join("artifacts", BIOFORMATS_SUBDIR)
BIOFORMATS_JAR_NAME = "bioformats_package.jar"
BIOFORMATS_MIN_SIZE_BYTES = 10_000_000
DEFAULT_TIMEOUT_SECONDS = 600
EXPORT_READ_CHUNK_BYTES = 1024 * 1024
_PRIVATE_FILE_MODE = 0o600
_CONFIG_MANAGED_DIR = "omero.managed.dir"
_CONFIG_MANAGED_DIR_ENV = "CONFIG_omero_managed_dir"
_CONFIG_IMS_EXPORT_DIR = "omero.ims.export.dir"
subprocess = process_utils


def _existing_regular_path(path):
    """Return existing regular path.

    Inputs: `path` path. Output: `Path` or path text.
    """
    try:
        path_text = os.fspath(path)
    except TypeError:
        return None
    if isinstance(path_text, bytes):
        return None
    if not path_text or "\x00" in path_text:
        return None
    candidate = Path(path_text)
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _export_root_from_value(source, value):
    """Return export root from a trusted OMERO config value.

    Inputs: `source`, `value`. Output: resolved export root string or None.
    """
    try:
        export_root = str(value or "").strip()
    except Exception:
        raise RuntimeError(f"{source} is invalid.") from None
    if not export_root:
        return None
    if "\x00" in export_root:
        raise RuntimeError(f"{source} contains invalid characters.")
    if not os.path.isabs(export_root):
        raise RuntimeError(f"{source} must be an absolute path.")
    try:
        return str(Path(export_root).resolve(strict=False))
    except OSError as exc:
        raise RuntimeError(f"{source} could not be resolved.") from exc


def _get_export_root(conn):
    """Return export root from OMERO server configuration.

    Inputs: `conn` OMERO gateway connection. Output: export root string. Raises:
    RuntimeError when the startup-persisted OMERO config contract is missing.
    """
    try:
        config_service = conn.c.sf.getConfigService()
    except Exception as exc:
        raise RuntimeError("OMERO IMS export configuration lookup failed.") from exc
    if config_service is None:
        raise RuntimeError("OMERO IMS export configuration service is unavailable.")
    try:
        configured_export_root = config_service.getConfigValue(_CONFIG_IMS_EXPORT_DIR)
    except Exception as exc:
        raise RuntimeError("OMERO IMS export directory lookup failed.") from exc
    export_root = _export_root_from_value(
        _CONFIG_IMS_EXPORT_DIR, configured_export_root
    )
    if export_root is None:
        raise RuntimeError(
            "OMERO IMS export directory is not configured. Set OMERO_IMS_EXPORT_DIR "
            f"in env/omeroserver.env so startup can persist {_CONFIG_IMS_EXPORT_DIR}."
        )
    return export_root


def _safe_filename(name, fallback="image"):
    """Return safe filename.

    Inputs: `name`, `fallback`. Output: `name`.
    """
    if name is None:
        name = ""
    name = str(name)
    name = name.replace("\x00", "")
    name = name.strip()
    if not name:
        name = fallback
    # Replace path separators and other risky chars.
    name = name.replace(os.sep, "_")
    if os.altsep:
        name = name.replace(os.altsep, "_")
    # Keep a conservative whitelist.
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Limit length to avoid filesystem/path issues.
    if len(name) > 200:
        name = name[:200].rstrip()
    if not name:
        name = fallback
    return name


def _ensure_bioformats_jar(install_dir):
    """Ensure the bioformats jar.

    Inputs: `install_dir`. Output: `jar_path`.
    """
    jar_dir = os.path.join(install_dir, BIOFORMATS_SUBDIR)
    jar_path = os.path.join(jar_dir, BIOFORMATS_JAR_NAME)
    cache_dir = os.path.join(install_dir, BIOFORMATS_ARTIFACTS_SUBDIR)
    cache_path = os.path.join(cache_dir, BIOFORMATS_JAR_NAME)
    cache_sha256_path = cache_path + ".sha256"
    expected_sha256 = _read_expected_sha256(cache_sha256_path)

    if _is_valid_bioformats_jar(jar_path, expected_sha256=expected_sha256):
        if not _is_valid_bioformats_jar(
            cache_path, expected_sha256=expected_sha256
        ) and _copy_bioformats_jar(
            jar_path,
            cache_path,
            expected_sha256=_sha256_file(jar_path),
            file_mode=_PRIVATE_FILE_MODE,
            description="cached Bio-Formats jar",
        ):
            _write_expected_sha256(cache_sha256_path, _sha256_file(jar_path))
        return jar_path

    if _is_valid_bioformats_jar(cache_path, expected_sha256=expected_sha256):
        os.makedirs(jar_dir, exist_ok=True)
        restored_sha256 = expected_sha256 or _sha256_file(cache_path)
        if _copy_bioformats_jar(
            cache_path,
            jar_path,
            expected_sha256=restored_sha256,
            file_mode=_PRIVATE_FILE_MODE,
            description="restored Bio-Formats jar",
        ):
            print(f"Restored Bio-Formats jar from local cache: {cache_path}")
            return jar_path

    bf_version = get_env("BIOFORMATS_VERSION", env_file=ENV_FILE_OMEROSERVER)
    bf_url = (
        f"https://downloads.openmicroscopy.org/bio-formats/{bf_version}/"
        f"artifacts/{BIOFORMATS_JAR_NAME}"
    )
    print(f"ERROR: Missing Bio-Formats jar at: {jar_path}")
    print(
        "ERROR: Refusing runtime network download for security reasons. "
        "Install or repair ImarisConvert via startup/51-install-imarisconvert.sh so the pinned jar "
        "and its internal repair copy are auto-provisioned during startup."
    )
    print(f"ERROR: Expected local cache path: {cache_path}")
    print(f"ERROR: Expected Bio-Formats source URL during build time: {bf_url}")
    return None


def _read_expected_sha256(path):
    """Read the expected sha256.

    Inputs: `path` path. Output: `token`.
    """
    checksum_path = _existing_regular_path(path)
    if checksum_path is None:
        return None
    try:
        with checksum_path.open("r", encoding="ascii") as handle:
            token = handle.read().strip().split()[0].lower()
    except (OSError, IndexError, UnicodeDecodeError):
        return None

    if re.fullmatch(r"[0-9a-f]{64}", token):
        return token
    return None


def _write_expected_sha256(path, sha256_value):
    """Write the expected sha256.

    Inputs: `path` path, `sha256_value`. Output: `bool`.
    """
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="ascii") as handle:
            handle.write(f"{sha256_value}  {BIOFORMATS_JAR_NAME}\n")
        os.chmod(tmp_path, _PRIVATE_FILE_MODE)
        os.replace(tmp_path, path)
        return True
    except OSError as exc:
        print(f"WARNING: Failed to write Bio-Formats checksum file {path}: {exc}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as cleanup_exc:
            logger.debug(
                "Suppressed non-fatal exception in IMS_Export.py", exc_info=cleanup_exc
            )
        return False


def _sha256_file(path):
    """Return the sha256 file.

    Inputs: `path` path. Output: `hexdigest` result. Raises: FileNotFoundError when validation
    or the called operation fails.
    """
    source_path = _existing_regular_path(path)
    if source_path is None:
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_bioformats_jar(path, expected_sha256=None):
    """Return whether valid bioformats jar.

    Inputs: `path`, `expected_sha256`. Output: bool.
    """
    if not os.path.exists(path):
        return False

    try:
        if os.path.getsize(path) < BIOFORMATS_MIN_SIZE_BYTES:
            return False
        if expected_sha256 is not None and _sha256_file(path) != expected_sha256:
            return False
    except OSError:
        return False

    return True


def _copy_bioformats_jar(
    source_path, destination_path, expected_sha256, file_mode, description
):
    """Copy the bioformats jar.

    Inputs: `source_path`, `destination_path`, `expected_sha256`, `file_mode`,
    `description`. Output: `bool`.
    """
    tmp_path = destination_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        shutil.copyfile(source_path, tmp_path)
        if _sha256_file(tmp_path) != expected_sha256:
            print(
                f"ERROR: Integrity check failed while preparing {description}: {destination_path}"
            )
            os.remove(tmp_path)
            return False
        os.chmod(tmp_path, file_mode)
        os.replace(tmp_path, destination_path)
        return True
    except OSError as exc:
        print(f"ERROR: Failed to install {description} at {destination_path}: {exc}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as cleanup_exc:
            logger.debug(
                "Suppressed non-fatal exception in IMS_Export.py", exc_info=cleanup_exc
            )
        return False


def _get_voxel_size_from_image(image):
    """Return voxel sizes (vx, vy, vz) in micrometers as floats.

    Inputs: `image`. Output: tuple.

    ImarisConvert fails if any axis has voxel size <= 0, so we ensure safe defaults.

    Fallback policy (minimal, safe):
      - If X missing/<=0 -> 1.0
      - If Y missing/<=0 -> X
      - If Z missing/<=0 -> X  (common for single-plane / missing Z metadata)
    """
    vx = None
    vy = None
    vz = None

    try:
        px = image.getPrimaryPixels()
        if px:
            psx = px.getPhysicalSizeX()
            psy = px.getPhysicalSizeY()
            psz = px.getPhysicalSizeZ()

            if psx is not None:
                try:
                    vx = float(psx.getValue())
                except Exception:
                    vx = None
            if psy is not None:
                try:
                    vy = float(psy.getValue())
                except Exception:
                    vy = None
            if psz is not None:
                try:
                    vz = float(psz.getValue())
                except Exception:
                    vz = None
    except Exception:
        vx = vy = vz = None

    if vx is None or vx <= 0:
        vx = 1.0
    if vy is None or vy <= 0:
        vy = vx
    if vz is None or vz <= 0:
        vz = vx

    return vx, vy, vz


def _managed_repository_root_from_value(source, value):
    """A managed repository root from a configured value.

    Inputs: `source`, `value` input value. Output: `resolve` result.
    """
    try:
        managed_root = str(value or "").strip()
    except Exception:
        print(f"Error reading {source}: value is invalid")
        return None
    if not managed_root:
        print(f"Error reading {source}: value is empty")
        return None
    if "\x00" in managed_root:
        print(f"Error reading {source}: value contains invalid characters")
        return None
    path_class = _path_class_for_server_path(managed_root)
    if path_class is None:
        print(f"Error reading {source}: value must be absolute")
        return None
    if path_class is PurePosixPath and os.name != "nt":
        path_class = Path
    try:
        root_path = path_class(managed_root)
        if isinstance(root_path, Path):
            return root_path.resolve(strict=False)
        return root_path
    except OSError:
        print(f"Error reading {source}: value could not be resolved")
        return None


def _path_class_for_server_path(path_text):
    """Return the path class that matches an OMERO server path string.

    Inputs: `path_text`. Output: pathlib path class or None.
    """
    if re.match(r"^[A-Za-z]:[\\/]", path_text) or path_text.startswith("\\\\"):
        return PureWindowsPath
    if path_text.startswith("/"):
        return PurePosixPath
    return None


def _safe_relative_path_parts(value, allow_empty):
    """Return safe relative path parts split across Windows and POSIX separators.

    Inputs: `value`, `allow_empty`. Output: list of parts or None.
    """
    text = str(value or "").strip().strip("/\\")
    if "\x00" in text:
        print("Error getting original file path: value contains invalid characters")
        return None
    if not text:
        return [] if allow_empty else None
    parts = [part for part in re.split(r"[\\/]+", text) if part]
    if any(part in {"", ".", ".."} for part in parts):
        print("Error getting original file path: managed file path is invalid")
        return None
    if any(re.match(r"^[A-Za-z]:$", part) for part in parts):
        print("Error getting original file path: managed file path is invalid")
        return None
    return parts


def _get_managed_repository_root(conn):
    """Return the configured OMERO managed repository root.

    Inputs: `conn` OMERO gateway connection. Output:
    `_managed_repository_root_from_value` result.
    """
    if _CONFIG_MANAGED_DIR_ENV in os.environ:
        return _managed_repository_root_from_value(
            _CONFIG_MANAGED_DIR_ENV,
            os.environ.get(_CONFIG_MANAGED_DIR_ENV),
        )

    try:
        config_service = conn.c.sf.getConfigService()
    except Exception:
        print("Error getting original file path: OMERO config service lookup failed")
        return None
    if config_service is None:
        print("Error getting original file path: OMERO config service is unavailable")
        return None
    try:
        managed_root = config_service.getConfigValue(_CONFIG_MANAGED_DIR)
    except Exception:
        print(f"Error reading {_CONFIG_MANAGED_DIR}: lookup failed")
        return None
    return _managed_repository_root_from_value(_CONFIG_MANAGED_DIR, managed_root)


def _managed_original_file_path(managed_root, file_path, file_name):
    """Return the managed original file path.

    Inputs: `managed_root`, `file_path` file path, `file_name`. Output: `str`.
    """
    relative_dir_parts = _safe_relative_path_parts(file_path, allow_empty=True)
    relative_name_parts = _safe_relative_path_parts(file_name, allow_empty=False)
    if relative_dir_parts is None or relative_name_parts is None:
        return None
    if len(relative_name_parts) != 1:
        print("Error getting original file path: file name is invalid")
        return None
    candidate = managed_root
    for part in [*relative_dir_parts, relative_name_parts[0]]:
        candidate = candidate / part
    try:
        candidate.relative_to(managed_root)
    except ValueError:
        print("Error getting original file path: managed file path escapes repository")
        return None
    return str(candidate)


def _absolute_original_file_path(file_path, file_name):
    """Return an absolute OriginalFile path when OMERO stores one directly.

    Inputs: `file_path`, `file_name`. Output: `str` result or None.
    """
    path_text = str(file_path or "").strip()
    name_text = str(file_name or "").strip().strip("/\\")
    if "\x00" in path_text or "\x00" in name_text:
        print("Error getting original file path: value contains invalid characters")
        return None
    path_class = _path_class_for_server_path(path_text)
    if path_class is None:
        return None
    name_parts = _safe_relative_path_parts(name_text, allow_empty=True)
    if name_parts is None:
        return None
    if len(name_parts) > 1:
        print("Error getting original file path: file name is invalid")
        return None
    if path_class is PurePosixPath and os.name != "nt":
        path_class = Path
    candidate = path_class(path_text)
    if name_parts:
        candidate = candidate / name_parts[0]
    try:
        if isinstance(candidate, Path):
            return str(candidate.resolve(strict=False))
        return str(candidate)
    except OSError:
        print("Error getting original file path: absolute path could not be resolved")
        return None


def get_original_file_path(conn, image):
    """Return original file path.

    Inputs: `conn` OMERO gateway connection, `image`. Output:
    `_managed_original_file_path` result.
    """
    try:
        fileset = image.getFileset()
        if not fileset:
            return None
        files = list(fileset.listFiles())
        if not files:
            return None
        original_file = files[0]
        absolute_path = _absolute_original_file_path(
            original_file.getPath(),
            original_file.getName(),
        )
        if absolute_path:
            return absolute_path
        managed_root = _get_managed_repository_root(conn)
        if managed_root is None:
            return None
        return _managed_original_file_path(
            managed_root,
            original_file.getPath(),
            original_file.getName(),
        )
    except Exception:
        print("Error getting original file path: lookup failed")
        return None


def convert_to_ims(image, input_file, output_file):
    """Convert the to IMS.

    Inputs: `image`, `input_file`, `output_file`. Output: `exists` result.
    """
    try:
        # Prefer the binary installed by startup/51-install-imarisconvert.sh
        converter = shutil.which("imarisconvert")
        if converter and os.path.exists(converter):
            # IMPORTANT: /usr/local/bin/imarisconvert may be a symlink or wrapper.
            # Resolve to the real binary so ImarisConvertBioformats can find its runtime files.
            converter_path = os.path.realpath(converter)
        else:
            converter_path = os.path.join(
                IMARISCONVERT_INSTALL_DIR, "ImarisConvertBioformats"
            )

        if not os.path.exists(converter_path):
            print(f"ERROR: ImarisConvertBioformats not found at: {converter_path}")
            return False

        # Ensure Bio-Formats jar exists at the location expected by ImarisConvertBioformats.
        jar_path = _ensure_bioformats_jar(IMARISCONVERT_INSTALL_DIR)
        if not jar_path:
            print("ERROR: Bio-Formats jar could not be ensured. Aborting conversion.")
            return False

        # Ensure voxel size is valid for ImarisConvert (it fails if any axis is 0).
        vsx, vsy, vsz = _get_voxel_size_from_image(image)

        cmd = [
            converter_path,
            "-i",
            input_file,
            "-o",
            output_file,
            "-vsx",
            str(vsx),
            "-vsy",
            str(vsy),
            "-vsz",
            str(vsz),
        ]

        print(f"Running: {' '.join(cmd)}")

        # Ensure shared libraries can be found.
        env = os.environ.copy()
        ld_parts = []
        if env.get("LD_LIBRARY_PATH"):
            ld_parts.append(env["LD_LIBRARY_PATH"])
        ld_parts.append(IMARISCONVERT_INSTALL_DIR)
        env["LD_LIBRARY_PATH"] = ":".join([p for p in ld_parts if p])

        # Force Bio-Formats onto the Java classpath (covers launchers that rely on CLASSPATH).
        # Preserve any existing CLASSPATH by appending.
        if env.get("CLASSPATH"):
            env["CLASSPATH"] = jar_path + os.pathsep + env["CLASSPATH"]
        else:
            env["CLASSPATH"] = jar_path

        # Run from the REAL binary directory (not /usr/local/bin) to match any internal
        # "find files relative to executable" logic.
        converter_dir = os.path.dirname(converter_path)

        result = process_utils.run(
            cmd,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            env=env,
            cwd=converter_dir,
        )

        if result.returncode != 0:
            print("Conversion failed!")
            print(
                "Command output summary: "
                f"{summarize_process_output(result.stdout, result.stderr)}"
            )
            return False

        print("Conversion successful!")
        return os.path.exists(output_file)

    except Exception as e:
        print(f"Conversion error: {e}")
        return False


def _build_export_path(export_root, image, image_id):
    """Build the export path.

    Inputs: `export_root`, `image`, `image_id` OMERO image ID. Output: `join` result.
    """
    safe_name = _safe_filename(image.getName(), fallback=f"omero_image_{image_id}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = os.path.join(export_root, f"image_{image_id}")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{safe_name}_{timestamp}.ims")


def _build_intermediate_ome_tiff_path(export_root, image, image_id):
    """A temporary OME-TIFF source path for conversion.

    Inputs: `export_root`, `image`, `image_id`. Output: `os.path.join` result.
    """
    safe_name = _safe_filename(image.getName(), fallback=f"omero_image_{image_id}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = os.path.join(export_root, f"image_{image_id}", "source")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{safe_name}_{timestamp}.ome.tif")


def _write_binary_chunk(handle, chunk):
    """Write the binary chunk.

    Inputs: `handle`, `chunk`. Output: `int` count.
    """
    if chunk is None:
        return 0
    if isinstance(chunk, str):
        chunk = chunk.encode("latin-1")
    elif not isinstance(chunk, (bytes, bytearray, memoryview)):
        chunk = bytes(chunk)
    handle.write(chunk)
    return len(chunk)


def _write_ome_tiff_from_image_wrapper(image, output_handle):
    """Write the OME tiff from image wrapper.

    Inputs: `image`, `output_handle`. Output: `bool`.
    """
    exporter = getattr(image, "exportOmeTiff", None)
    if not callable(exporter):
        return False
    exported = exporter(bufsize=EXPORT_READ_CHUNK_BYTES)
    if isinstance(exported, tuple) and len(exported) == 2:
        _size, chunks = exported
        total = 0
        for chunk in chunks:
            total += _write_binary_chunk(output_handle, chunk)
        return total > 0
    return _write_binary_chunk(output_handle, exported) > 0


def _write_ome_tiff_from_exporter(conn, image_id, output_handle):
    """Write the OME tiff from exporter.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID, `output_handle`.
    Output: `bool`.
    """
    create_exporter = getattr(conn, "createExporter", None)
    if not callable(create_exporter):
        return False
    exporter = create_exporter()
    try:
        exporter.addImage(int(image_id))
        service_opts = getattr(conn, "SERVICE_OPTS", None)
        try:
            if service_opts is None:
                total_size = exporter.generateTiff()
            else:
                total_size = exporter.generateTiff(service_opts)
        except TypeError:
            total_size = exporter.generateTiff()
        total_size = int(total_size)
        offset = 0
        written = 0
        while offset < total_size:
            chunk_size = min(EXPORT_READ_CHUNK_BYTES, total_size - offset)
            chunk = exporter.read(offset, chunk_size)
            if not chunk:
                break
            written += _write_binary_chunk(output_handle, chunk)
            offset += len(chunk)
        return written > 0 and written == total_size
    finally:
        close = getattr(exporter, "close", None)
        if callable(close):
            close()


def _materialize_ome_tiff_source(conn, image, image_id, export_root):
    """A converter-readable OME-TIFF source through OMERO APIs.

    Inputs: `conn` OMERO gateway connection, `image`, `image_id` OMERO image ID,
    `export_root`. Output: `_write_ome_tiff_from_image_wrapper` result.
    """
    output_file = _build_intermediate_ome_tiff_path(export_root, image, image_id)
    output_dir = os.path.dirname(output_file)

    def write_from_wrapper(handle):
        """Write the from wrapper.

        Inputs: `handle`. Output: `_write_ome_tiff_from_image_wrapper` result.
        """
        return _write_ome_tiff_from_image_wrapper(image, handle)

    def write_from_exporter(handle):
        """Write the from exporter.

        Inputs: `handle`. Output: `_write_ome_tiff_from_exporter` result.
        """
        return _write_ome_tiff_from_exporter(conn, image_id, handle)

    os.makedirs(output_dir, exist_ok=True)
    for writer in (write_from_wrapper, write_from_exporter):
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output_dir,
                prefix=".ims-export-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_file = handle.name
                wrote_source = writer(handle)
                if wrote_source:
                    handle.flush()
                    os.fsync(handle.fileno())
            if wrote_source:
                os.chmod(tmp_file, _PRIVATE_FILE_MODE)
                os.replace(tmp_file, output_file)
                print(f"Prepared OME-TIFF source via OMERO API: {output_file}")
                return output_file
        except Exception as exc:
            print(f"WARNING: OMERO OME-TIFF export attempt failed: {exc}")
            try:
                if tmp_file and os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except OSError as cleanup_exc:
                logger.debug(
                    "Suppressed non-fatal exception in IMS_Export.py",
                    exc_info=cleanup_exc,
                )
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError as cleanup_exc:
                    logger.debug(
                        "Suppressed non-fatal exception in IMS_Export.py",
                        exc_info=cleanup_exc,
                    )
    print("ERROR: OMERO OME-TIFF export did not produce a readable source file")
    return None


def _remove_intermediate_source(path):
    """Remove the intermediate source.

    Inputs: `path` path. Output: None.
    """
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        print(f"WARNING: Failed to remove temporary source file {path}: {exc}")


def run_conversion(conn, image_id, export_root):
    """Convert an OMERO image to IMS and return the export result.

    Inputs: `conn`, `image_id`, `export_root`. Output: tuple.
    """
    image = conn.getObject("Image", image_id)
    if not image:
        return (False, f"Image {image_id} not found", None)

    print(f"Converting image: {image.getName()} (ID: {image_id})")

    input_file = get_original_file_path(conn, image)
    generated_input = False
    existing_input = _existing_regular_path(input_file) if input_file else None
    if existing_input is not None:
        input_file = str(existing_input)
        print(f"Input file: {input_file}")
    else:
        if input_file:
            print(
                "Original source file is not available in this runtime; "
                "exporting OME-TIFF through OMERO API"
            )
        else:
            print(
                "Original source file path is unavailable; "
                "exporting OME-TIFF through OMERO API"
            )
        input_file = _materialize_ome_tiff_source(conn, image, image_id, export_root)
        generated_input = input_file is not None
        if not input_file:
            return (False, "Could not prepare source image for IMS conversion", None)

    output_file = _build_export_path(export_root, image, image_id)

    try:
        success = convert_to_ims(image, input_file, output_file)
        if not success:
            return (False, "Conversion to IMS failed", None)
    finally:
        if generated_input:
            _remove_intermediate_source(input_file)

    return (True, f"Successfully exported IMS: {output_file}", output_file)


def run_script():
    # Resolve export root and ensure directory exists here (inside run_script),
    # NOT at module level, so the OMERO processor can parse parameters without
    # triggering filesystem side-effects that cause ValidationException:
    # 'Can't find params for <id>'.
    """The script entrypoint.

    Inputs: no caller arguments. Output: performs the documented action and returns None.
    """
    client = scripts.client(
        "IMS_Export.py",
        """Export an OMERO image to IMS format using ImarisConvertBioformats.""",
        scripts.Long(
            "Image_ID",
            optional=False,
            grouping="1",
            description="ID of the image to export to IMS format",
        ),
        namespaces=["omero.export"],
        version="1.0.0",
        authors=["Efstratios Mitridis"],
        institutions=["ZMB/UZH"],
        contact="mitridisefstratios@gmail.com",
    )
    try:
        params = client.getInputs(unwrap=True)
        image_id = params.get("Image_ID")
        conn = BlitzGateway(client_obj=client)
        conn.SERVICE_OPTS.setOmeroGroup(-1)  # Enable cross-group access
        export_root = _get_export_root(conn)
        os.makedirs(export_root, exist_ok=True)
        success, message, export_path = run_conversion(conn, image_id, export_root)
        client.setOutput("Message", rstring(message))

        if success and export_path and os.path.exists(export_path):
            # Attach the IMS file as a FileAnnotation to the image
            # This makes it downloadable from the Activities panel
            try:
                image = conn.getObject("Image", image_id)
                if image:
                    # Switch to the image's group for write operations
                    image_group = image.getDetails().getGroup().getId()
                    conn.SERVICE_OPTS.setOmeroGroup(image_group)

                    # Create file annotation
                    file_ann = conn.createFileAnnfromLocalFile(
                        export_path,
                        mimetype="application/octet-stream",
                        ns="omero.export.ims",
                        desc=f"IMS export of {image.getName()}",
                    )

                    # Link to image
                    image.linkAnnotation(file_ann)

                    # Return the file annotation object so OMERO.web shows a download button
                    try:
                        file_ann_obj = getattr(file_ann, "_obj", None)
                        if file_ann_obj is not None:
                            client.setOutput(
                                "File_Annotation", omero.rtypes.robject(file_ann_obj)
                            )
                    except Exception as output_error:
                        print(
                            f"WARNING: Failed to set File_Annotation output: {output_error}"
                        )
                    # Also return the ID for clients that only parse numeric outputs
                    client.setOutput(
                        "File_Annotation_Id", omero.rtypes.rlong(file_ann.getId())
                    )
                    client.setOutput("Export_Path", rstring(export_path))
                    client.setOutput(
                        "Export_Name", rstring(os.path.basename(export_path))
                    )

                    print(
                        f"Attached file annotation {file_ann.getId()} to image {image_id}"
                    )
                else:
                    print(
                        f"WARNING: Could not retrieve image {image_id} to attach file"
                    )
                    client.setOutput("Export_Path", rstring(export_path))
                    client.setOutput(
                        "Export_Name", rstring(os.path.basename(export_path))
                    )
            except Exception as e:
                print(f"WARNING: Failed to attach file annotation: {e}")
                import traceback

                traceback.print_exc()
                # Still return the path even if attachment fails
                client.setOutput("Export_Path", rstring(export_path))
                client.setOutput("Export_Name", rstring(os.path.basename(export_path)))

    except Exception as e:
        client.setOutput("Message", rstring(f"Script error: {e}"))
        import traceback

        traceback.print_exc()
    finally:
        client.closeSession()


if __name__ == "__main__":
    run_script()
