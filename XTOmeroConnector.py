import traceback
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
import datetime
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

# Default timeout/poll values for client-side export polling.
# These must NOT depend on server-side packages (omero_plugin_common)
# because this script runs inside Imaris on the user's machine.
EXPORT_TIMEOUT = 3600       # seconds
EXPORT_POLL_INTERVAL = 2.0  # seconds
_XT_LOG_PATH = None


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
    try:
        with open(file_path, "rb") as f:
            header = f.read(len(hdf5_signature))
        return header == hdf5_signature
    except Exception:
        return False


def open_file_in_imaris(file_path, imaris_app):
    """Attempt to open a file in Imaris using available API methods."""
    if imaris_app is None:
        print("Imaris application handle is not available.")
        return False

    last_error = None
    candidates = [
        ("FileOpen", (file_path, "")),
        ("FileOpen", (file_path,)),
        ("OpenFile", (file_path,)),
        ("LoadFile", (file_path,)),
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
        self.opener = None
        self.csrf_token = None
        self.session_id = None
        self.session_key = None

    def _build_base_url(self, host, port, scheme):
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"{scheme}://{host}:{port}"

    def _build_cookie_header(self):
        """Build Cookie header string from stored session credentials.
        
        This ensures cookies are always sent, regardless of cookie jar matching issues.
        """
        cookies = []
        if self.session_id:
            cookies.append(f'sessionid={self.session_id}')
        if self.csrf_token:
            cookies.append(f'csrftoken={self.csrf_token}')
        return '; '.join(cookies) if cookies else None

    def _create_request_with_cookies(self, url, data=None, method=None):
        """Create a request with explicit cookie headers.
        
        This bypasses potential issues with automatic cookie jar matching.
        """
        req = urllib.request.Request(url, data=data, method=method)
        
        # Always add cookies explicitly
        cookie_header = self._build_cookie_header()
        if cookie_header:
            req.add_header('Cookie', cookie_header)
        
        # Add CSRF token header for POST requests
        if method == 'POST' or data is not None:
            if self.csrf_token:
                req.add_header('X-CSRFToken', self.csrf_token)
            req.add_header('Referer', self.base_url)
        
        # Add common headers to prevent caching issues
        req.add_header('Cache-Control', 'no-cache')
        req.add_header('Pragma', 'no-cache')
        req.add_header('User-Agent', 'OMERO-ImarisXT/1.0')
        
        return req

    def _extract_cookies_from_jar(self):
        """Extract session and CSRF cookies from the cookie jar."""
        if not self.cookie_jar:
            return
        
        for cookie in self.cookie_jar:
            if cookie.name == 'sessionid':
                self.session_id = cookie.value
                self.session_key = cookie.value
                _xt_debug(f"Extracted sessionid: {cookie.value[:8]}...")
            elif cookie.name == 'csrftoken':
                self.csrf_token = cookie.value
                _xt_debug(f"Extracted csrftoken: {cookie.value[:8]}...")

    def _check_login_redirect(self, response, context="request"):
        """Check if a response was redirected to login page.
        
        Returns True if redirected to login (authentication failed).
        """
        final_url = getattr(response, "geturl", lambda: "")()
        if "/webclient/login/" in str(final_url):
            _xt_debug(f"Authentication failed during {context}: redirected to {final_url}")
            return True
        return False

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
            req.add_header('User-Agent', 'OMERO-ImarisXT/1.0')
            response = self.opener.open(req, timeout=30)
            _xt_debug(f"Login GET response={getattr(response, 'status', 'unknown')}")
            
            # Extract CSRF token from cookies
            self._extract_cookies_from_jar()
            
            if not self.csrf_token:
                _xt_debug("Login failed: CSRF token missing after GET")
                return False
            
            # POST login credentials
            data = urllib.parse.urlencode({
                'username': self.username,
                'password': self.password,
                'server': 1,
                'csrfmiddlewaretoken': self.csrf_token
            }).encode()
            
            req = urllib.request.Request(login_url, data=data, method='POST')
            req.add_header('Referer', login_url)
            req.add_header('X-CSRFToken', self.csrf_token)
            req.add_header('User-Agent', 'OMERO-ImarisXT/1.0')
            # Also add existing cookies explicitly
            cookie_header = self._build_cookie_header()
            if cookie_header:
                req.add_header('Cookie', cookie_header)
            
            response = self.opener.open(req, timeout=30)
            _xt_debug(f"Login POST response={getattr(response, 'status', 'unknown')}")
            
            # Extract session cookie from response
            self._extract_cookies_from_jar()
            
            if self.session_id:
                _xt_debug(f"Login succeeded; session cookie received (sessionid={self.session_id[:8]}...)")
                return True
            
            _xt_debug("Login failed: session cookie missing after POST")
            return False
            
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
            return json.loads(response.read().decode('utf-8'))
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
            data = json.dumps(payload).encode('utf-8')

        req = self._create_request_with_cookies(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')

        try:
            response = self.opener.open(req, timeout=30)
            
            if self._check_login_redirect(response, "API POST"):
                return None
            
            _xt_debug(f"API POST url={url} response={getattr(response, 'status', 'unknown')}")
            raw = response.read()
            if not raw:
                return None
            try:
                return json.loads(raw.decode('utf-8'))
            except Exception:
                return None
        except urllib.error.HTTPError as e:
            _xt_debug(f"API POST error ({e.code}): {e.reason}")
            try:
                _xt_debug(e.read().decode('utf-8'))
            except Exception:
                pass
            return None
        except Exception as e:
            _xt_debug(f"API POST error: {e}")
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
            scripts = data.get('data') or data.get('scripts') or []
            if isinstance(scripts, dict):
                scripts = scripts.get('data') or scripts.get('scripts') or []
            return scripts
        return []

    def find_script_id(self, script_name):
        """Find script ID by matching script name or path."""
        scripts_list = self.list_scripts()
        normalized_name = os.path.splitext(script_name)[0]
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
            if normalized_name:
                if name and os.path.splitext(os.path.basename(name))[0] == normalized_name:
                    return sid
                if path and os.path.splitext(os.path.basename(path))[0] == normalized_name:
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
            download_dir = os.path.join(os.path.expanduser("~"), "Downloads", "OMERO_Imaris_Exports")

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
                        
                        poll_body = poll_response.read().decode("utf-8", errors="replace")
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
                    if e.code == 401 or e.code == 403:
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
                    error_msg = poll_payload.get('error', 'unknown error')
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
            
            with self.opener.open(download_req, timeout=EXPORT_TIMEOUT + 60) as response:
                if self._check_login_redirect(response, "IMS export download"):
                    raise RuntimeError(
                        "Not authenticated to OMERO.web (redirected to login) while downloading IMS export."
                    )
                    
                cd = response.headers.get("Content-Disposition", "")
                filename = None
                m = re.search(r'filename\*=UTF-8\'\'([^;]+)', cd)
                if m:
                    filename = urllib.parse.unquote(m.group(1))
                else:
                    m = re.search(r'filename="([^"]+)"', cd)
                    if m:
                        filename = m.group(1)

                if not filename:
                    filename = fallback_name
                    if not filename.lower().endswith(".ims"):
                        filename += ".ims"

                safe_filename = re.sub(r'[^\w\s.-]', "_", filename).strip()
                if not safe_filename:
                    safe_filename = fallback_name

                local_path = os.path.join(download_dir, safe_filename)

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
                                f"  Progress: {percent:.1f}% ({downloaded / (1024*1024):.1f} MB)",
                                end="\r",
                            )

                if total_size:
                    print()

            if not os.path.exists(local_path):
                raise RuntimeError(f"Download completed but file not found at {local_path}")
            if os.path.getsize(local_path) <= 0:
                raise RuntimeError("Downloaded IMS file is empty")

            _xt_debug(f"IMS export downloaded OK: {local_path}")
            return local_path

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"IMS export HTTPError {e.code}: {e.reason}\n{body[:2000]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"IMS export failed (URLError): {e}") from e

    def _normalize_url(self, url, base_url):
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
            if parsed.netloc != base_parsed.netloc or parsed.scheme != base_parsed.scheme:
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
            _xt_debug(f"Load worker starting image_id={img['id']} name={img['name']}")
            self._set_status(f"Exporting IMS for {img['name']}...", "#fff3cd")

            # Download directory
            download_dir = os.path.join(self.export_dir, f"img_{img['id']}")
            os.makedirs(download_dir, exist_ok=True)

            self._set_status("Running server-side IMS export...", "#fff3cd")
            downloaded_file = self.client.download_ims_export(
                img['id'],
                download_dir,
                fallback_name=f"img_{img['id']}.ims",
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
            _xt_debug(f"Downloaded: {downloaded_file}")
            
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
            _xt_debug(f"Load worker failed: {e}")
        finally:
            self.load_btn.config(state=tk.NORMAL)
    
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
    return os.path.join(tempfile.gettempdir(), f"XTOmeroConnector_{ts}.log")


def _xt_write_log(log_path, msg):
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(msg)
            if not msg.endswith("\n"):
                f.write("\n")
    except Exception:
        pass


def _xt_show_fatal(title, message):
    try:
        import tkinter.messagebox as _mb
        _mb.showerror(title, message)
    except Exception:
        print(title + ": " + message)


def XTOmeroConnector(aImarisId):
    """Called by Imaris."""
    log_path = _xt_log_path()
    global _XT_LOG_PATH
    _XT_LOG_PATH = log_path
    try:
        _xt_write_log(log_path, "=== XTOmeroConnector starting ===")
        _xt_write_log(log_path, f"Python: {sys.version}")
        _xt_write_log(log_path, f"argv: {sys.argv}")
        _xt_write_log(log_path, f"cwd: {os.getcwd()}")

        vImaris = None
        try:
            import ImarisLib
            vImaris = ImarisLib.GetApplication(aImarisId)
        except Exception:
            # When run outside Imaris (manual debug), aImarisId may be None or already an app object.
            vImaris = aImarisId if not isinstance(aImarisId, int) else None

        dialog = OMEROBrowserDialog(vImaris)
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
        except Exception:
            pass


if __name__ == "__main__":
    # Manual debug mode (outside Imaris): keep the console open on error.
    try:
        XTOmeroConnector(None)
    except Exception as e:
        print("Fatal:", e)
        try:
            input("Press ENTER to close...")
        except Exception:
            pass
