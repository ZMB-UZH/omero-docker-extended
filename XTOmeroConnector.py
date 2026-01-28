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
from tkinter import ttk, messagebox
import threading
import re
import tempfile
import time

# =============================================================================
# OMERO WEB CLIENT
# =============================================================================

class OMEROWebClient:
    """Client for OMERO.web API."""

    def __init__(self, host, port, username, password, scheme="http"):
        self.base_url = self._build_base_url(host, port, scheme)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.session = None
        self.scheme = scheme

    def _build_base_url(self, host, port, scheme):
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"{scheme}://{host}:{port}"
        
    def connect(self):
        """Authenticate with OMERO.web."""
        try:
            import urllib.request
            import urllib.parse
            import http.cookiejar
            
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
            
            login_url = f"{self.base_url}/webclient/login/"
            req = urllib.request.Request(login_url)
            response = opener.open(req, timeout=10)
            
            csrf_token = None
            for cookie in cookie_jar:
                if cookie.name == 'csrftoken':
                    csrf_token = cookie.value
                    break
            
            if not csrf_token:
                return False
            
            data = urllib.parse.urlencode({
                'username': self.username,
                'password': self.password,
                'server': 1,
                'csrfmiddlewaretoken': csrf_token
            }).encode()
            
            req = urllib.request.Request(login_url, data=data, method='POST')
            req.add_header('Referer', login_url)
            req.add_header('X-CSRFToken', csrf_token)
            
            response = opener.open(req, timeout=10)
            
            session_id = None
            for cookie in cookie_jar:
                if cookie.name == 'sessionid':
                    session_id = cookie.value
                    break
            
            if session_id:
                self.cookie_jar = cookie_jar
                self.opener = opener
                self.csrf_token = csrf_token
                self.session_id = session_id
                return True
            
            return False
            
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def _webclient_api_request(self, endpoint, params=None):
        """Make a webclient API request."""
        import urllib.request
        import urllib.error
        import urllib.parse

        if not hasattr(self, 'opener'):
            return None

        url = f"{self.base_url}/webclient/api/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)

        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)

        try:
            response = self.opener.open(req, timeout=10)
            return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"API error ({e.code}): {e.reason}")
            return None
        except Exception as e:
            print(f"API error: {e}")
            return None

    def get_image_metadata(self, image_id):
        """Get image metadata including original filename."""
        data = self._get_first_webclient_response([
            ("images/{}/".format(image_id), None),
            ("objects/", {"type": "image", "id": image_id}),
            ("metadata/", {"type": "image", "id": image_id}),
        ])
        if not data:
            return {}

        if isinstance(data, list):
            data = data[0] if data else {}
        data = data.get('data') or data

        result = {
            'id': image_id,
            'name': data.get('Name') or data.get('name', ''),
            'original_file': None,
        }

        fileset = data.get("Fileset") or data.get("fileset") or {}
        files = fileset.get("Files") or []
        if files:
            result['original_file'] = files[0].get("Name") or files[0].get("name")

        return result

    def list_scripts(self):
        """List available scripts."""
        data = self._webclient_list_scripts()

        print(f"DEBUG: Raw API response type: {type(data)}")
        
        # Handle response - could be list or dict
        if isinstance(data, list):
            # Direct list response from webclient
            scripts = data
            print(f"DEBUG: Direct list response with {len(scripts)} scripts")
            if len(scripts) > 0:
                print(f"DEBUG: First script sample: {scripts[0]}")
            return scripts
        elif isinstance(data, dict):
            # Nested dict response from API
            print(f"DEBUG: Dict response with keys: {data.keys()}")
            scripts = data.get('data') or data.get('scripts') or []
            if isinstance(scripts, dict):
                scripts = scripts.get('data') or scripts.get('scripts') or []
            print(f"DEBUG: Parsed scripts type: {type(scripts)}")
            print(f"DEBUG: Number of scripts: {len(scripts) if isinstance(scripts, list) else 'N/A'}")
            if isinstance(scripts, list) and len(scripts) > 0:
                print(f"DEBUG: First script sample: {scripts[0]}")
            return scripts
        
        return []
    
    def _webclient_list_scripts(self):
        """List scripts using direct webclient endpoint."""
        import urllib.request
        import urllib.error
        
        if not hasattr(self, 'opener'):
            return None
        
        url = f"{self.base_url}/webclient/list_scripts/"
        req = urllib.request.Request(url)
        
        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)
        
        try:
            response = self.opener.open(req, timeout=10)
            data = json.loads(response.read().decode('utf-8'))
            print(f"DEBUG: Webclient response: {data}")
            return data
        except urllib.error.HTTPError as e:
            print(f"DEBUG: Webclient API error ({e.code}): {e.reason}")
            return None
        except Exception as e:
            print(f"DEBUG: Webclient API error: {e}")
            return None

    def _webclient_annotations(self, image_id):
        """Fetch annotations using webclient API as a fallback."""
        import urllib.request
        import urllib.error
        import urllib.parse

        if not hasattr(self, 'opener'):
            return None

        query = urllib.parse.urlencode({
            "image": image_id,
            "type": "FileAnnotation",
        })
        url = f"{self.base_url}/webclient/api/annotations/?{query}"
        req = urllib.request.Request(url)

        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)

        try:
            response = self.opener.open(req, timeout=10)
            return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"DEBUG: Webclient annotations error ({e.code}): {e.reason}")
            return None
        except Exception as e:
            print(f"DEBUG: Webclient annotations error: {e}")
            return None

    def _extract_file_annotation_ids(self, annotation_data):
        if not annotation_data:
            return set()

        annotations = []
        if isinstance(annotation_data, list):
            annotations = annotation_data
        elif isinstance(annotation_data, dict):
            annotations = (
                annotation_data.get('data', {}).get('annotations')
                or annotation_data.get('annotations')
                or annotation_data.get('data')
                or []
            )

        file_ann_ids = set()
        for annotation in annotations:
            ann_type = annotation.get('@type') or annotation.get('type') or ""
            if "FileAnnotation" in ann_type:
                ann_id = annotation.get('@id') or annotation.get('id')
                if ann_id is not None:
                    file_ann_ids.add(ann_id)
        return file_ann_ids

    def get_image_file_annotations(self, image_id):
        """Return file annotation IDs for an image with fallbacks."""
        webclient_data = self._webclient_annotations(image_id)
        return self._extract_file_annotation_ids(webclient_data)

    def _get_first_webclient_response(self, endpoints):
        for endpoint, params in endpoints:
            data = self._webclient_api_request(endpoint, params=params)
            if data:
                return data
        return None

    def _extract_objects(self, data, preferred_keys=None):
        if not data:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if preferred_keys:
                for key in preferred_keys:
                    if key in data:
                        return data.get(key) or []

                nested_data = data.get('data')
                if isinstance(nested_data, dict):
                    for key in preferred_keys:
                        if key in nested_data:
                            return nested_data.get(key) or []

            return (
                data.get('data')
                or data.get('objects')
                or data.get('projects')
                or data.get('datasets')
                or data.get('images')
                or []
            )
        return []

    def find_script_id(self, script_name):
        """Find script ID by matching script name or path."""
        print(f"\nDEBUG: Searching for script: '{script_name}'")
        scripts_list = self.list_scripts()
        print(f"DEBUG: Total categories to search: {len(scripts_list)}")
        
        normalized_name = os.path.splitext(script_name)[0]
        print(f"DEBUG: Normalized name: '{normalized_name}'")
        
        # Flatten nested structure if scripts are grouped by category
        flat_scripts = []
        for item in scripts_list:
            # Check if this is a category with nested scripts
            if 'ul' in item and isinstance(item['ul'], list):
                category_name = item.get('name', 'unknown')
                print(f"DEBUG: Found category '{category_name}' with {len(item['ul'])} scripts")
                flat_scripts.extend(item['ul'])
            else:
                # Direct script item
                flat_scripts.append(item)
        
        print(f"DEBUG: Total flattened scripts: {len(flat_scripts)}")
        
        for idx, item in enumerate(flat_scripts):
            name = item.get('name') or item.get('Name') or item.get('scriptName')
            path = item.get('path') or item.get('Path')
            sid = item.get('id') or item.get('@id')
            
            if idx < 5:  # Print first 5 scripts for debugging
                print(f"DEBUG: Script {idx}: name='{name}', path='{path}', id={sid}")
            
            # Check if this is IMS_Export
            if name and 'IMS_Export' in name:
                print(f"DEBUG: FOUND IMS_Export by name: {name}, ID: {sid}")
            if path and 'IMS_Export' in path:
                print(f"DEBUG: FOUND IMS_Export by path: {path}, ID: {sid}")
            
            if not sid:
                continue
            if name == script_name or path == script_name:
                print(f"DEBUG: MATCH by exact name/path!")
                return sid
            if name and os.path.basename(name) == script_name:
                print(f"DEBUG: MATCH by basename(name)!")
                return sid
            if path and os.path.basename(path) == script_name:
                print(f"DEBUG: MATCH by basename(path)!")
                return sid
            if normalized_name:
                if name and os.path.splitext(os.path.basename(name))[0] == normalized_name:
                    print(f"DEBUG: MATCH by normalized name!")
                    return sid
                if path and os.path.splitext(os.path.basename(path))[0] == normalized_name:
                    print(f"DEBUG: MATCH by normalized path!")
                    return sid
        
        print(f"DEBUG: NO MATCH FOUND for '{script_name}'")
        return None

    def run_script(self, script_id, inputs):
        """Run a script with provided inputs."""
        import urllib.request
        import urllib.error
        import urllib.parse
        
        if not hasattr(self, 'opener'):
            return None
        
        # Use webclient endpoint for running scripts
        url = f"{self.base_url}/webclient/script_run/{script_id}/"
        
        # Convert inputs to the format expected by webclient
        # Format: key=value pairs in the POST data
        data = urllib.parse.urlencode(inputs).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)
            req.add_header('Referer', url)
        
        try:
            print(f"DEBUG: Posting to {url} with inputs: {inputs}")
            response = self.opener.open(req, timeout=30)
            raw = response.read()
            print(f"DEBUG: Script run response: {raw[:200]}")
            
            if not raw:
                return None
            
            try:
                result = json.loads(raw.decode('utf-8'))
                print(f"DEBUG: Parsed run result: {result}")
                return result
            except Exception:
                # Response might not be JSON
                print(f"DEBUG: Non-JSON response")
                return None
                
        except urllib.error.HTTPError as e:
            print(f"DEBUG: Script run error ({e.code}): {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                print(f"DEBUG: Error body: {error_body}")
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"DEBUG: Script run exception: {e}")
            return None

    def poll_activity(self, job_id, timeout=900, interval=2):
        """Poll a script activity until completion via webclient."""
        import time
        import urllib.request
        import urllib.error
        
        if not hasattr(self, 'opener'):
            return None
        
        # Extract just the UUID from the Ice proxy string if needed
        # Format: ProcessCallback/UUID -t -e 1.1:tcp...
        job_uuid = job_id
        if '/' in job_id:
            parts = job_id.split('/')
            if len(parts) >= 2:
                # Get the UUID part
                uuid_part = parts[1].split()[0]  # Get first token after /
                job_uuid = uuid_part
                print(f"DEBUG: Extracted UUID: {job_uuid}")
        
        url = f"{self.base_url}/webclient/activities/json/"
        
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(url)
                if hasattr(self, 'csrf_token'):
                    req.add_header('X-CSRFToken', self.csrf_token)
                
                response = self.opener.open(req, timeout=10)
                data = json.loads(response.read().decode('utf-8'))
                
                # Look for our job in the activities list
                activities = data.get('activities', [])
                for activity in activities:
                    act_id = str(activity.get('id', ''))
                    # Match by UUID
                    if job_uuid in act_id or act_id in job_id:
                        status = str(activity.get('status', '')).lower()
                        print(f"DEBUG: Found activity, status: {status}")
                        
                        if status in ['finished', 'success', 'complete', 'done', 'succeeded']:
                            print("DEBUG: Activity completed successfully")
                            return activity
                        elif status in ['failed', 'error', 'cancelled', 'canceled']:
                            print(f"DEBUG: Activity failed with status: {status}")
                            return activity
                
                # Activity not found or still running
                print(f"DEBUG: Activity not finished yet, waiting...")
                time.sleep(interval)
                
            except Exception as e:
                print(f"DEBUG: Poll error: {e}")
                time.sleep(interval)
        
        print("DEBUG: Polling timed out")
        return None

    def list_projects(self):
        """List all projects."""
        data = self._get_first_webclient_response([
            ("projects/", None),
            ("containers/", {"type": "project"}),
            ("objects/", {"type": "project"}),
        ])
        projects = self._extract_objects(data, preferred_keys=['projects'])
        return [{
            'id': p.get('@id') or p.get('id'),
            'name': p.get('Name') or p.get('name')
        } for p in projects if p]

    def list_datasets(self, project_id):
        """List datasets in a project."""
        data = self._get_first_webclient_response([
            (f"projects/{project_id}/datasets/", None),
            ("containers/", {"type": "dataset", "parent": project_id}),
            ("objects/", {"type": "dataset", "parent": project_id}),
        ])
        datasets = self._extract_objects(data, preferred_keys=['datasets'])
        return [{
            'id': d.get('@id') or d.get('id'),
            'name': d.get('Name') or d.get('name')
        } for d in datasets if d]

    def list_images(self, dataset_id):
        """List images in a dataset."""
        data = self._get_first_webclient_response([
            (f"datasets/{dataset_id}/images/", None),
            ("containers/", {"type": "image", "parent": dataset_id}),
            ("objects/", {"type": "image", "parent": dataset_id}),
        ])
        images = self._extract_objects(data, preferred_keys=['images'])
        return [{
            'id': img.get('@id') or img.get('id'),
            'name': img.get('Name') or img.get('name'),
            'sizeX': (img.get('Pixels') or img.get('pixels') or {}).get('SizeX', 0),
            'sizeY': (img.get('Pixels') or img.get('pixels') or {}).get('SizeY', 0),
            'sizeZ': (img.get('Pixels') or img.get('pixels') or {}).get('SizeZ', 1),
            'sizeC': (img.get('Pixels') or img.get('pixels') or {}).get('SizeC', 1),
            'sizeT': (img.get('Pixels') or img.get('pixels') or {}).get('SizeT', 1),
        } for img in images]

    def download_ims_export(self, image_id, download_dir, fallback_name="export.ims"):
        """
        Run IMS_Export script and download the resulting IMS file attachment.
        
        This method:
        1. Finds and runs the IMS_Export.py script on the OMERO server
        2. Polls for file annotation to appear (script runs asynchronously)
        3. Downloads the file attachment
        4. Saves it to the local download directory
        
        Returns:
            str: Path to the downloaded file, or None on failure
        """
        import urllib.request
        import urllib.error
        import time
        
        try:
            # Step 1: Find the IMS_Export script
            print("Finding IMS_Export script...")
            script_id = self.find_script_id("IMS_Export.py")
            if not script_id:
                print("ERROR: IMS_Export.py script not found on server")
                print("Available scripts:")
                for s in self.list_scripts():
                    print(f"  - {s.get('name')} (ID: {s.get('id')})")
                raise RuntimeError("IMS_Export.py script not found. Please ensure it's installed on the OMERO server.")
            
            print(f"Found IMS_Export script (ID: {script_id})")
            
            # Step 2: Get existing annotations before running script
            print(f"Checking existing annotations on image {image_id}...")
            existing_file_ann_ids = self.get_image_file_annotations(image_id)
            print(f"Found {len(existing_file_ann_ids)} existing file annotations")
            
            # Step 3: Run the script
            print(f"Running IMS export for image {image_id}...")
            run_response = self.run_script(script_id, {"Image_ID": image_id})
            if not run_response:
                raise RuntimeError("Failed to start IMS export script")
            
            print(f"Script submitted. Waiting for export to complete...")
            
            # Step 4: Poll for new file annotation to appear (up to 60 minutes)
            timeout = 3600  # 60 minutes
            interval = 5  # Check every 5 seconds
            deadline = time.time() + timeout
            file_annotation_id = None
            
            poll_count = 0
            while time.time() < deadline:
                poll_count += 1
                if poll_count % 6 == 0:  # Print status every 30 seconds
                    elapsed = int(time.time() - (deadline - timeout))
                    print(f"Still waiting... ({elapsed}s elapsed)")
                
                # Check for new file annotations
                current_file_ann_ids = self.get_image_file_annotations(image_id)
                new_file_ann_ids = current_file_ann_ids - existing_file_ann_ids
                if new_file_ann_ids:
                    file_annotation_id = next(iter(new_file_ann_ids))
                    print(f"Found new file annotation: {file_annotation_id}")

                if file_annotation_id:
                    break
                
                time.sleep(interval)
            
            if not file_annotation_id:
                raise RuntimeError(
                    f"IMS export timed out after {timeout} seconds. "
                    "No new file annotation was created. Check OMERO server logs for script errors."
                )
            
            print(f"Export completed! File attachment ID: {file_annotation_id}")
            
            # Step 5: Get the original file ID from the annotation
            annotation_data = self._webclient_api_request(
                f"annotations/{file_annotation_id}/"
            )
            if not annotation_data:
                raise RuntimeError(f"Could not retrieve file annotation {file_annotation_id}")

            annotation_payload = annotation_data.get('data') or annotation_data
            file_obj = annotation_payload.get('file') or {}
            if not file_obj:
                raise RuntimeError(f"File annotation {file_annotation_id} has no file object")
            
            original_file_id = file_obj.get('id') or file_obj.get('@id')
            original_filename = file_obj.get('name') or file_obj.get('Name') or fallback_name
            
            if not original_file_id:
                raise RuntimeError(f"File annotation has no original file ID")
            
            print(f"Original file: {original_filename} (ID: {original_file_id})")
            
            # Step 6: Download the file via the annotation download endpoint
            download_url = f"{self.base_url}/webclient/annotation/{file_annotation_id}/"
            print(f"Downloading from: {download_url}")
            
            # Ensure download directory exists
            os.makedirs(download_dir, exist_ok=True)
            
            # Sanitize filename
            safe_filename = re.sub(r'[^\w\s.-]', '_', original_filename)
            local_path = os.path.join(download_dir, safe_filename)
            
            # Download with progress
            req = urllib.request.Request(download_url)
            
            with self.opener.open(req, timeout=300) as response:
                total_size = int(response.headers.get('content-length', 0))
                
                print(f"Downloading {safe_filename} ({total_size / (1024*1024):.1f} MB)...")
                
                downloaded = 0
                chunk_size = 8192
                
                with open(local_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"  Progress: {percent:.1f}% ({downloaded / (1024*1024):.1f} MB)", end='\r')
                
                print()  # New line after progress
            
            if not os.path.exists(local_path):
                raise RuntimeError(f"Download completed but file not found at {local_path}")
            
            file_size = os.path.getsize(local_path)
            if file_size == 0:
                raise RuntimeError("Downloaded file is empty")
            
            print(f"Successfully downloaded: {local_path} ({file_size / (1024*1024):.1f} MB)")
            return local_path
            
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode('utf-8')
            except:
                pass
            print(f"HTTP Error {e.code}: {e.reason}")
            if error_body:
                print(f"Error details: {error_body}")
            raise RuntimeError(f"Download failed: HTTP {e.code} - {e.reason}")
            
        except Exception as e:
            print(f"Download error: {e}")
            import traceback
            traceback.print_exc()
            raise


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_ims_file(file_path):
    """Check if file is a valid IMS (HDF5) file."""
    if not os.path.exists(file_path):
        return False
    
    if os.path.getsize(file_path) < 8:
        return False
    
    try:
        with open(file_path, 'rb') as f:
            signature = f.read(8)
            return signature == b'\x89HDF\r\n\x1a\n'
    except Exception:
        return False


def open_file_in_imaris(file_path, imaris_app):
    """Open a file in Imaris."""
    if not imaris_app:
        print(f"No Imaris application instance. File saved at: {file_path}")
        return True
    
    try:
        print(f"Opening in Imaris: {file_path}")
        imaris_app.FileOpen(file_path, "")
        print("Successfully opened in Imaris")
        return True
    except Exception as e:
        print(f"Error opening in Imaris: {e}")
        return False


# =============================================================================
# GUI DIALOG
# =============================================================================

class OMEROBrowserDialog:
    """GUI for browsing and loading OMERO images into Imaris."""
    
    def __init__(self, imaris):
        self.imaris = imaris
        self.client = None
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
        self.temp_files = []
        
        # Get export directory
        self.export_dir = self._get_export_dir()
        
        self.root = tk.Tk()
        self.root.title("OMERO → Imaris Connector")
        self.root.geometry("1000x700")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self._build_ui()
    
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
        
        tk.Label(conn_frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.user_entry = tk.Entry(conn_frame, width=25)
        self.user_entry.insert(0, "test")
        self.user_entry.grid(row=1, column=1, pady=5, padx=5)
        
        tk.Label(conn_frame, text="Password:").grid(row=1, column=2, sticky=tk.W, pady=5)
        self.pass_entry = tk.Entry(conn_frame, show="*", width=25)
        self.pass_entry.grid(row=1, column=3, columnspan=2, pady=5, padx=5, sticky=tk.W)
        
        tk.Button(conn_frame, text="Connect", command=self._connect,
                 bg='#3498db', fg='white', font=('Arial', 10, 'bold'),
                 width=15).grid(row=0, column=5, rowspan=2, padx=10, pady=5)
        
        # Browser
        browser = tk.Frame(self.root)
        browser.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Projects
        p_frame = tk.LabelFrame(browser, text="Projects")
        p_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        p_scroll = tk.Scrollbar(p_frame)
        p_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.plist = tk.Listbox(p_frame, yscrollcommand=p_scroll.set, exportselection=False)
        self.plist.pack(fill=tk.BOTH, expand=True)
        p_scroll.config(command=self.plist.yview)
        self.plist.bind('<<ListboxSelect>>', lambda e: self._sel_proj())
        
        # Datasets
        d_frame = tk.LabelFrame(browser, text="Datasets")
        d_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        d_scroll = tk.Scrollbar(d_frame)
        d_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.dlist = tk.Listbox(d_frame, yscrollcommand=d_scroll.set, exportselection=False)
        self.dlist.pack(fill=tk.BOTH, expand=True)
        d_scroll.config(command=self.dlist.yview)
        self.dlist.bind('<<ListboxSelect>>', lambda e: self._sel_ds())
        
        # Images
        i_frame = tk.LabelFrame(browser, text="Images")
        i_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        i_scroll = tk.Scrollbar(i_frame)
        i_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.ilist = tk.Listbox(i_frame, yscrollcommand=i_scroll.set, exportselection=False)
        self.ilist.pack(fill=tk.BOTH, expand=True)
        i_scroll.config(command=self.ilist.yview)
        
        # Actions
        actions = tk.Frame(self.root)
        actions.pack(fill=tk.X, padx=10, pady=10)
        
        self.load_btn = tk.Button(actions, text="Load into Imaris", 
                                  command=self._load,
                                  bg='#27ae60', fg='white', 
                                  font=('Arial', 12, 'bold'), 
                                  state=tk.DISABLED, height=2)
        self.load_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        tk.Button(actions, text="Close", command=self._on_close,
                 bg='#95a5a6', fg='white', 
                 font=('Arial', 12, 'bold'), height=2).pack(side=tk.LEFT, padx=2)
        
        # Status
        self.status = tk.Label(self.root, text="Ready - Please connect to OMERO", 
                              bg='#ecf0f1', anchor=tk.W, padx=10, pady=5,
                              font=('Arial', 9))
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _get_export_dir(self):
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        if os.path.isdir(desktop):
            base = desktop
        else:
            base = tempfile.gettempdir()
        export_dir = os.path.join(base, "ImarisOMEROExports")
        os.makedirs(export_dir, exist_ok=True)
        return export_dir

    def _set_status(self, text, color='#ecf0f1'):
        def update():
            self.status.config(text=text, bg=color)
            self.root.update_idletasks()
        self.root.after(0, update)

    def _show_error(self, title, message):
        self.root.after(0, lambda: messagebox.showerror(title, message))

    def _show_info(self, title, message):
        self.root.after(0, lambda: messagebox.showinfo(title, message))
    
    def _connect(self):
        h = self.host_entry.get().strip()
        p = self.port_entry.get().strip()
        u = self.user_entry.get().strip()
        pw = self.pass_entry.get()
        
        if not all([h, p, u, pw]):
            messagebox.showwarning("Missing Fields", "Please fill all connection fields")
            return
        
        self._set_status("Connecting to OMERO...", "#fff3cd")
        
        scheme = "https" if self.https_var.get() else "http"
        self.client = OMEROWebClient(h, int(p), u, pw, scheme=scheme)
        
        if self.client.connect():
            self._set_status(f"✓ Connected to {h}:{p} as {u}", "#d4edda")
            self._load_projects()
            self.load_btn.config(state=tk.NORMAL)
        else:
            self._set_status("✗ Connection failed", "#f8d7da")
            messagebox.showerror("Connection Failed", 
                               "Cannot connect to OMERO server.\n"
                               "Please check your credentials.")
    
    def _load_projects(self):
        self.plist.delete(0, tk.END)
        self.projects_data = self.client.list_projects()
        for p in self.projects_data:
            self.plist.insert(tk.END, p['name'])
    
    def _sel_proj(self):
        sel = self.plist.curselection()
        if not sel:
            return
        p = self.projects_data[sel[0]]
        if not hasattr(self, '_pid') or self._pid != p['id']:
            self._pid = p['id']
            self._load_ds()
    
    def _sel_ds(self):
        sel = self.dlist.curselection()
        if not sel:
            return
        d = self.datasets_data[sel[0]]
        self._load_imgs(d['id'])
    
    def _load_ds(self):
        self.dlist.delete(0, tk.END)
        self.ilist.delete(0, tk.END)
        self.datasets_data = self.client.list_datasets(self._pid)
        for d in self.datasets_data:
            self.dlist.insert(tk.END, d['name'])
    
    def _load_imgs(self, did):
        self.ilist.delete(0, tk.END)
        self.images_data = self.client.list_images(did)
        for img in self.images_data:
            size_info = f"{img['sizeX']}×{img['sizeY']}×{img['sizeZ']}"
            if img['sizeC'] > 1:
                size_info += f" C{img['sizeC']}"
            if img['sizeT'] > 1:
                size_info += f" T{img['sizeT']}"
            self.ilist.insert(tk.END, f"{img['name']} [{size_info}]")
    
    def _load(self):
        sel = self.ilist.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select an image")
            return
        
        img = self.images_data[sel[0]]
        
        if not messagebox.askyesno("Confirm Load", 
                                   f"Download and open:\n{img['name']}\n\n"
                                   f"Conversion will run on the server if needed."):
            return
        
        self.load_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._load_worker, args=(img,), daemon=True).start()
    
    def _load_worker(self, img):
        try:
            self._set_status(f"Exporting IMS for {img['name']}...", "#fff3cd")

            # Download directory
            download_dir = os.path.join(self.export_dir, f"img_{img['id']}")
            os.makedirs(download_dir, exist_ok=True)

            self._set_status("Running server-side IMS export...", "#fff3cd")
            downloaded_file = self.client.download_ims_export(
                img['id'],
                download_dir,
                fallback_name=f"img_{img['id']}.ims"
            )
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise RuntimeError("Failed to download IMS export from OMERO.")

            if not is_ims_file(downloaded_file):
                raise RuntimeError(
                    "Downloaded file is not a valid IMS (HDF5) file. "
                    "Refusing to open to avoid triggering Imaris File Converter. "
                    "Please verify that the server-side conversion completed successfully."
                )
            
            self._set_status(f"Downloaded: {os.path.basename(downloaded_file)}", "#d4edda")
            print(f"Downloaded: {downloaded_file}")
            
            self.temp_files.append(downloaded_file)
            
            # Open in Imaris
            self._set_status("Opening IMS in Imaris...", "#fff3cd")
            
            success = open_file_in_imaris(downloaded_file, self.imaris)
            
            if success:
                self._set_status("✓ Opened in Imaris", "#d4edda")
                self._show_info("Success", 
                              f"File opened in Imaris!\n"
                              f"Opened IMS file: {downloaded_file}")
            else:
                raise RuntimeError(f"Failed to open in Imaris.\n\nFile: {downloaded_file}")
            
        except Exception as e:
            self._set_status("✗ Failed", "#f8d7da")
            self._show_error("Error", str(e))
            import traceback
            traceback.print_exc()
        finally:
            self.load_btn.config(state=tk.NORMAL)
    
    def show(self):
        self.root.mainloop()


# =============================================================================
# XTENSION ENTRY POINT
# =============================================================================

def XTOmeroConnector(aImarisId):
    """Called by Imaris."""
    vImaris = None
    try:
        import ImarisLib
        vImaris = ImarisLib.GetApplication(aImarisId)
    except:
        vImaris = aImarisId if not isinstance(aImarisId, int) else None
    
    dialog = OMEROBrowserDialog(vImaris)
    dialog.show()


if __name__ == "__main__":
    OMEROBrowserDialog(None).show()
