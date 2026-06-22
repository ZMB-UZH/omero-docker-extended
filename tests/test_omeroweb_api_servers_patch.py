from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, mock


ORIGINAL_VIEWS_SNIPPET = """\
import traceback
import json

from omeroweb.connector import Server
from omeroweb.api.decorators import json_response


@json_response()
def api_servers(request, api_version, **kwargs):
    \"\"\"List the available servers to connect to.\"\"\"
    servers = []
    for i, obj in enumerate(Server):
        s = {\"id\": i + 1, \"host\": obj.host, \"port\": obj.port}
        if obj.server is not None:
            s[\"server\"] = obj.server
        servers.append(s)
    return {\"data\": servers}
"""


class OmeroWebApiServersPatchTests(TestCase):
    """Test cases for OMERO.web API server discovery patch tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `OmeroWebApiServersPatchTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.patch_script = cls.repo_root / "docker" / "patch_omeroweb_api_servers.py"

    def test_patch_script_makes_server_discovery_request_aware(self) -> None:
        """Verify the patch script makes OMERO.web server discovery request-aware.

        Inputs: repository fixtures. Output: fails on regressions in api server discovery patch behavior.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_path = Path(tmp_dir) / "views.py"
            target_path.write_text(ORIGINAL_VIEWS_SNIPPET, encoding="utf-8")

            subprocess.run(
                [sys.executable, str(self.patch_script), str(target_path)],
                check=True,
            )
            subprocess.run(
                [sys.executable, str(self.patch_script), str(target_path)],
                check=True,
            )

            patched_text = target_path.read_text(encoding="utf-8")
            self.assertEqual(
                patched_text.count("def _api_request_host_without_port"), 1
            )
            self.assertEqual(patched_text.count("def _api_server_host_for_request"), 1)
            self.assertIn("request.get_host()", patched_text)
            self.assertIn('os.environ.get("OMEROHOST", "")', patched_text)
            self.assertIn('OMERO_WEB_API_SERVER_PUBLIC_HOST', patched_text)
            self.assertIn('OMERO_WEB_API_SERVER_HOST_ALLOWLIST', patched_text)
            self.assertIn(
                '"host": _api_server_host_for_request(request, obj.host)',
                patched_text,
            )
            compile(patched_text, str(target_path), "exec")

    def test_patched_helpers_require_public_host_or_allowlist(self) -> None:
        """Verify patched helpers avoid reflecting arbitrary request hosts.

        Inputs: repository fixtures. Output: validates safe host rewriting and server preservation.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_path = Path(tmp_dir) / "views.py"
            target_path.write_text(ORIGINAL_VIEWS_SNIPPET, encoding="utf-8")

            subprocess.run(
                [sys.executable, str(self.patch_script), str(target_path)],
                check=True,
            )

            spec = importlib.util.spec_from_file_location("patched_views", target_path)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            self.assertIsNotNone(spec.loader)

            def json_response():
                """Return an identity decorator for patched OMERO.web imports.

                Inputs: none. Output: callable decorator.
                """
                return lambda function: function

            server_list = [
                SimpleNamespace(host="omeroserver", port=4064, server="omero"),
                SimpleNamespace(host="remote.example.org", port=14064, server="remote"),
            ]
            with (
                mock.patch.dict(
                    sys.modules,
                    {
                        "omeroweb": SimpleNamespace(),
                        "omeroweb.connector": SimpleNamespace(Server=server_list),
                        "omeroweb.api": SimpleNamespace(),
                        "omeroweb.api.decorators": SimpleNamespace(
                            json_response=json_response
                        ),
                    },
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "OMEROHOST": "omeroserver",
                        "OMERO_WEB_API_SERVER_PUBLIC_HOST": "",
                        "OMERO_WEB_API_SERVER_HOST_ALLOWLIST": "omero.example.org,2001:db8::1",
                    },
                    clear=False,
                ),
            ):
                spec.loader.exec_module(module)

                ported_domain_request = SimpleNamespace(
                    get_host=lambda: "omero-web.example.test:4090"
                )
                domain_request = SimpleNamespace(get_host=lambda: "omero.example.org")
                ipv6_request = SimpleNamespace(get_host=lambda: "[2001:db8::1]:4090")

                self.assertEqual(
                    module.api_servers(ported_domain_request, "0")["data"][0]["host"],
                    "omeroserver",
                )
                self.assertEqual(
                    module.api_servers(domain_request, "0")["data"][0]["host"],
                    "omero.example.org",
                )
                self.assertEqual(
                    module.api_servers(ipv6_request, "0")["data"][0]["host"],
                    "2001:db8::1",
                )
                self.assertEqual(
                    module.api_servers(domain_request, "0")["data"][1]["host"],
                    "remote.example.org",
                )

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "OMEROHOST": "omeroserver",
                        "OMERO_WEB_API_SERVER_PUBLIC_HOST": "public.example.org",
                    },
                    clear=False,
                ),
            ):
                self.assertEqual(
                    module.api_servers(ported_domain_request, "0")["data"][0]["host"],
                    "public.example.org",
                )


if __name__ == "__main__":
    main()
