"""Real filesystem tests for DropBox directory ownership and race boundaries."""

import os
import stat
from dataclasses import replace
import builtins
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from startup import dropbox_user_dir_sync as dropbox


def test_created_root_reconciles_parent_ownership_before_verification(
    tmp_path, monkeypatch
):
    """Inputs: a newly created directory reporting different ownership. Output: descriptor-based parent ownership and mode before handoff."""
    root = tmp_path / "dropbox"
    original_stat, original_chown = os.fstat, os.fchown
    reconciled = []

    def inspect(fd):
        """Inputs: an open descriptor. Output: one controlled ownership mismatch on the new root."""
        result = original_stat(fd)
        if root.exists() and result.st_ino == root.stat().st_ino and not reconciled:
            values = list(result)
            values[4] = result.st_uid + 1
            return os.stat_result(values)
        return result

    def reconcile(fd, uid, gid):
        """Inputs: ownership request. Output: actual operation confined to the fixture directory."""
        assert original_stat(fd).st_ino == root.stat().st_ino
        assert (uid, gid) == (tmp_path.stat().st_uid, tmp_path.stat().st_gid)
        original_chown(fd, uid, gid)
        reconciled.append((uid, gid))

    monkeypatch.setattr(dropbox.os, "fstat", inspect)
    monkeypatch.setattr(dropbox.os, "fchown", reconcile)
    state = dropbox.ensure_root(root, create_root=True, mode=0o750)
    assert state.created and len(reconciled) == 1
    assert stat.S_IMODE(root.stat().st_mode) == 0o750
    assert (root.stat().st_uid, root.stat().st_gid) == reconciled[0]


@pytest.fixture
def directory_config():
    """Inputs: none. Output: explicit non-network fixture settings."""
    return dropbox.SyncConfig(
        host="unused.example.test",
        port=1,
        secure=True,
        username="fixture",
        password_env="FIXTURE_PASSWORD",
        create_root=True,
        owner="",
        group="",
        mode=0o770,
        allow_world_writable=False,
        status_file=None,
        connect_retries=1,
        connect_retry_delay_seconds=0,
    )


@pytest.mark.parametrize(
    "username,reason",
    [
        ("bad\x00name", "control character"),
        ("bad\tname", "control character"),
        ("x" * 256, "longer than 255 bytes"),
        ("\u03bc" * 128, "longer than 255 bytes"),
        ("x" * 255, None),
        ("\u03bc" * 127, None),
    ],
)
def test_username_limits_measure_filesystem_bytes(username, reason):
    """Inputs: byte-boundary Unicode and control characters. Output: safe components only."""
    actual = dropbox.validate_username_component(username)
    assert actual is None if reason is None else reason in actual


def test_gateway_import_returns_real_symbol_or_explicit_installation_error(monkeypatch):
    """Inputs: a controlled dependency import. Output: exact gateway symbol or explanatory failure."""
    original_import = builtins.__import__
    gateway = object()
    available = True

    def import_gateway(name, *args, **kwargs):
        """Inputs: module import. Output: isolate only the optional OMERO dependency."""
        if name == "omero.gateway":
            if available:
                return SimpleNamespace(BlitzGateway=gateway)
            raise ImportError("fixture missing gateway")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_gateway)
    assert dropbox.import_omero_gateway() is gateway
    available = False
    with pytest.raises(dropbox.SyncError, match="gateway is not importable"):
        dropbox.import_omero_gateway()


@pytest.mark.parametrize(
    "outcomes", [[False, True], [OSError("fixture outage"), True], [False, False]]
)
def test_gateway_retries_close_only_failed_connections(
    directory_config, monkeypatch, outcomes
):
    """Inputs: failed and successful dedicated logins. Output: bounded retries, every failed connection closed."""
    config = replace(
        directory_config, connect_retries=2, connect_retry_delay_seconds=0.25
    )
    monkeypatch.setenv(config.password_env, "fixture-runtime-value")
    connections = [
        SimpleNamespace(
            connect=Mock(side_effect=value)
            if isinstance(value, Exception)
            else Mock(return_value=value),
            close=Mock(),
        )
        for value in outcomes
    ]
    factory = Mock(side_effect=connections)
    monkeypatch.setattr(dropbox, "import_omero_gateway", lambda: factory)
    sleep = Mock()
    monkeypatch.setattr(dropbox.time, "sleep", sleep)
    if outcomes[-1] is True:
        assert dropbox.connect(config) is connections[-1]
        connections[-1].close.assert_not_called()
    else:
        with pytest.raises(
            dropbox.SyncError, match="after 2 attempt.*login returned false"
        ):
            dropbox.connect(config)
        connections[-1].close.assert_called_once_with(hard=True)
    connections[0].close.assert_called_once_with(hard=True)
    assert factory.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_missing_gateway_credential_fails_before_network(directory_config, monkeypatch):
    """Inputs: absent named environment value. Output: no gateway import or network request."""
    monkeypatch.delenv(directory_config.password_env, raising=False)
    factory = Mock(side_effect=AssertionError("must not import gateway"))
    monkeypatch.setattr(dropbox, "import_omero_gateway", factory)
    with pytest.raises(dropbox.SyncError, match="must be set"):
        dropbox.connect(directory_config)
    factory.assert_not_called()


@pytest.mark.parametrize(
    "settings,diagnostic",
    [
        ({"omero.fs.importUsers": "special"}, "importUsers=default"),
        ({"omero.data.dir": ""}, "omero.data.dir is empty"),
        (
            {"omero.data.dir": "/data", "omero.fs.defaultDropBoxDir": ""},
            "defaultDropBoxDir is empty",
        ),
        ({"omero.fs.watchDir": "relative/dropbox"}, "must be absolute"),
    ],
)
def test_ambiguous_or_relative_dropbox_configuration_is_rejected(settings, diagnostic):
    """Inputs: invalid deployment settings. Output: fail before creating a guessed storage path."""
    service = SimpleNamespace(getConfigValue=settings.get)
    connection = SimpleNamespace(getConfigService=lambda: service)
    with pytest.raises(dropbox.SyncError, match=diagnostic):
        dropbox.resolve_dropbox_root(connection)
    assert dropbox.config_value(connection, "absent", "fallback") == "fallback"


def test_missing_root_or_parent_is_not_implicitly_created(tmp_path):
    """Inputs: disabled root creation or absent parent. Output: no unexpected hierarchy is fabricated."""
    target = tmp_path / "absent-parent" / "acceptor"
    for create in (False, True):
        with pytest.raises(dropbox.SyncError, match="does not exist"):
            dropbox.ensure_root(target, create_root=create, mode=0o770)
        assert not target.parent.exists()


def test_changed_root_identity_refuses_user_directory_creation(
    tmp_path, directory_config
):
    """Inputs: root resolving somewhere other than the previously verified path. Output: no writes."""
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(dropbox.SyncError, match="escaped DropBox root"):
        dropbox.ensure_user_directory(
            root,
            tmp_path / "different",
            "fixture",
            directory_config,
            os.getuid(),
            os.getgid(),
        )
    assert not list(root.iterdir())


@pytest.mark.parametrize("operation", ["root", "user"])
def test_directory_swap_never_changes_external_permissions(
    tmp_path, monkeypatch, directory_config, operation
):
    """Inputs: symlink swap at permission boundary. Output: external data and mode preserved."""
    root = tmp_path / "acceptor"
    if operation == "user":
        root.mkdir()
        target = root / "fixture"
        target.mkdir(mode=0o700)
    else:
        target = root
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "data.bin"
    sentinel.write_bytes(b"existing-user-data")
    before = outside.stat()
    original = stat.S_IMODE
    replaced = False

    def swap_before_permission_change(mode):
        """Inputs: mode about to be compared. Output: controlled filesystem race."""
        nonlocal replaced
        if not replaced:
            replaced = True
            target.rename(tmp_path / "original-directory")
            target.symlink_to(outside, target_is_directory=True)
        return original(mode)

    monkeypatch.setattr(dropbox.stat, "S_IMODE", swap_before_permission_change)
    old_umask = os.umask(0o077)
    try:
        try:
            if operation == "root":
                dropbox.ensure_root(root, create_root=True, mode=directory_config.mode)
            else:
                dropbox.ensure_user_directory(
                    root,
                    root.resolve(),
                    "fixture",
                    directory_config,
                    os.getuid(),
                    os.getgid(),
                )
        except (dropbox.SyncError, OSError):
            # Detecting the replacement is permitted; following it is never permitted.
            pass
    finally:
        os.umask(old_umask)
    assert replaced, "The race must execute, not merely be configured."
    after = outside.stat()
    assert (after.st_mode, after.st_uid, after.st_gid) == (
        before.st_mode,
        before.st_uid,
        before.st_gid,
    )
    assert sentinel.read_bytes() == b"existing-user-data"
    assert target.is_symlink()


def test_directory_repair_is_leaf_only_and_idempotent(tmp_path, directory_config):
    """Inputs: existing data and restrictive umask. Output: exact leaf modes, unchanged payload."""
    root = tmp_path / "acceptor"
    root.mkdir(mode=0o700)
    target = root / "fixture"
    target.mkdir(mode=0o700)
    nested = target / "existing"
    nested.mkdir(mode=0o700)
    payload = nested / "data.bin"
    payload.write_bytes(b"payload")
    payload.chmod(0o600)
    before = (nested.stat().st_mode, payload.stat().st_mode, payload.read_bytes())
    for _ in range(2):
        assert (
            dropbox.ensure_user_directory(
                root,
                root.resolve(),
                "fixture",
                directory_config,
                os.getuid(),
                os.getgid(),
            )
            == "existing"
        )
    assert stat.S_IMODE(target.stat().st_mode) == directory_config.mode
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert (
        nested.stat().st_mode,
        payload.stat().st_mode,
        payload.read_bytes(),
    ) == before


@pytest.mark.parametrize("username", ["../outside", "a/b", "", ".", ".."])
def test_directory_boundary_rejects_invalid_components(
    tmp_path, directory_config, username
):
    """Inputs: invalid direct caller. Output: rejection before creating any directory."""
    root = tmp_path / "acceptor"
    root.mkdir()
    with pytest.raises((dropbox.SyncError, OSError)):
        dropbox.ensure_user_directory(
            root, root.resolve(), username, directory_config, os.getuid(), os.getgid()
        )
    assert list(root.iterdir()) == []
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "setting,value,diagnostic",
    [
        ("port", 0, "port"),
        ("port", -1, "port"),
        ("port", 65536, "port"),
        ("connect_retry_delay_seconds", float("nan"), "finite"),
        ("connect_retry_delay_seconds", float("inf"), "finite"),
        ("connect_retry_delay_seconds", -1, "non-negative"),
        ("connect_retries", 0, "at least 1"),
    ],
)
def test_dropbox_config_rejects_invalid_connection_settings(
    directory_config, setting, value, diagnostic
):
    """Inputs: invalid connection settings. Output: rejection before connecting or sleeping."""
    config = directory_config
    args = dropbox.build_parser().parse_args(
        [
            "sync",
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--secure",
            "true",
            "--create-root",
            "false",
            "--mode",
            "0770",
            "--allow-world-writable",
            "false",
            "--connect-retries",
            "1",
            "--connect-retry-delay-seconds",
            "0",
        ]
    )
    setattr(args, setting, value)
    with pytest.raises(dropbox.SyncError, match=diagnostic):
        dropbox.config_from_args(args)


def test_existing_directory_does_not_require_parent_write_access(
    tmp_path, monkeypatch, directory_config
):
    """Inputs: existing writable leaf below read-only root. Output: no unnecessary creation attempt."""
    root = tmp_path / "acceptor"
    root.mkdir()
    (root / "fixture").mkdir(mode=directory_config.mode)
    root.chmod(0o500)
    mkdir = Mock(side_effect=PermissionError("Parent is read-only"))
    monkeypatch.setattr(dropbox.os, "mkdir", mkdir)
    try:
        assert (
            dropbox.ensure_user_directory(
                root,
                root.resolve(),
                "fixture",
                directory_config,
                os.getuid(),
                os.getgid(),
            )
            == "existing"
        )
        mkdir.assert_not_called()
    finally:
        root.chmod(0o700)


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_concurrent_creator_is_validated_without_following_links(
    tmp_path, monkeypatch, directory_config, replacement
):
    """Inputs: entry created by another writer. Output: valid reuse or closed symlink rejection."""
    root = tmp_path / "acceptor"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    before = outside.stat()
    real_mkdir = os.mkdir

    def raced_creation(name, mode=0o777, *, dir_fd=None):
        """Inputs: proposed name. Output: deterministic concurrent creation result."""
        if replacement == "directory":
            real_mkdir(name, mode, dir_fd=dir_fd)
        else:
            os.symlink(outside, name, dir_fd=dir_fd)
        raise FileExistsError(name)

    monkeypatch.setattr(dropbox.os, "mkdir", raced_creation)
    if replacement == "directory":
        assert (
            dropbox.ensure_user_directory(
                root,
                root.resolve(),
                "fixture",
                directory_config,
                os.getuid(),
                os.getgid(),
            )
            == "existing"
        )
        assert stat.S_IMODE((root / "fixture").stat().st_mode) == directory_config.mode
    else:
        with pytest.raises(dropbox.SyncError, match="symlink"):
            dropbox.ensure_user_directory(
                root,
                root.resolve(),
                "fixture",
                directory_config,
                os.getuid(),
                os.getgid(),
            )
        after = outside.stat()
        assert (after.st_mode, after.st_uid, after.st_gid) == (
            before.st_mode,
            before.st_uid,
            before.st_gid,
        )


@pytest.mark.parametrize("operation", ["fchown", "fchmod"])
def test_permission_failure_closes_pinned_descriptors(
    tmp_path, monkeypatch, directory_config, operation
):
    """Inputs: failed ownership/mode change. Output: propagated failure and closed handles."""
    root = tmp_path / "acceptor"
    root.mkdir()
    target = root / "fixture"
    target.mkdir(mode=0o700)
    captured = []

    def fail(descriptor, *_args):
        """Inputs: directory handle. Output: simulated OS denial, retaining the descriptor number."""
        captured.append(descriptor)
        raise PermissionError("fixture permission failure")

    monkeypatch.setattr(dropbox.os, operation, fail)
    uid = os.getuid() + 1 if operation == "fchown" else os.getuid()
    with pytest.raises(PermissionError, match="fixture permission failure"):
        dropbox.ensure_user_directory(
            root, root.resolve(), "fixture", directory_config, uid, os.getgid()
        )
    assert captured
    for descriptor in captured:
        with pytest.raises(OSError):
            os.fstat(descriptor)
