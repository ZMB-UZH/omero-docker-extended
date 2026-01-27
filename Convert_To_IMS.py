#!/usr/bin/env python
# -*- coding: utf-8 -*-
import omero
from omero.gateway import BlitzGateway
from omero.rtypes import rstring, rlong
from omero import scripts
import os
import tempfile
import subprocess
import shutil
import re
import urllib.request
import urllib.error


IMARISCONVERT_INSTALL_DIR = "/opt/omero/imarisconvert"
BIOFORMATS_SUBDIR = "bioformats"
BIOFORMATS_JAR_NAME = "bioformats_package.jar"
# Keep this in sync with startup/51-install-imarisconvert.sh
BIOFORMATS_URL = "https://downloads.openmicroscopy.org/bio-formats/8.4.0/artifacts/bioformats_package.jar"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_JAVA_MAX_HEAP = "16G"


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


def convert_to_ims(input_file, output_file):
    try:
        # Prefer the binary installed by startup/51-install-imarisconvert.sh
        converter = shutil.which("imarisconvert")
        if converter and os.path.exists(converter):
            # IMPORTANT: /usr/local/bin/imarisconvert is a symlink in this project.
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

        cmd = [converter_path, "-i", input_file, "-o", output_file]

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


def upload_file_to_omero(conn, file_path, image_id):
    try:
        file_ann = conn.createFileAnnfromLocalFile(
            file_path,
            mimetype="application/octet-stream",
            ns="imaris.ims.converted",
            desc="IMS file converted from original using ImarisConvertBioformats"
        )
        image = conn.getObject("Image", image_id)
        if image:
            image.linkAnnotation(file_ann)
        return file_ann.getId()
    except Exception as e:
        print(f"Error uploading file: {e}")
        return None


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

    temp_dir = tempfile.mkdtemp(prefix="omero_ims_")
    try:
        safe_name = _safe_filename(image.getName(), fallback=f"omero_image_{image_id}")
        output_file = os.path.join(temp_dir, f"{safe_name}.ims")

        success = convert_to_ims(input_file, output_file)
        if not success:
            # Keep temp dir on failure for debugging unless explicitly disabled.
            keep_tmp = os.environ.get("OMERO_IMS_KEEP_TEMP", "1").strip().lower() in ("1", "true", "yes", "y")
            if keep_tmp:
                return (False, f"Conversion to IMS failed. Temp dir kept for debugging: {temp_dir}", None)
            return (False, "Conversion to IMS failed", None)

        file_ann_id = upload_file_to_omero(conn, output_file, image_id)
        if not file_ann_id:
            return (False, "Failed to upload IMS file to OMERO", None)

        return (True, f"Successfully converted to IMS (FileAnnotation:{file_ann_id})", file_ann_id)

    finally:
        try:
            keep_tmp = os.environ.get("OMERO_IMS_KEEP_TEMP", "0").strip().lower() in ("1", "true", "yes", "y")
            if not keep_tmp:
                shutil.rmtree(temp_dir)
        except Exception:
            pass


def run_script():
    client = scripts.client(
        'Convert_To_IMS.py',
        """Convert an OMERO image to IMS format using ImarisConvertBioformats.""",
        scripts.Long(
            "Image_ID",
            optional=False,
            grouping="1",
            description="ID of the image to convert to IMS format"
        ),
        authors=["OMERO Team"],
        institutions=["University"],
        contact="support@example.com",
    )
    try:
        params = client.getInputs(unwrap=True)
        image_id = params.get("Image_ID")
        conn = BlitzGateway(client_obj=client)
        success, message, file_ann_id = run_conversion(conn, image_id)
        client.setOutput("Message", rstring(message))
        if success and file_ann_id:
            client.setOutput("File_Annotation", rlong(file_ann_id))
    except Exception as e:
        client.setOutput("Message", rstring(f"Script error: {e}"))
        import traceback
        traceback.print_exc()
    finally:
        client.closeSession()


if __name__ == "__main__":
    run_script()
