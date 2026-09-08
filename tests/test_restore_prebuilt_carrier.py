"""Historical carrier identity, authorization and readback regression tests."""

import hashlib
import io
import os
from pathlib import Path
import tarfile
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tools import restore_prebuilt_carrier as recovery


def original():
    """Inputs: none. Output: synthetic manifest without installation-specific values."""
    return {
        "release": "1.2.3-main.1",
        "carrier_image_repository": "example/carrier",
        "carrier_image": "example/carrier:1.2.3-main.1",
        "git_sha": "a" * 40,
        "required_images": ["example/runtime:1.2.3"],
    }


def test_original_identity_and_inventory():
    """Inputs: varied manifests. Output: only exact identity and pinned inventory pass."""
    manifest = original()
    arguments = ("1.2.3-main.1", "example/carrier", "a" * 40)
    assert (
        recovery.validate_original(manifest, *arguments) == manifest["required_images"]
    )
    for key, value in (
        ("release", "1.2.4-main.1"),
        ("carrier_image_repository", "other/carrier"),
        ("carrier_image", "example/carrier:1.2.4-main.1"),
        ("git_sha", "b" * 40),
        ("required_images", []),
        ("required_images", ["example/runtime:latest"]),
        ("required_images", ["example/runtime:1", "example/runtime:1"]),
        ("required_images", ["-option"]),
        ("required_images", ["example/runtime"]),
        ("required_images", ["registry.example:5000/runtime"]),
        ("required_images", ["example/runtime:"]),
        ("required_images", ["image with spaces:1"]),
        ("required_images", [{}]),
    ):
        with pytest.raises(ValueError):
            recovery.validate_original({**manifest, key: value}, *arguments)


def test_only_confirmed_missing_tag_is_accepted():
    """Inputs: Hub status/body fixtures. Output: only confirmed absence permits recovery."""
    arguments = ("example/carrier", "1.2.3-main.1")
    with patch.object(recovery, "output", return_value="{}\n404") as request:
        recovery.require_missing_tag(*arguments)
        command = request.call_args.args[0]
        assert (
            command[-1]
            == "https://hub.docker.com/v2/repositories/example/carrier/tags/1.2.3-main.1/"
        )
        assert command[command.index("--proto") + 1] == "=https"
        assert "--tlsv1.2" in command
        assert command[command.index("--max-time") + 1] == "30"
        assert command[command.index("--max-filesize") + 1] == str(1024**2)
        assert not {"--insecure", "--location", "-k", "-L"}.intersection(command)
        request.return_value = "{}\n503"
        with pytest.raises(RuntimeError):
            recovery.require_missing_tag(*arguments)
        request.side_effect = subprocess.CalledProcessError(28, command)
        with pytest.raises(subprocess.CalledProcessError):
            recovery.require_missing_tag(*arguments)
        request.side_effect = None
        request.return_value = "{}\n200"
        with pytest.raises(ValueError, match="existing"):
            recovery.require_missing_tag(*arguments)
        for content in ("[]", "invalid", "x" * (1024**2 + 1)):
            request.return_value = content + "\n200"
            with pytest.raises(ValueError):
                recovery.docker_tag(*arguments)


def test_executable_resolution_is_required(tmp_path):
    """Inputs: executable lookup fixtures. Output: resolved argv or a closed failure."""
    path = str(tmp_path / "tool")
    with (
        patch.object(recovery.shutil, "which", return_value=path),
        patch.object(
            recovery.subprocess, "check_output", return_value="result\n"
        ) as execute,
    ):
        assert recovery.output(["tool", "argument"]) == "result"
        execute.assert_called_once_with([path, "argument"], text=True)
    with (
        patch.object(recovery.shutil, "which", return_value=None),
        pytest.raises(FileNotFoundError),
    ):
        recovery.executable("tool")


def test_explicit_metadata_authorization_and_runner_boundary():
    """Inputs: CLI and runner fixtures. Output: missing approvals or isolation stop work."""
    with patch.object(recovery, "restore") as restore:
        with pytest.raises(SystemExit):
            recovery.main(
                [
                    "--release-version",
                    "1.2.3-main.1",
                    "--docker-repository",
                    "example/carrier",
                ]
            )
        restore.assert_not_called()
        recovery.main(
            [
                "--release-version",
                "1.2.3-main.1",
                "--docker-repository",
                "example/carrier",
                "--authorize-replace-manifest",
                "--authorize-replace-digest",
            ]
        )
        restore.assert_called_once_with("1.2.3-main.1", "example/carrier")
    with (
        patch.dict(recovery.os.environ, {}, clear=True),
        patch.object(recovery, "run") as run,
    ):
        with pytest.raises(ValueError, match="GitHub-hosted"):
            recovery.restore("1.2.3-main.1", "example/carrier")
        run.assert_not_called()
    environment = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "DOCKER_HOST": "tcp://example.invalid:2375",
    }
    with (
        patch.dict(recovery.os.environ, environment, clear=True),
        pytest.raises(ValueError, match="Docker context"),
    ):
        recovery.restore("1.2.3-main.1", "example/carrier")


def test_existing_public_notes_are_checksum_bound(tmp_path):
    """Inputs: existing notes and checksum. Output: mismatched public text is rejected."""
    notes = b"Compatible maintenance update.\n"
    (tmp_path / "release-notes.md").write_bytes(notes)
    manifest = {"release_notes_sha256": hashlib.sha256(notes).hexdigest()}
    assert recovery.release_notes({}, manifest, tmp_path) == notes
    with pytest.raises(ValueError, match="checksum"):
        recovery.release_notes({}, {"release_notes_sha256": "bad"}, tmp_path)


def test_legacy_public_notes_do_not_keep_obsolete_digest(tmp_path):
    """Inputs: legacy public notes. Output: preserved prose without an obsolete digest."""
    body = "Runtime bundle: `example/carrier:1.2.3-main.1@sha256:" + "a" * 64 + "`."
    result = recovery.release_notes({"body": body}, {}, tmp_path)
    assert b"@sha256:" not in result
    assert b"example/carrier:1.2.3-main.1" in result


def test_legacy_standalone_digest_points_to_verified_asset(tmp_path):
    """Inputs: standalone old digest. Output: notes refer to the refreshed digest asset."""
    body = "Expected carrier digest:\n\nsha256:" + "a" * 64 + "\n"
    result = recovery.release_notes({"body": body}, {}, tmp_path)
    assert result == b"Expected carrier digest:\n\nprebuilt-carrier-digest.txt\n"


def test_synthetic_configuration_overrides_build_only_settings(tmp_path):
    """Inputs: synthetic example values. Output: isolated settings obey build policy."""
    source = tmp_path / "source"
    source.mkdir()
    target = source / ".env"
    values = {"COMPOSE_FILE": "unused", "DOCKER_BUILD_PUSH_IMAGES": "1"}
    with (
        patch.object(recovery, "prepare_ci_compose_environment", return_value=values),
        patch.object(recovery, "derive_compose_project_name", return_value="fixture"),
        patch.object(
            recovery, "_contract_pairs", return_value=[(source / "example", target)]
        ),
    ):
        env = recovery.configure_build(source, tmp_path)
        assert env["DOCKER_BUILD_PUSH_IMAGES"] == "0"
        assert env["COMPOSE_FILE"] == str(source / "docker-compose.yml")
        assert "COMPOSE_PROJECT_NAME='fixture'" in target.read_text()
        values["COMPOSE_FILE"] = "invalid\nvalue"
        with pytest.raises(ValueError, match="literal"):
            recovery.configure_build(source, tmp_path)


def archive_stream(content, *, extra=False, link=False):
    """Inputs: payload and tar-entry options. Output: Docker-copy-shaped binary stream."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        info = tarfile.TarInfo("runtime-images.tar.gz")
        if link:
            info.type = tarfile.SYMTYPE
            info.linkname = "other"
        else:
            info.size = len(content)
        archive.addfile(info, None if link else io.BytesIO(content))
        if extra:
            archive.addfile(tarfile.TarInfo("unexpected"), io.BytesIO())
    stream.seek(0)
    return stream


@pytest.mark.parametrize(
    "case", ["valid", "size", "digest", "extra", "symlink", "empty", "exit"]
)
def test_published_archive_readback(tmp_path, case):
    """Inputs: archive copy cases. Output: complete bytes pass; malformed copies fail."""
    archive = tmp_path / "runtime-images.tar.gz"
    archive.write_bytes(b"verified content")
    content = b"verified content"
    if case == "size":
        content += b"x"
    elif case == "digest":
        content = b"different bytes!"
    process = MagicMock()
    process.__enter__.return_value = process
    process.stdout = (
        None
        if case == "empty"
        else archive_stream(content, extra=case == "extra", link=case == "symlink")
    )
    process.wait.return_value = 1 if case == "exit" else 0
    with (
        patch.object(recovery.subprocess, "Popen", return_value=process),
        patch.object(recovery, "executable", return_value=str(tmp_path / "docker")),
    ):
        if case == "valid":
            recovery.verify_archive("fixture-container", archive)
            process.terminate.assert_not_called()
        else:
            with pytest.raises((ValueError, RuntimeError)):
                recovery.verify_archive("fixture-container", archive)
            process.terminate.assert_called_once()


def test_source_asset_identity_excludes_replaced_metadata():
    """Inputs: release assets. Output: source identity excludes replaceable metadata."""
    source = {
        "id": 1,
        "name": "example-source.tar.gz",
        "size": 12,
        "digest": "sha256:fixture",
    }
    metadata = {"id": 2, "name": "prebuilt-manifest.json", "size": 30}
    assert recovery.source_assets({"assets": [source, metadata]}) == [
        (1, source["name"], 12, "sha256:fixture")
    ]


def test_source_tag_resolution_is_bounded_and_validated():
    """Inputs: GitHub tag fixtures. Output: exact source SHA or a closed failure."""
    commit = {"object": {"type": "commit", "sha": "a" * 40}}
    annotation = {"object": {"type": "tag", "sha": "b" * 40}}
    with patch.object(recovery, "github", return_value=commit):
        assert recovery.source_commit("example/repository", "1.2.3") == "a" * 40
    with patch.object(recovery, "github", side_effect=[annotation, commit]):
        assert recovery.source_commit("example/repository", "1.2.3") == "a" * 40
    for invalid in (
        annotation,
        {"object": {"type": "blob", "sha": "a" * 40}},
        {"object": {"type": "commit", "sha": "invalid"}},
    ):
        with (
            patch.object(recovery, "github", return_value=invalid),
            pytest.raises(ValueError),
        ):
            recovery.source_commit("example/repository", "1.2.3")


def test_concurrent_release_edits_stop_reconciliation():
    """Inputs: release snapshots. Output: download counts accepted, content edits refused."""
    asset = {
        "id": 1,
        "name": "manifest.json",
        "size": 12,
        "digest": "sha256:fixture",
        "download_count": 0,
    }
    before = {
        "id": 2,
        "body": "Public notes",
        "published_at": "2026-01-01",
        "assets": [asset],
    }
    recovery.require_unchanged_release(
        before, {**before, "assets": [{**asset, "download_count": 1}]}
    )
    for after in (
        {**before, "body": "Concurrent notes"},
        {**before, "id": 3},
        {**before, "assets": [{**asset, "digest": "sha256:changed"}]},
    ):
        with pytest.raises(ValueError, match="changed"):
            recovery.require_unchanged_release(before, after)


def test_recovery_workflow_is_manual_and_preserves_release_objects():
    """Inputs: recovery workflow. Output: distinct approvals and no release deletion path."""
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/restore-prebuilt-carrier.yml"
    ).read_text()
    assert "workflow_dispatch:" in workflow
    assert "authorize_replace_manifest:" in workflow
    assert "authorize_replace_digest:" in workflow
    assert "github.event.repository.default_branch" in workflow
    for forbidden in ("gh release delete", "refs/tags/", "--method DELETE"):
        assert forbidden not in workflow


@pytest.mark.parametrize(
    "manifest,digest",
    [("false", "false"), ("false", "true"), ("true", "false"), ("true", "true")],
)
def test_workflow_authorization_shell_fails_closed(manifest, digest):
    """Inputs: all checkbox combinations. Output: real shell proceeds only with both."""
    path = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/restore-prebuilt-carrier.yml"
    )
    workflow = yaml.safe_load(path.read_text())
    steps = workflow["jobs"]["restore"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step["name"] == "Validate recovery authorization"
    )
    guard = script.split("python3 - <<", 1)[0] + "printf authorized"
    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash is required for the workflow authorization check")
    result = subprocess.run(
        [shell, "-c", guard],
        env=dict(os.environ, AUTHORIZE_MANIFEST=manifest, AUTHORIZE_DIGEST=digest),
        capture_output=True,
        text=True,
        check=False,
    )
    allowed = manifest == digest == "true"
    assert (result.returncode == 0) is allowed
    assert (result.stdout == "authorized") is allowed
