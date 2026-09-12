"""Fail-closed source and Docker integration contracts for OMERO.web JSON types."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from docker import patch_omeroweb_webgateway as patcher


SOURCE = b"""@require_POST
@login_required()
@jsonp
@validate_rdef_query
def save_image_rdef_json(request, iid, conn=None, **kwargs):
    if request:
        json_data = "false"
    else:
        json_data = "true"
    return json_data

@login_required()
@jsonp
def list_compatible_imgs_json(request, iid, conn=None, **kwargs):
    json_data = "false"
    if conn:
        img = conn.getObject("Image", iid)
        imgs = []
        for ds in img.getProject().listChildren():
            imgs.extend(ds.listChildren())
        json_data = json.dumps([x.getId() for x in imgs])
    return json_data
"""
CORRECTED = (
    SOURCE.replace(b'json_data = "false"', b"json_data = False")
    .replace(b'json_data = "true"', b"json_data = True")
    .replace(
        b"        for ds in img.getProject().listChildren():",
        b"        project = img.getProject()\n"
        b"        if project is None:\n"
        b"            return []\n"
        b"        for ds in project.listChildren():",
    )
    .replace(
        b"json_data = json.dumps([x.getId() for x in imgs])",
        b"json_data = [x.getId() for x in imgs]",
    )
)


@pytest.fixture
def known_source(monkeypatch):
    """Bind synthetic fixtures without weakening the production digest gate.

    Inputs: pytest monkeypatch. Output: fixture source bytes.
    """
    monkeypatch.setattr(patcher, "SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest())
    monkeypatch.setattr(
        patcher, "PATCHED_SHA256", hashlib.sha256(CORRECTED).hexdigest()
    )
    return SOURCE


def test_corrects_only_native_values_and_preserves_all_decorators(known_source):
    """Keep authentication, method checks and JSONP validation unchanged.

    Inputs: synthetic upstream source. Output: exact corrected source assertion.
    """
    result = patcher.patch_source(known_source)
    assert result == CORRECTED
    before = ast.parse(known_source).body
    after = ast.parse(result).body
    for original, corrected in zip(before, after, strict=True):
        assert original.name == corrected.name
        assert [ast.dump(node) for node in original.decorator_list] == [
            ast.dump(node) for node in corrected.decorator_list
        ]
    assert patcher.patch_source(result) == result


@pytest.mark.parametrize("source", (b"", SOURCE, SOURCE + b"\n"))
def test_unknown_source_is_rejected_without_fixture_override(source):
    """Do not silently apply a correction to an unreviewed upstream version.

    Inputs: unrecognized source bytes. Output: fail-closed assertion.
    """
    with pytest.raises(ValueError, match="Unrecognized"):
        patcher.patch_source(source)


@pytest.mark.parametrize(
    "scope, expected", [("project", [2]), ("orphan", []), ("disconnected", False)]
)
def test_corrected_lookup_preserves_native_results(
    known_source, tmp_path, scope, expected
):
    """Execute the corrected lookup for project, orphan and disconnected images.

    Inputs: reviewed synthetic source, temporary module and image scope. Output:
    native JSON value assertions from the complete corrected fixture module.
    """
    target = tmp_path / "corrected_webgateway.py"
    target.write_bytes(
        b"import json\n"
        b"def require_POST(view):\n    return view\n"
        b"def login_required():\n    return lambda view: view\n"
        b"jsonp = validate_rdef_query = require_POST\n"
        + patcher.patch_source(known_source)
    )
    spec = importlib.util.spec_from_file_location("corrected_webgateway", target)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    child = SimpleNamespace(getId=lambda: 2)
    dataset = SimpleNamespace(listChildren=lambda: [child])
    project = (
        SimpleNamespace(listChildren=lambda: [dataset]) if scope == "project" else None
    )
    image = SimpleNamespace(getProject=lambda: project)
    connection = (
        SimpleNamespace(getObject=lambda *_: image) if scope != "disconnected" else None
    )
    assert module.list_compatible_imgs_json(None, 1, conn=connection) == expected
    assert module.save_image_rdef_json(None, 1) is True
    assert module.save_image_rdef_json(object(), 1) is False


@pytest.mark.parametrize(
    ("before", "after", "message"),
    (
        (b"save_image_rdef_json", b"renamed_view", "functions are missing"),
        (b'json_data = "true"', b"json_data = True", "assignment is not unique"),
        (b"@require_POST\n", b"", "reviewed digest"),
    ),
)
def test_malformed_reviewed_contract_is_rejected(
    known_source, monkeypatch, before, after, message
):
    """Require both an exact transformation and its independently reviewed output.

    Inputs: mutated synthetic source. Output: fail-closed transformation assertions.
    """
    changed = known_source.replace(before, after)
    monkeypatch.setattr(patcher, "SOURCE_SHA256", hashlib.sha256(changed).hexdigest())
    with pytest.raises(ValueError, match=message):
        patcher.patch_source(changed)


def test_missing_source_segment_is_rejected(known_source, monkeypatch):
    """Refuse an incomplete parser result without writing partial source.

    Inputs: synthetic source and parser fault. Output: explicit failure assertion.
    """
    monkeypatch.setattr(patcher.ast, "get_source_segment", lambda *_: None)
    with pytest.raises(ValueError, match="function is not unique"):
        patcher.patch_source(known_source)


def test_cli_preserves_file_mode_and_is_idempotent(known_source, tmp_path, monkeypatch):
    """Keep ownership-sensitive build file permissions and accept a verified repeat.

    Inputs: temporary source file. Output: source and mode assertions.
    """
    target = tmp_path / "views.py"
    target.write_bytes(known_source)
    target.chmod(0o640)
    original_mode = target.stat().st_mode
    monkeypatch.setattr("sys.argv", ["patch", str(target)])
    assert patcher.main() == 0
    assert target.read_bytes() == CORRECTED
    assert target.stat().st_mode == original_mode
    assert patcher.main() == 0


def test_cli_rejects_unknown_content_without_changing_file(tmp_path, monkeypatch):
    """Never mutate an unrecognized target, including a future upstream release.

    Inputs: temporary unrecognized source. Output: unchanged file assertion.
    """
    target = tmp_path / "views.py"
    target.write_bytes(SOURCE)
    monkeypatch.setattr("sys.argv", ["patch", str(target)])
    with pytest.raises(ValueError, match="Unrecognized"):
        patcher.main()
    assert target.read_bytes() == SOURCE


@pytest.mark.parametrize("kind", ("missing", "directory", "symlink"))
def test_cli_requires_regular_file(tmp_path, monkeypatch, kind):
    """Do not redirect writes through links or accept invalid source paths.

    Inputs: temporary invalid path. Output: rejected target assertion.
    """
    target = tmp_path / "views.py"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        source = tmp_path / "original.py"
        source.write_bytes(SOURCE)
        target.symlink_to(source)
    monkeypatch.setattr("sys.argv", ["patch", str(target)])
    with pytest.raises(ValueError, match="regular file"):
        patcher.main()


def test_docker_build_applies_correction_to_installed_webgateway():
    """Keep the correction coupled to the reviewed base image and installed module.

    Inputs: tracked Dockerfile. Output: build integration assertions.
    """
    dockerfile = (
        Path(__file__).resolve().parents[1] / "docker/omero-web.Dockerfile"
    ).read_text()
    assert "COPY docker/patch_omeroweb_webgateway.py" in dockerfile
    assert 'WEBGATEWAY_PY="${SITE_PACKAGES}/omeroweb/webgateway/views.py"' in dockerfile
    assert (
        '"${VENV_DIR}/bin/python" /tmp/patch_omeroweb_webgateway.py "${WEBGATEWAY_PY}"'
        in dockerfile
    )
    assert "rm -f /tmp/patch_omeroweb_webgateway.py" in dockerfile
