#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging

logger = logging.getLogger(__name__)

from omero.gateway import BlitzGateway
from omero.rtypes import rstring
from omero import scripts
import omero.rtypes
import os
import subprocess
import shutil
import re
import hashlib
from datetime import datetime

from omero_plugin_common.env_utils import (
    ENV_FILE_OMERO_CELERY,
    ENV_FILE_OMEROSERVER,
    get_env,
)

IMARISCONVERT_INSTALL_DIR = "/opt/omero/imarisconvert"
BIOFORMATS_SUBDIR = "bioformats"
BIOFORMATS_ARTIFACTS_SUBDIR = os.path.join("artifacts", BIOFORMATS_SUBDIR)
BIOFORMATS_JAR_NAME = "bioformats_package.jar"
BIOFORMATS_MIN_SIZE_BYTES = 10_000_000
DEFAULT_TIMEOUT_SECONDS = 600


def _get_export_root():
    """Resolve the IMS export root directory, with a safe fallback.

    This function is intentionally NOT called at module level so that the
    OMERO processor can parse script parameters without triggering side
    effects (filesystem access, env-file reads) that would crash parameter
    discovery and cause the 'Can't find params for <id>' ValidationException.
    """
    try:
        return get_env(
            "OMERO_IMS_EXPORT_DIR",
            env_file=ENV_FILE_OMERO_CELERY,
        )
    except RuntimeError as e:
        fallback = "/OMERO/ImarisExports"
        print(f"WARNING: {e}")
        print(f"WARNING: Falling back to default OMERO_IMS_EXPORT_DIR={fallback}")
        return fallback


def _safe_filename(name, fallback="image"):
    """Create a filesystem-safe filename (no path separators, no control chars)."""
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
    """Ensure Bio-Formats jar exists where ImarisConvertBioformats expects it."""
    jar_dir = os.path.join(install_dir, BIOFORMATS_SUBDIR)
    jar_path = os.path.join(jar_dir, BIOFORMATS_JAR_NAME)
    cache_dir = os.path.join(install_dir, BIOFORMATS_ARTIFACTS_SUBDIR)
    cache_path = os.path.join(cache_dir, BIOFORMATS_JAR_NAME)
    cache_sha256_path = cache_path + ".sha256"
    expected_sha256 = _read_expected_sha256(cache_sha256_path)

    if _is_valid_bioformats_jar(jar_path, expected_sha256=expected_sha256):
        if not _is_valid_bioformats_jar(cache_path, expected_sha256=expected_sha256):
            if _copy_bioformats_jar(
                jar_path,
                cache_path,
                expected_sha256=_sha256_file(jar_path),
                file_mode=0o644,
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
            file_mode=0o640,
            description="restored Bio-Formats jar",
        ):
            print(f"Restored Bio-Formats jar from local cache: {cache_path}")
            return jar_path

    bf_version = get_env("BIOFORMATS_VERSION", env_file=ENV_FILE_OMEROSERVER)
    bf_url = f"https://downloads.openmicroscopy.org/bio-formats/{bf_version}/artifacts/{BIOFORMATS_JAR_NAME}"
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
    try:
        with open(path, "r", encoding="ascii") as handle:
            token = handle.read().strip().split()[0].lower()
    except (OSError, IndexError, UnicodeDecodeError):
        return None

    if re.fullmatch(r"[0-9a-f]{64}", token):
        return token
    return None


def _write_expected_sha256(path, sha256_value):
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="ascii") as handle:
            handle.write(f"{sha256_value}  {BIOFORMATS_JAR_NAME}\n")
        os.chmod(tmp_path, 0o644)
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
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_bioformats_jar(path, expected_sha256=None):
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
    """
    Return voxel sizes (vx, vy, vz) in micrometers as floats.
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


def get_original_file_path(conn, image):
    try:
        fileset = image.getFileset()
        if not fileset:
            return None
        files = list(fileset.listFiles())
        if not files:
            return None
        original_file = files[0]
        managed_repo_path = "/OMERO/ManagedRepository"
        file_path = original_file.getPath()
        file_name = original_file.getName()
        full_path = os.path.join(managed_repo_path, file_path, file_name)
        return full_path
    except Exception as e:
        print(f"Error getting original file path: {e}")
        return None


def convert_to_ims(image, input_file, output_file):
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

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            env=env,
            cwd=converter_dir,
        )

        if result.returncode != 0:
            print("Conversion failed!")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False

        print("Conversion successful!")
        return os.path.exists(output_file)

    except Exception as e:
        print(f"Conversion error: {e}")
        return False


def _build_export_path(export_root, image, image_id):
    safe_name = _safe_filename(image.getName(), fallback=f"omero_image_{image_id}")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_dir = os.path.join(export_root, f"image_{image_id}")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{safe_name}_{timestamp}.ims")


def run_conversion(conn, image_id, export_root):
    image = conn.getObject("Image", image_id)
    if not image:
        return (False, f"Image {image_id} not found", None)

    print(f"Converting image: {image.getName()} (ID: {image_id})")

    input_file = get_original_file_path(conn, image)
    if not input_file:
        return (False, "Could not get original file path", None)
    if not os.path.exists(input_file):
        return (False, f"Original file not found: {input_file}", None)

    print(f"Input file: {input_file}")

    output_file = _build_export_path(export_root, image, image_id)

    success = convert_to_ims(image, input_file, output_file)
    if not success:
        return (False, "Conversion to IMS failed", None)

    return (True, f"Successfully exported IMS: {output_file}", output_file)


def run_script():
    # Resolve export root and ensure directory exists here (inside run_script),
    # NOT at module level, so the OMERO processor can parse parameters without
    # triggering filesystem side-effects that cause ValidationException:
    # 'Can't find params for <id>'.
    export_root = _get_export_root()
    os.makedirs(export_root, exist_ok=True)

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
                        client.setOutput(
                            "File_Annotation", omero.rtypes.robject(file_ann._obj)
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
