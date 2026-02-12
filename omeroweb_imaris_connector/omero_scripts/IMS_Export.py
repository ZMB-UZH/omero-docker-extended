#!/usr/bin/env python
# -*- coding: utf-8 -*-
from omero.gateway import BlitzGateway
from omero.rtypes import rstring
from omero import scripts
import omero.rtypes
import os
import subprocess
import shutil
import re
import urllib.request
import urllib.error
from datetime import datetime

from omero_plugin_common.env_utils import ENV_FILE_OMERO_CELERY, get_env

IMARISCONVERT_INSTALL_DIR = "/opt/omero/imarisconvert"
BIOFORMATS_SUBDIR = "bioformats"
BIOFORMATS_JAR_NAME = "bioformats_package.jar"
# Keep this in sync with startup/51-install-imarisconvert.sh
BIOFORMATS_URL = "https://downloads.openmicroscopy.org/bio-formats/8.4.0/artifacts/bioformats_package.jar"
DEFAULT_TIMEOUT_SECONDS = 600
try:
    EXPORT_ROOT = get_env(
        "OMERO_IMS_EXPORT_DIR",
        env_file=ENV_FILE_OMERO_CELERY,
    )
except RuntimeError as e:
    # Some OMERO script runners do not propagate all container env vars reliably.
    # Fall back to the default path under the mounted /OMERO volume.
    EXPORT_ROOT = "/OMERO/ImarisExports"
    print(f"WARNING: {e}")
    print(f"WARNING: Falling back to default OMERO_IMS_EXPORT_DIR={EXPORT_ROOT}")
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
# Ensure export root exists
os.makedirs(EXPORT_ROOT, exist_ok=True)



def _ensure_bioformats_jar(install_dir):
    """Ensure Bio-Formats jar exists where ImarisConvertBioformats expects it."""
    jar_dir = os.path.join(install_dir, BIOFORMATS_SUBDIR)
    jar_path = os.path.join(jar_dir, BIOFORMATS_JAR_NAME)

    if os.path.exists(jar_path) and os.path.getsize(jar_path) > 0:
        return jar_path

    os.makedirs(jar_dir, exist_ok=True)
    tmp_path = jar_path + ".download"

    print(f"Bio-Formats jar missing. Downloading to: {jar_path}")
    print(f"Source: {BIOFORMATS_URL}")
    try:
        with urllib.request.urlopen(BIOFORMATS_URL, timeout=60) as r, open(tmp_path, "wb") as f:
            shutil.copyfileobj(r, f)
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            print("ERROR: Downloaded Bio-Formats jar is empty")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return None
        os.replace(tmp_path, jar_path)
        os.chmod(jar_path, 0o644)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"ERROR: Failed to download Bio-Formats jar: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error downloading Bio-Formats jar: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return None

    if not os.path.exists(jar_path) or os.path.getsize(jar_path) == 0:
        print("ERROR: Bio-Formats jar download resulted in an empty or missing file")
        return None

    return jar_path


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
            converter_path = os.path.join(IMARISCONVERT_INSTALL_DIR, "ImarisConvertBioformats")

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
            "-i", input_file,
            "-o", output_file,
            "-vsx", str(vsx),
            "-vsy", str(vsy),
            "-vsz", str(vsz),
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
            cwd=converter_dir
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


def _build_export_path(image, image_id):
    safe_name = _safe_filename(image.getName(), fallback=f"omero_image_{image_id}")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_dir = os.path.join(EXPORT_ROOT, f"image_{image_id}")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{safe_name}_{timestamp}.ims")


def run_conversion(conn, image_id):
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

    output_file = _build_export_path(image, image_id)

    success = convert_to_ims(image, input_file, output_file)
    if not success:
        return (False, "Conversion to IMS failed", None)

    return (True, f"Successfully exported IMS: {output_file}", output_file)


def run_script():
    client = scripts.client(
        "IMS_Export.py",
        """Export an OMERO image to IMS format using ImarisConvertBioformats.""",
        scripts.Long(
            "Image_ID",
            optional=False,
            grouping="1",
            description="ID of the image to export to IMS format"
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
        success, message, export_path = run_conversion(conn, image_id)
        client.setOutput("Message", rstring(message))
        
        if success and export_path and os.path.exists(export_path):
            # Attach the IMS file as a FileAnnotation to the image
            # This makes it downloadable from the Activities panel
            try:
                from omero.model import FileAnnotationI, OriginalFileI
                from omero.gateway import FileAnnotationWrapper
                
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
                        desc=f"IMS export of {image.getName()}"
                    )
                    
                    # Link to image
                    image.linkAnnotation(file_ann)
                    
                    # Return the file annotation object so OMERO.web shows a download button
                    try:
                        client.setOutput("File_Annotation", omero.rtypes.robject(file_ann._obj))
                    except Exception as output_error:
                        print(f"WARNING: Failed to set File_Annotation output: {output_error}")
                    # Also return the ID for clients that only parse numeric outputs
                    client.setOutput("File_Annotation_Id", omero.rtypes.rlong(file_ann.getId()))
                    client.setOutput("Export_Path", rstring(export_path))
                    client.setOutput("Export_Name", rstring(os.path.basename(export_path)))
                    
                    print(f"Attached file annotation {file_ann.getId()} to image {image_id}")
                else:
                    print(f"WARNING: Could not retrieve image {image_id} to attach file")
                    client.setOutput("Export_Path", rstring(export_path))
                    client.setOutput("Export_Name", rstring(os.path.basename(export_path)))
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
