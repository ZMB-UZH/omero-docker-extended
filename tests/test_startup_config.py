"""Startup discovery, configuration parsing, and real child-process error boundaries."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "startup" / "50-config.py"


@pytest.fixture
def config(monkeypatch):
    """Inputs: isolated startup variables. Output: the actual importable startup module."""
    for key in tuple(os.environ):
        if key.startswith(("OMERO_", "CONFIG_")) or key in {"OMERODIR", "PYTHON_BIN"}:
            monkeypatch.delenv(key)
    spec = importlib.util.spec_from_file_location("startup_web_config", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CONFIG_omero_web_apps", "omero.web.apps"),
        ("CONFIG_omero_web_secure__cookies", "omero.web.secure_cookies"),
        ("CONFIG_a_b_c", "a.b.c"),
        ("CONFIG_a__b_c", "a_b.c"),
        ("CONFIG_a_b__c_d", "a.b_c.d"),
    ],
)
def test_property_segments_and_escaped_underscores(config, name, expected):
    """Inputs: conventional and single-letter segments. Output: exact OMERO property names."""
    assert config.config_env_to_property(name) == expected


@pytest.mark.parametrize("variable", ["OMERO_WEB_OMERO_BIN", "OMERO_BIN"])
def test_explicit_cli_takes_precedence(config, monkeypatch, tmp_path, variable):
    """Inputs: custom executable path. Output: unmodified explicit command selection."""
    binary = str(tmp_path / "custom path" / "omero")
    monkeypatch.setenv(variable, binary)
    assert config.resolve_omero_bin() == binary


def test_cli_discovers_natural_version_and_respects_configured_venv(
    config, monkeypatch, tmp_path
):
    """Inputs: multiple real venv layouts. Output: natural latest version or explicit selection."""
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setenv("OMERO_WEB_ROOT", str(tmp_path))
    for name in ("venv-3.9", "venv-3.12"):
        binary = tmp_path / name / "bin" / "omero"
        binary.parent.mkdir(parents=True)
        binary.touch()
    latest = tmp_path / "venv-3.12" / "bin" / "omero"
    assert Path(config.resolve_omero_bin()) == latest
    monkeypatch.setenv("OMERO_WEB_VENV", "venv-3.9")
    assert Path(config.resolve_omero_bin()) == tmp_path / "venv-3.9" / "bin" / "omero"
    monkeypatch.setenv("OMERO_WEB_VENV", str(tmp_path / "venv-3.12"))
    assert Path(config.resolve_omero_bin()) == latest


def test_cli_path_and_missing_installation(config, monkeypatch, tmp_path):
    """Inputs: PATH result then absent installation. Output: precedence and explicit diagnostics."""
    monkeypatch.setattr(config.shutil, "which", lambda _name: "discovered-cli")
    assert config.resolve_omero_bin() == "discovered-cli"
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="OMERO_WEB_ROOT is required"):
        config.resolve_omero_bin()
    monkeypatch.setenv("OMERO_WEB_ROOT", "  ")
    with pytest.raises(RuntimeError, match="OMERO_WEB_ROOT is required"):
        config.resolve_omero_bin()
    monkeypatch.setenv("OMERO_WEB_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="Could not resolve an OMERO CLI"):
        config.resolve_omero_bin()


@pytest.mark.parametrize("variable", ["OMERO_WEB_PYTHON_BIN", "PYTHON_BIN"])
def test_python_explicit_selection(config, monkeypatch, variable):
    """Inputs: an explicit interpreter. Output: no fallback to a different venv."""
    monkeypatch.setenv(variable, sys.executable)
    assert config.resolve_python_bin("omero") == sys.executable


@pytest.mark.parametrize("name", ["python3", "python"])
def test_python_prefers_cli_sibling(config, tmp_path, name):
    """Inputs: actual sibling file. Output: interpreter next to the chosen CLI."""
    (tmp_path / name).touch()
    assert config.resolve_python_bin(str(tmp_path / "omero")) == str(tmp_path / name)


@pytest.mark.parametrize("configured", [False, True])
def test_python_venv_fallback_and_absence(config, monkeypatch, tmp_path, configured):
    """Inputs: missing sibling and versioned venv. Output: verified fallback or clear failure."""
    monkeypatch.setenv("OMERO_WEB_ROOT", str(tmp_path))
    if configured:
        monkeypatch.setenv("OMERO_WEB_VENV", "venv-3.12")
    with pytest.raises(RuntimeError, match="Could not resolve a Python binary"):
        config.resolve_python_bin(str(tmp_path / "external" / "omero"))
    binary = tmp_path / "venv-3.12" / "bin" / "python3"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert config.resolve_python_bin(str(tmp_path / "external" / "omero")) == str(
        binary
    )


@pytest.mark.parametrize("variable", ["OMERO_CONFIG_GLOB", "OMERO_WEB_CONFIG_GLOB"])
def test_config_glob_explicit_and_discovered(config, monkeypatch, tmp_path, variable):
    """Inputs: explicit patterns and actual ancestor layout. Output: exact precedence."""
    monkeypatch.setenv(variable, "chosen/*.omero")
    assert config.resolve_config_glob("omero") == "chosen/*.omero"
    monkeypatch.delenv(variable)
    command = tmp_path / "runtime" / "bin" / "omero"
    assert config.resolve_config_glob(str(command)) == ""
    (tmp_path / "config").mkdir()
    assert config.resolve_config_glob(str(command)) == str(
        tmp_path / "config" / "*.omero"
    )


@pytest.mark.parametrize("raw", ["", "plain", "[invalid", "[]", '{"keep": 1}'])
def test_unrelated_configuration_bytes_are_preserved(config, raw):
    """Inputs: unrelated scalar/JSON text. Output: byte-identical values without normalization."""
    assert config.normalize_config_value("CONFIG_fixture", raw) == raw


def test_nested_alias_conversion_does_not_change_keys_or_numbers(config, capsys):
    """Inputs: legacy aliases nested with ordinary values. Output: only legacy values change."""
    original = {"omeroweb_upload": ["/omeroweb_upload/", 3, None, True]}
    result = config.normalize_config_value("CONFIG_fixture", json.dumps(original))
    assert json.loads(result) == {
        "omeroweb_upload": ["/omeroweb_import/", 3, None, True]
    }
    assert (
        config.normalize_config_value("CONFIG_fixture", "omeroweb_upload")
        == "omeroweb_import"
    )
    assert "CONFIG_fixture" in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw", ["not-json", "null", "{}", '"module"', "[1]", "[false]"]
)
def test_additional_apps_require_list_of_module_names(config, raw):
    """Inputs: invalid app declarations. Output: rejection before configuration mutation."""
    with pytest.raises(RuntimeError, match="JSON array of app module names"):
        config.parse_additional_apps(raw)


def test_additional_apps_import_in_real_child(config):
    """Inputs: installed standard modules then nonexistent app. Output: actual interpreter result."""
    assert config.parse_additional_apps('["json", "array"]') == ["json", "array"]
    config.validate_additional_apps(sys.executable, [])
    config.validate_additional_apps(sys.executable, ["json", "array"])
    with pytest.raises(subprocess.CalledProcessError):
        config.validate_additional_apps(sys.executable, ["missing_omero_test_app"])


def test_startup_command_failure_never_prints_configured_secret(tmp_path):
    """Inputs: rejected real CLI command with sensitive argument. Output: redacted failure."""
    sentinel = "fixture-sensitive-value-not-for-diagnostics"
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "COVERAGE_PROCESS_CONFIG"}
    }
    environment.update(
        {
            "OMERO_BIN": sys.executable,
            "OMERO_WEB_PYTHON_BIN": sys.executable,
            "OMERO_CONFIG_GLOB": str(tmp_path / "absent" / "*.omero"),
            "CONFIG_omero_web_secret__key": sentinel,
        }
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert sentinel not in result.stdout + result.stderr
    assert "configuration command failed" in result.stderr
