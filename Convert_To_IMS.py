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
        tools_dir = os.path.join(os.path.dirname(__file__), "tools")
        os.makedirs(tools_dir, exist_ok=True)

        bioformats_jar = os.path.join(tools_dir, "bioformats_package.jar")
        bioformats_url = (
            "https://downloads.openmicroscopy.org/bio-formats/7.1.0/"
            "artifacts/bioformats_package.jar"
        )

        if not os.path.exists(bioformats_jar):
            print("Bio-Formats not found, downloading automatically...")
            try:
                import urllib.request
                urllib.request.urlretrieve(bioformats_url, bioformats_jar)
            except Exception as e:
                print(f"ERROR: Failed to download Bio-Formats: {e}")
                return False

        cmd = [
            "java",
            "-Xmx16G",
            "-cp", bioformats_jar,
            "com.bitplane.imaris.convert.ImarisConvert",
            "-i", input_file,
            "-o", output_file
        ]

        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
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
        output_file = os.path.join(temp_dir, f"{image.getName()}.ims")
        success = convert_to_ims(input_file, output_file)
        if not success:
            return (False, "Conversion to IMS failed", None)
        file_ann_id = upload_file_to_omero(conn, output_file, image_id)
        if not file_ann_id:
            return (False, "Failed to upload IMS file to OMERO", None)
        return (True, f"Successfully converted to IMS (FileAnnotation:{file_ann_id})", file_ann_id)
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

def run_script():
    client = scripts.client(
        'Convert_To_IMS.py',
        """Convert an OMERO image to IMS format using ImarisConvertBioformats.""",
        scripts.Long("Image_ID", optional=False, grouping="1",
                    description="ID of the image to convert to IMS format"),
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
  
