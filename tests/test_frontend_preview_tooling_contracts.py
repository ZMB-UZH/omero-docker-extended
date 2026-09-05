from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

import pytest


def load_frontend_preview_tooling():
    """Return load frontend preview tooling.

    Inputs: none. Output: `module`.
    """
    import importlib.util

    script_path = (
        Path(__file__).resolve().parents[1] / "tools" / "frontend_preview_tooling.py"
    )
    spec = importlib.util.spec_from_file_location(
        "frontend_preview_tooling_under_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontend_preview_tooling_manifest_pins_expected_versions():
    """Verify frontend preview tooling manifest pins expected versions.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview tooling manifest pins expected versions.
    """
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "frontend_preview_tooling_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "omero-agent-frontend-preview-tooling"
    assert manifest["node_version"] == "24.20.0"
    assert manifest["dependencies"] == {
        "vite": "8.2.2",
        "vitest": "5.0.0",
        "jsdom": "30.0.1",
        "@vitest/browser-playwright": "5.0.0",
        "playwright": "1.63.0",
    }


def test_frontend_preview_wrapper_help_surfaces_supported_commands():
    """Verify frontend preview wrapper help surfaces supported commands.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview wrapper help surfaces supported commands.
    """
    script_path = (
        Path(__file__).resolve().parents[1] / "tools" / "frontend_preview_tooling.py"
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "bootstrap" in completed.stdout
    assert "install-node" in completed.stdout
    assert "vite" in completed.stdout
    assert "vitest" in completed.stdout
    assert "playwright" in completed.stdout


def test_frontend_preview_wrapper_requires_exact_node_version():
    """Verify frontend preview wrapper requires exact node version.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview wrapper requires exact node version.
    """
    tooling = load_frontend_preview_tooling()
    manifest = {"node_version": "24.20.0"}
    completed = subprocess.CompletedProcess(
        args=["node", "--version"], returncode=0, stdout="v25.9.0\n"
    )

    with (
        mock.patch.object(
            tooling, "ensure_command_available", return_value="/usr/bin/node"
        ),
        mock.patch.object(tooling.subprocess, "run", return_value=completed),
        pytest.raises(RuntimeError, match="need v24.20.0"),
    ):
        tooling.ensure_node_version(manifest)


def test_frontend_preview_safe_extract_rejects_path_traversal():
    """Confirm frontend preview safe extract rejects path traversal is rejected at the boundary.

    Inputs: repository fixtures. Output: fails on regressions when frontend preview safe extract rejects path traversal accepts unsafe input.
    """
    tooling = load_frontend_preview_tooling()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "unsafe.tar.xz"
        destination = tmp_path / "destination"
        destination.mkdir()
        payload = tmp_path / "payload.txt"
        payload.write_text("unsafe", encoding="utf-8")
        with tarfile.open(archive_path, "w:xz") as archive:
            archive.add(payload, arcname="../escape.txt")

        with pytest.raises(RuntimeError, match="unsafe archive member"):
            tooling.safe_extract_tar_xz(archive_path, destination)


def test_frontend_preview_node_release_path_allows_only_expected_artifacts():
    """Verify the frontend preview node release path allows only expected artifacts safety boundary.

    Inputs: repository fixtures. Output: fails on regressions when frontend preview node release path allows only expected artifacts accepts unsafe input.
    """
    tooling = load_frontend_preview_tooling()

    assert (
        tooling.node_release_path("24.20.0", "node-v24.20.0-linux-x64.tar.xz")
        == "/dist/v24.20.0/node-v24.20.0-linux-x64.tar.xz"
    )
    assert (
        tooling.node_release_path("24.20.0", "SHASUMS256.txt")
        == "/dist/v24.20.0/SHASUMS256.txt"
    )
    with pytest.raises(RuntimeError, match="Invalid Node.js version"):
        tooling.node_release_path("../24.20.0", "SHASUMS256.txt")
    with pytest.raises(RuntimeError, match="Unexpected Node.js release artifact"):
        tooling.node_release_path("24.20.0", "node-v25.0.0-linux-x64.tar.xz")
    with pytest.raises(RuntimeError, match="Unexpected Node.js release artifact"):
        tooling.node_release_path("24.20.0", "node-v24.20.0-linux-../x64.tar.xz")


def test_frontend_preview_download_uses_validated_curl_args(monkeypatch, tmp_path):
    """Verify frontend preview download uses validated curl args.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` temporary path fixture.
    Output: `CompletedProcess` result.
    """
    tooling = load_frontend_preview_tooling()
    calls = []

    def _fake_run(args, **kwargs):
        """Return `tests.test_frontend_preview_tooling_contracts`'s fake command result.

        Inputs: `args` positional arguments, `**kwargs` keyword arguments. Output:
        `CompletedProcess` result.
        """
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        tooling, "ensure_command_available", lambda command: "/bin/curl"
    )
    monkeypatch.setattr(tooling.subprocess, "run", _fake_run)

    tooling.download_node_release_file("24.20.0", "SHASUMS256.txt", tmp_path / "out")

    args, kwargs = calls[0]
    assert args[:2] == ["/bin/curl", "--fail"]
    assert "--location" in args
    assert args[args.index("--proto") + 1] == "=https"
    tls_option_prefix = "-" * 2 + "tls"
    assert all(not arg.startswith(tls_option_prefix) for arg in args)
    assert args[-1] == "https://nodejs.org/dist/v24.20.0/SHASUMS256.txt"
    assert kwargs["timeout"] == 60
    assert kwargs["check"] is False


def test_frontend_preview_safe_extract_does_not_call_extractall(monkeypatch):
    """Verify frontend preview safe extract does not call extractall.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in frontend preview safe extract does not call extractall.
    AssertionError when validation or the called operation fails.
    """
    tooling = load_frontend_preview_tooling()

    def _fail_extractall(*args, **kwargs):
        """Record the fail extractall call on the test double for later assertions.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        None. Raises: AssertionError when validation or the called operation fails.
        """
        raise AssertionError("extractall must not be used")

    monkeypatch.setattr(tarfile.TarFile, "extractall", _fail_extractall)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "safe.tar.xz"
        destination = tmp_path / "destination"
        destination.mkdir()
        payload = b"#!/bin/sh\nexit 0\n"
        with tarfile.open(archive_path, "w:xz") as archive:
            directory = tarfile.TarInfo("node/bin")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)

            script = tarfile.TarInfo("node/bin/tool")
            script.size = len(payload)
            script.mode = 0o755
            archive.addfile(script, io.BytesIO(payload))

            link = tarfile.TarInfo("node/bin/tool-link")
            link.type = tarfile.SYMTYPE
            link.linkname = "tool"
            archive.addfile(link)

        tooling.safe_extract_tar_xz(archive_path, destination)

        extracted = destination / "node" / "bin" / "tool"
        assert extracted.read_bytes() == payload
        if os.name != "nt":
            assert extracted.stat().st_mode & 0o111
        assert (destination / "node" / "bin" / "tool-link").is_symlink()


def test_frontend_preview_skill_points_to_wrapper_and_drops_stale_temp_setup():
    """Verify frontend preview skill points to wrapper and drops stale temp setup.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview skill points to wrapper and drops stale temp setup.
    """
    skill_path = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "frontend-preview"
        / "SKILL.md"
    )
    skill_text = skill_path.read_text(encoding="utf-8")

    assert "python3 tools/frontend_preview_tooling.py bootstrap" in skill_text
    assert "python3 tools/frontend_preview_tooling.py install-node" in skill_text
    assert skill_text.find("install-node") < skill_text.find("bootstrap")
    assert "python3 tools/frontend_preview_tooling.py vite --" in skill_text
    assert "python3 tools/frontend_preview_tooling.py vitest --" in skill_text
    assert "python3 tools/frontend_preview_tooling.py playwright --" in skill_text
    assert "vite_django_preview.config.mjs" in skill_text
    assert "vitest_django_preview.config.mjs" in skill_text
    template_check = (
        'test -f "$PLUGIN_ROOT/templates/$(basename "$PLUGIN_ROOT")/$PREVIEW_TEMPLATE"'
    )
    assert template_check in skill_text
    assert "do not guess a repo path" in skill_text
    assert "$REPO_ROOT/omero-web/omero/static" not in skill_text
    assert "mktemp -d /tmp/vite-preview" not in skill_text
    assert "npm install vite@8.2.2" not in skill_text


def test_frontend_preview_vitest_config_exposes_browser_mode_support():
    """Verify frontend preview vitest config exposes browser mode support.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview vitest config exposes browser mode support.
    """
    config_path = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "frontend-preview"
        / "agents"
        / "vitest_django_preview.config.mjs"
    )
    config_text = config_path.read_text(encoding="utf-8")

    assert "mergeConfig" in config_text
    assert "@vitest/browser-playwright" in config_text
    assert "VITEST_BROWSER" in config_text
    assert "VITEST_INCLUDE" in config_text
    assert "vitestInternalBrowserEntry" in config_text
    assert "vitestBrowserContextEntry" in config_text
    assert "browser: {" in config_text
    assert "vitePreviewConfig" in config_text


def test_frontend_preview_vite_config_allows_explicit_temp_spec_paths():
    """Verify frontend preview vite config allows explicit temp spec paths.

    Inputs: repository fixtures. Output: fails on regressions in frontend preview vite config allows explicit temp spec paths.
    """
    config_path = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "frontend-preview"
        / "agents"
        / "vite_django_preview.config.mjs"
    )
    config_text = config_path.read_text(encoding="utf-8")

    assert "PREVIEW_EXTRA_FS_ALLOW" in config_text
    assert "VITEST_INCLUDE" in config_text
    assert "EXTRA_FS_ALLOW" in config_text


def test_frontend_preview_static_asset_resolver_rejects_traversal(tmp_path):
    """Verify frontend preview static resolver rejects traversal outside static roots.

    Inputs: `tmp_path` temporary path fixture. Output: fails on regressions in
    frontend preview static asset containment.
    """
    node_bin = shutil.which("node")
    if node_bin is None:
        pytest.skip("node is required to execute the Vite preview config contract")

    repo_root = tmp_path / "repo"
    plugin_static = repo_root / "omeroweb_import" / "static" / "omeroweb_import"
    omero_static = repo_root / "omero-static"
    plugin_static.mkdir(parents=True)
    omero_static.joinpath("3rdparty").mkdir(parents=True)
    plugin_asset = plugin_static / "app.css"
    omero_asset = omero_static / "3rdparty" / "app.js"
    plugin_asset.write_text("body{}", encoding="utf-8")
    omero_asset.write_text("console.log(1);", encoding="utf-8")
    repo_root.joinpath("AGENTS.md").write_text("secret", encoding="utf-8")

    tool_dir = tmp_path / "tooling"
    vite_stub = tool_dir / "node_modules" / "vite"
    vite_stub.mkdir(parents=True)
    tool_dir.joinpath("package.json").write_text(
        '{"name":"preview-test","type":"module"}\n', encoding="utf-8"
    )
    vite_stub.joinpath("index.js").write_text(
        "module.exports = { defineConfig: (config) => config };\n",
        encoding="utf-8",
    )

    config_path = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "frontend-preview"
        / "agents"
        / "vite_django_preview.config.mjs"
    )
    script = f"""
import {{ pathToFileURL }} from 'node:url';
const config = await import(pathToFileURL({json.dumps(str(config_path))}).href);
const payload = {{
  pluginValid: config.resolveStaticAssetPath('omeroweb_import/app.css'),
  pluginTraversal: config.resolveStaticAssetPath('omeroweb_import/../../../AGENTS.md'),
  pluginEncodedTraversal: config.resolveStaticAssetPath('omeroweb_import/%2e%2e/%2e%2e/AGENTS.md'),
  pluginEncodedSlash: config.resolveStaticAssetPath('omeroweb_import%2f..%2fAGENTS.md'),
  omeroValid: config.resolveStaticAssetPath('3rdparty/app.js'),
  omeroTraversal: config.resolveStaticAssetPath('3rdparty/../AGENTS.md'),
}};
console.log(JSON.stringify(payload));
"""
    env = os.environ.copy()
    env.update(
        {
            "REPO_ROOT": str(repo_root),
            "PLUGIN_ROOT": str(repo_root / "omeroweb_import"),
            "OMERO_STATIC_ROOT": str(omero_static),
        }
    )
    completed = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=tool_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert Path(payload["pluginValid"]).resolve() == plugin_asset.resolve()
    assert Path(payload["omeroValid"]).resolve() == omero_asset.resolve()
    assert payload["pluginTraversal"] is None
    assert payload["pluginEncodedTraversal"] is None
    assert payload["pluginEncodedSlash"] is None
    assert payload["omeroTraversal"] is None
