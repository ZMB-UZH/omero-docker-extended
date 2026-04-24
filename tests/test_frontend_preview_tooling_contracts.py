from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_frontend_preview_tooling_manifest_pins_expected_versions():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "frontend_preview_tooling_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "omero-agent-frontend-preview-tooling"
    assert manifest["node_min_version"] == "20.19.0"
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
    assert "vite" in completed.stdout
    assert "vitest" in completed.stdout
    assert "playwright" in completed.stdout


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
