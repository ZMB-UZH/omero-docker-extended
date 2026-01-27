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
Downloads ORIGINAL files from OMERO and opens in Imaris.
Imaris auto-converts to IMS format when opening.
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
    
    def __init__(self, host, port, username, password):
        self.base_url = f"http://{host}:{port}"
        self.api_url = f"{self.base_url}/api/v0"
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.session = None
        
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
        
        if not hasattr(self, 'opener'):
            return None
            
        url = f"{self.api_url}/{endpoint}"
        req = urllib.request.Request(url)
        
        if hasattr(self, 'csrf_token'):
            req.add_header('X-CSRFToken', self.csrf_token)
        
        try:
            response = self.opener.open(req, timeout=10)
            return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"API error: {e}")
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
    
    def download_original_file(self, image_id, output_dir):
        """
        Download ORIGINAL file from OMERO using webgateway archived_files endpoint.
        Returns path to downloaded file.
        """
        try:
            import urllib.request
            import zipfile
            import io
            
            os.makedirs(output_dir, exist_ok=True)
            
            # Download original file via webgateway
            download_url = f"{self.base_url}/webgateway/archived_files/download/{image_id}/"
            
            print(f"Downloading original file from: {download_url}")
            
            req = urllib.request.Request(download_url)
            if hasattr(self, 'csrf_token'):
                req.add_header('X-CSRFToken', self.csrf_token)
            
            response = self.opener.open(req, timeout=600)
            
            content_type = response.headers.get('Content-Type', '')
            content_disposition = response.headers.get('Content-Disposition', '')
            
            print(f"Content-Type: {content_type}")
            print(f"Content-Disposition: {content_disposition}")
            
            data = response.read()
            
            # Check if it's a zip file
            if content_type == 'application/zip' or b'PK\x03\x04' in data[:4]:
                print("Received ZIP archive, extracting...")
                
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    file_list = zf.namelist()
                    print(f"Files in archive: {file_list}")
                    
                    zf.extractall(output_dir)
                    
                    # Find main image file
                    main_files = [f for f in file_list 
                                 if not f.startswith('__MACOSX') 
                                 and not f.startswith('.')
                                 and not f.endswith('.txt')
                                 and os.path.basename(f)
                                 and not os.path.basename(f).startswith('.')]
                    
                    if main_files:
                        return os.path.join(output_dir, main_files[0])
                    elif file_list:
                        return os.path.join(output_dir, file_list[0])
            else:
                # Single file
                filename = self._extract_filename(content_disposition)
                if not filename:
                    filename = f"image_{image_id}.dat"
                
                file_path = os.path.join(output_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                print(f"Downloaded: {file_path} ({len(data)} bytes)")
                return file_path
            
            return None
            
        except Exception as e:
            print(f"Download error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_filename(self, content_disposition):
        """Extract filename from Content-Disposition header."""
        import urllib.parse
        
        if content_disposition:
            utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
            if utf8_match:
                return urllib.parse.unquote(utf8_match.group(1))
            
            match = re.search(r'filename="?([^"]+)"?', content_disposition)
            if match:
                return match.group(1)
        
        return None
    
    def list_projects(self):
        """List all projects."""
        data = self._api_request('m/projects/')
        if data and 'data' in data:
            return [{'id': p['@id'], 'name': p['Name']} for p in data['data']]
        return []
    
    def list_datasets(self, project_id):
        """List datasets in project."""
        data = self._api_request(f'm/projects/{project_id}/datasets/')
        if data and 'data' in data:
            return [{'id': d['@id'], 'name': d['Name']} for d in data['data']]
        return []
    
    def list_images(self, dataset_id):
        """List images in dataset."""
        data = self._api_request(f'm/datasets/{dataset_id}/images/')
        if data and 'data' in data:
            images = []
            for i in data['data']:
                pixels = i.get('Pixels', {})
                images.append({
                    'id': i['@id'],
                    'name': i['Name'],
                    'sizeX': pixels.get('SizeX', 0),
                    'sizeY': pixels.get('SizeY', 0),
                    'sizeZ': pixels.get('SizeZ', 0),
                    'sizeC': pixels.get('SizeC', 0),
                    'sizeT': pixels.get('SizeT', 0),
                })
            return images
        return []


# =============================================================================
# IMARIS FILE OPENER
# =============================================================================

def open_file_in_imaris(filepath, imaris_app=None):
    """
    Open file in Imaris. If imaris_app is provided, use it. Otherwise launch Imaris.
    Imaris will auto-convert to IMS format when opening.
    """
    if imaris_app and hasattr(imaris_app, 'FileOpen'):
        try:
            print(f"Opening in current Imaris session: {filepath}")
            imaris_app.FileOpen(filepath, "")
            return True
        except Exception as e:
            print(f"Error opening in Imaris: {e}")
            return False
    else:
        # Launch Imaris with file
        import subprocess
        imaris_paths = [
            r"C:\Program Files\Bitplane\Imaris 11.0.0\Imaris.exe",
            r"C:\Program Files\Bitplane\Imaris 10.0.0\Imaris.exe",
            r"C:\Program Files\Bitplane\Imaris 9.9.1\Imaris.exe",
        ]
        
        imaris_exe = None
        for path in imaris_paths:
            if os.path.exists(path):
                imaris_exe = path
                break
        
        if not imaris_exe:
            print("Imaris not found")
            return False
        
        try:
            print(f"Launching Imaris: {imaris_exe} {filepath}")
            subprocess.Popen([imaris_exe, filepath])
            return True
        except Exception as e:
            print(f"Error launching Imaris: {e}")
            return False


# =============================================================================
# GUI
# =============================================================================

class OMEROBrowserDialog:
    """Main GUI."""
    
    def __init__(self, imaris_app):
        self.imaris = imaris_app
        self.client = None
        self.root = tk.Tk()
        self.root.title("OMERO Image Loader")
        self.root.geometry("1000x600")
        
        self.projects_data = []
        self.datasets_data = []
        self.images_data = []
        self.temp_files = []
        
        self.export_dir = self._get_export_dir()
        
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _on_close(self):
        self.root.destroy()
    
    def _build_ui(self):
        # Connection
        conn = tk.LabelFrame(self.root, text="OMERO Connection", font=('Arial', 10, 'bold'))
        conn.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(conn, text="Host:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.host_entry = tk.Entry(conn, width=30)
        self.host_entry.insert(0, "172.23.208.90")
        self.host_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(conn, text="Port:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.port_entry = tk.Entry(conn, width=10)
        self.port_entry.insert(0, "4090")
        self.port_entry.grid(row=0, column=3, padx=5, pady=5)
        
        tk.Label(conn, text="User:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.user_entry = tk.Entry(conn, width=30)
        self.user_entry.insert(0, "test")
        self.user_entry.grid(row=1, column=1, padx=5, pady=5)
        
        tk.Label(conn, text="Pass:").grid(row=1, column=2, sticky=tk.W, padx=5)
        self.pass_entry = tk.Entry(conn, width=30, show="*")
        self.pass_entry.grid(row=1, column=3, padx=5, pady=5)
        
        tk.Button(conn, text="Connect", command=self._connect,
                 bg='#3498db', fg='white', font=('Arial', 10, 'bold')).grid(
                     row=2, column=0, columnspan=4, pady=10)
        
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
        
        self.client = OMEROWebClient(h, int(p), u, pw)
        
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
                                   f"Imaris will auto-convert to IMS format."):
            return
        
        self.load_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._load_worker, args=(img,), daemon=True).start()
    
    def _load_worker(self, img):
        try:
            self._set_status(f"Downloading {img['name']}...", "#fff3cd")
            
            # Download directory
            download_dir = os.path.join(self.export_dir, f"img_{img['id']}")
            os.makedirs(download_dir, exist_ok=True)
            
            # Download original file
            downloaded_file = self.client.download_original_file(img['id'], download_dir)
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise RuntimeError("Failed to download image from OMERO.")
            
            self._set_status(f"Downloaded: {os.path.basename(downloaded_file)}", "#d4edda")
            print(f"Downloaded: {downloaded_file}")
            
            self.temp_files.append(downloaded_file)
            
            # Open in Imaris
            self._set_status(f"Opening in Imaris (will auto-convert to IMS)...", "#fff3cd")
            
            success = open_file_in_imaris(downloaded_file, self.imaris)
            
            if success:
                self._set_status("✓ Opened in Imaris", "#d4edda")
                self._show_info("Success", 
                              f"File opened in Imaris!\n"
                              f"Imaris will auto-convert to IMS format.\n\n"
                              f"Original file: {downloaded_file}")
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
