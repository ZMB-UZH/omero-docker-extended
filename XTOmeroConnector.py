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
        self.api_url = f"{self.base_url}/api/v0"
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
    
    def _api_request(self, endpoint):
        """Make API request."""
        import urllib.request
        import urllib.error

        if not hasattr(self, 'opener'):
            return None
            
        url = f"{self.api_url}/{endpoint}"
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

    def _api_post(self, endpoint, payload=None):
        """POST JSON to OMERO.web API and parse JSON response."""
        import urllib.request
        import urllib.error

        if not hasattr(self, 'opener'):
            return None

        url = f"{self.api_url}/{endpoint}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)

        try:
            response = self.opener.open(req, timeout=30)
            raw = response.read()
            if not raw:
                return None
            try:
                return json.loads(raw.decode('utf-8'))
            except Exception:
                return None
        except urllib.error.HTTPError as e:
            print(f"API POST error ({e.code}): {e.reason}")
            try:
                print(e.read().decode('utf-8'))
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"API POST error: {e}")
            return None

    def get_image_metadata(self, image_id):
        """Get image metadata including original filename."""
        data = self._api_request(f"m/images/{image_id}/")
        if not data:
            return {}
        
        result = {
            'id': image_id,
            'name': data.get('Name', ''),
            'original_file': None,
        }
        
        fileset = data.get("Fileset") or {}
        files = fileset.get("Files") or []
        if files:
            result['original_file'] = files[0].get("Name")
        
        return result

    def list_scripts(self):
        """List available scripts."""
        data = self._api_request("scripts/")
        if data and isinstance(data, dict):
            return data.get('data') or data.get('scripts') or []
        return []

    def find_script_id(self, script_name):
        """Find script ID by matching script name or path."""
        scripts_list = self.list_scripts()
        for item in scripts_list:
            name = item.get('name') or item.get('Name') or item.get('scriptName')
            path = item.get('path') or item.get('Path')
            sid = item.get('id') or item.get('@id')
            if not sid:
                continue
            if name == script_name or path == script_name:
                return sid
            if name and os.path.basename(name) == script_name:
                return sid
            if path and os.path.basename(path) == script_name:
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

    def poll_activity(self, job_id, timeout=900, interval=2):
        """Poll a script activity until completion."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._api_request(f"activities/{job_id}/")
            if not data:
                return None

            status = (data.get('status') or data.get('state') or '').upper()
            if status in {'FINISHED', 'SUCCESS', 'COMPLETE', 'DONE'}:
                return data
            if status in {'FAILED', 'ERROR', 'CANCELLED', 'CANCELED'}:
                return data

            time.sleep(interval)

        return None

    def list_projects(self):
        """List all projects."""
        data = self._api_request("m/projects/")
        if not data:
            return []
        projects = data.get('data') or []
        return [{'id': p['@id'], 'name': p['Name']} for p in projects]

    def list_datasets(self, project_id):
        """List datasets in a project."""
        data = self._api_request(f"m/projects/{project_id}/datasets/")
        if data:
            datasets = data.get('data') or []
            if datasets:
                return [{'id': d['@id'], 'name': d['Name']} for d in datasets]
        data = self._api_request(f"m/projects/{project_id}/")
        if not data:
            return []
        datasets = (
            data.get('data', {}).get('Datasets')
            or data.get('data', {}).get('datasets')
            or []
        )
        return [{'id': d['@id'], 'name': d['Name']} for d in datasets]

    def list_images(self, dataset_id):
        """List images in a dataset."""
        data = self._api_request(f"m/datasets/{dataset_id}/images/")
        if not data:
            return []
        images = data.get('data') or []
        return [{
            'id': img['@id'],
            'name': img['Name'],
            'sizeX': img.get('Pixels', {}).get('SizeX', 0),
            'sizeY': img.get('Pixels', {}).get('SizeY', 0),
            'sizeZ': img.get('Pixels', {}).get('SizeZ', 1),
            'sizeC': img.get('Pixels', {}).get('SizeC', 1),
            'sizeT': img.get('Pixels', {}).get('SizeT', 1),
        } for img in images]

    def download_ims_export(self, image_id, download_dir, fallback_name="export.ims"):
        """
        Run IMS_Export script and download the resulting IMS file attachment.
        
        This method:
        1. Finds and runs the IMS_Export.py script on the OMERO server
        2. Polls until the export job completes
        3. Downloads the file attachment created by the script
        4. Saves it to the local download directory
        
        Returns:
            str: Path to the downloaded file, or None on failure
        """
        import urllib.request
        import urllib.error
        
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
            
            # Step 2: Run the script
            print(f"Running IMS export for image {image_id}...")
            run_response = self.run_script(script_id, {"Image_ID": image_id})
            if not run_response:
                raise RuntimeError("Failed to start IMS export script")
            
            job_id = (
                run_response.get('job_id') 
                or run_response.get('jobId') 
                or run_response.get('id')
            )
            if not job_id:
                raise RuntimeError("Script started but no job ID returned")
            
            print(f"Export job started (Job ID: {job_id})")
            
            # Step 3: Poll until completion
            print("Waiting for export to complete...")
            activity = self.poll_activity(job_id, timeout=900, interval=2)
            
            if not activity:
                raise RuntimeError("Export job timed out (15 minutes)")
            
            status = (activity.get('status') or activity.get('state') or '').upper()
            print(f"Export job status: {status}")
            
            if status in {'FAILED', 'ERROR', 'CANCELLED', 'CANCELED'}:
                message = activity.get('message', 'Unknown error')
                raise RuntimeError(f"Export job failed: {message}")
            
            # Step 4: Get the file annotation from outputs
            outputs = (
                activity.get('outputs') 
                or activity.get('output') 
                or activity.get('results')
                or {}
            )
            
            # Look for File_Annotation in outputs
            file_annotation_id = None
            for key in ['File_Annotation', 'file_annotation', 'FileAnnotation', 'File_Annotation_Id']:
                value = outputs.get(key)
                if value:
                    if isinstance(value, dict):
                        file_annotation_id = value.get('value') or value.get('id') or value.get('@id')
                    else:
                        file_annotation_id = value
                    break
            
            if not file_annotation_id:
                # Fallback: check for direct file ID
                for key in ['File', 'file', 'FileID', 'file_id']:
                    value = outputs.get(key)
                    if value:
                        if isinstance(value, dict):
                            file_annotation_id = value.get('value') or value.get('id')
                        else:
                            file_annotation_id = value
                        break
            
            if not file_annotation_id:
                print(f"ERROR: No file attachment found in job outputs")
                print(f"Available outputs: {list(outputs.keys())}")
                print(f"Output values: {outputs}")
                raise RuntimeError(
                    "IMS export completed but no file attachment was created. "
                    "This likely means the script failed to attach the file properly."
                )
            
            print(f"Found file attachment (ID: {file_annotation_id})")
            
            # Step 5: Get the original file ID from the annotation
            annotation_data = self._api_request(f"m/annotations/{file_annotation_id}/")
            if not annotation_data:
                raise RuntimeError(f"Could not retrieve file annotation {file_annotation_id}")
            
            file_obj = annotation_data.get('data', {}).get('file')
            if not file_obj:
                raise RuntimeError(f"File annotation {file_annotation_id} has no file object")
            
            original_file_id = file_obj.get('id')
            original_filename = file_obj.get('name', fallback_name)
            
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
