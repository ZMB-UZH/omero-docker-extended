from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

import pytest


def load_frontend_preview_tooling():
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
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "frontend_preview_tooling_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "omero-agent-frontend-preview-tooling"
    assert manifest["node_version"] == "24.15.0"
    assert manifest["dependencies"] == {
        "vite": "8.0.7",
        "vitest": "4.1.4",
        "jsdom": "29.0.2",
        "@vitest/browser-playwright": "4.1.4",
        "playwright": "1.59.1",
    }


def test_frontend_preview_wrapper_help_surfaces_supported_commands():
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
    tooling = load_frontend_preview_tooling()
    manifest = {"node_version": "24.15.0"}
    completed = subprocess.CompletedProcess(
        args=["node", "--version"], returncode=0, stdout="v25.9.0\n"
    )

    with (
        mock.patch.object(
            tooling, "ensure_command_available", return_value="/usr/bin/node"
        ),
        mock.patch.object(tooling.subprocess, "run", return_value=completed),
        pytest.raises(RuntimeError, match="need v24.15.0"),
    ):
        tooling.ensure_node_version(manifest)


def test_frontend_preview_safe_extract_rejects_path_traversal():
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
    tooling = load_frontend_preview_tooling()

    assert (
        tooling.node_release_path("24.15.0", "node-v24.15.0-linux-x64.tar.xz")
        == "/dist/v24.15.0/node-v24.15.0-linux-x64.tar.xz"
    )
    assert (
        tooling.node_release_path("24.15.0", "SHASUMS256.txt")
        == "/dist/v24.15.0/SHASUMS256.txt"
    )
    with pytest.raises(RuntimeError, match="Invalid Node.js version"):
        tooling.node_release_path("../24.15.0", "SHASUMS256.txt")
    with pytest.raises(RuntimeError, match="Unexpected Node.js release artifact"):
        tooling.node_release_path("24.15.0", "node-v25.0.0-linux-x64.tar.xz")
    with pytest.raises(RuntimeError, match="Unexpected Node.js release artifact"):
        tooling.node_release_path("24.15.0", "node-v24.15.0-linux-../x64.tar.xz")


def test_frontend_preview_download_uses_validated_curl_args(monkeypatch, tmp_path):
    tooling = load_frontend_preview_tooling()
    calls = []

    def _fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        tooling, "ensure_command_available", lambda command: "/bin/curl"
    )
    monkeypatch.setattr(tooling.subprocess, "run", _fake_run)

    tooling.download_node_release_file("24.15.0", "SHASUMS256.txt", tmp_path / "out")

    args, kwargs = calls[0]
    assert args[:2] == ["/bin/curl", "--fail"]
    assert "--location" in args
    assert args[args.index("--proto") + 1] == "=https"
    tls_option_prefix = "-" * 2 + "tls"
    assert all(not arg.startswith(tls_option_prefix) for arg in args)
    assert args[-1] == "https://nodejs.org/dist/v24.15.0/SHASUMS256.txt"
    assert kwargs["timeout"] == 60
    assert kwargs["check"] is False


def test_frontend_preview_safe_extract_does_not_call_extractall(monkeypatch):
    tooling = load_frontend_preview_tooling()

    def _fail_extractall(*args, **kwargs):
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
        assert extracted.stat().st_mode & 0o111
        assert (destination / "node" / "bin" / "tool-link").is_symlink()


def test_frontend_preview_skill_points_to_wrapper_and_drops_stale_temp_setup():
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
    assert "npm install vite@8.0.7" not in skill_text


def test_frontend_preview_vitest_config_exposes_browser_mode_support():
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
