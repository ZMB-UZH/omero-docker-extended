"""Check startup CLI decisions and status output without a live account."""

import grp
import os
import pwd
from unittest.mock import Mock

import pytest

from startup import dropbox_user_dir_sync as dropbox


@pytest.fixture
def sync_arguments():
    """Inputs: none. Output: explicit startup arguments with no deployment defaults."""
    return [
        "sync",
        "--host",
        "service.example.invalid",
        "--port",
        "4064",
        "--secure",
        "true",
        "--username",
        "fixture",
        "--password-env",
        "FIXTURE_UNUSED_AUTH",
        "--create-root",
        "false",
        "--mode",
        "0770",
        "--allow-world-writable",
        "false",
        "--connect-retries",
        "2",
        "--connect-retry-delay-seconds",
        "0",
    ]


@pytest.mark.parametrize("failed", [0, 1])
@pytest.mark.parametrize("write_status", [False, True])
def test_sync_cli_reports_actual_counts_and_exit_status(
    tmp_path, monkeypatch, capsys, sync_arguments, failed, write_status
):
    """Inputs: successful or partially failed pass. Output: matching status, counts and exit code."""
    result = dropbox.SyncResult(tmp_path / "acceptor", 7, 2, 3, 1, failed)
    synchronize = Mock(return_value=result)
    monkeypatch.setattr(dropbox, "sync", synchronize)
    monkeypatch.setattr(dropbox.time, "time", lambda: 1234)
    status_path = tmp_path / "status" / "dropbox.state"
    arguments = sync_arguments + (
        ["--status-file", str(status_path)] if write_status else []
    )
    assert dropbox.main(arguments) == (1 if failed else 0)
    output = capsys.readouterr()
    assert output.err == ""
    status = dict(line.split("=", 1) for line in output.out.splitlines())
    assert status == {
        "status": "error" if failed else "ok",
        "last_success_epoch": "0" if failed else "1234",
        "dropbox_root": str(result.root),
        "eligible_user_count": "7",
        "created_count": "2",
        "existing_count": "3",
        "skipped_count": "1",
        "failed_count": str(failed),
    }
    assert synchronize.call_count == 1
    config = synchronize.call_args.args[0]
    assert config.secure and not config.create_root
    assert config.status_file == (status_path if write_status else None)
    assert config.password_env == "FIXTURE_UNUSED_AUTH"  # nosec B105 - Environment-variable name, not a credential.
    assert not result.root.exists()
    assert status_path.exists() == write_status
    if write_status:
        assert (
            dict(line.split("=", 1) for line in status_path.read_text().splitlines())
            == status
        )


@pytest.mark.parametrize("write_status", [False, True])
def test_sync_cli_connection_error_records_failure_without_creating_data_dirs(
    tmp_path, monkeypatch, capsys, sync_arguments, write_status
):
    """Inputs: a connection failure. Output: unsuccessful status and no acceptor-directory side effect."""
    monkeypatch.setattr(
        dropbox, "sync", Mock(side_effect=dropbox.SyncError("service unavailable"))
    )
    status_path = tmp_path / "status" / "dropbox.state"
    arguments = sync_arguments + (
        ["--status-file", str(status_path)] if write_status else []
    )
    assert dropbox.main(arguments) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ERROR service unavailable\n"
    assert status_path.exists() == write_status
    if write_status:
        fields = dict(
            line.split("=", 1) for line in status_path.read_text().splitlines()
        )
        assert fields["status"] == "error"
        assert fields["last_success_epoch"] == "0"
        assert fields["dropbox_root"] == ""
        assert fields["failed_count"] == "1"
        assert set(fields) == {
            "status",
            "last_success_epoch",
            "dropbox_root",
            "eligible_user_count",
            "created_count",
            "existing_count",
            "skipped_count",
            "failed_count",
        }


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--port", "0", "port must be between"),
        ("--port", "65536", "port must be between"),
        ("--connect-retries", "0", "connect retries must be at least"),
        ("--connect-retry-delay-seconds", "nan", "finite and non-negative"),
        ("--connect-retry-delay-seconds", "-1", "finite and non-negative"),
        ("--secure", "maybe", "must be a boolean"),
        ("--mode", "private", "3- or 4-digit octal"),
    ],
)
def test_sync_cli_invalid_configuration_never_connects(
    monkeypatch, capsys, sync_arguments, option, value, message
):
    """Inputs: invalid startup values. Output: controlled rejection before any network call."""
    synchronize = Mock(
        side_effect=AssertionError("invalid configuration reached the network")
    )
    monkeypatch.setattr(dropbox, "sync", synchronize)
    arguments = sync_arguments.copy()
    arguments[arguments.index(option) + 1] = value
    assert dropbox.main(arguments) == 1
    assert message in capsys.readouterr().err
    synchronize.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "allow", "result"),
    [("0770", "false", 0), ("0777", "false", 1), ("0777", "true", 0)],
)
def test_validate_cli_enforces_explicit_permission_policy(
    monkeypatch, mode, allow, result
):
    """Inputs: safe or world-writable modes. Output: explicit opt-in required without connecting."""
    synchronize = Mock(side_effect=AssertionError("validation reached the network"))
    monkeypatch.setattr(dropbox, "sync", synchronize)
    assert (
        dropbox.main(["validate", "--mode", mode, "--allow-world-writable", allow])
        == result
    )
    synchronize.assert_not_called()


def test_owner_and_group_resolution_uses_local_account_database():
    """Inputs: current local identity and numeric IDs. Output: matching IDs without filesystem mutation."""
    uid, gid = os.getuid(), os.getgid()
    assert dropbox.resolve_user("", default_uid=uid) == uid
    assert dropbox.resolve_group("", default_gid=gid) == gid
    assert dropbox.resolve_user(str(uid), default_uid=uid) == uid
    assert dropbox.resolve_group(str(gid), default_gid=gid) == gid
    assert dropbox.resolve_user(pwd.getpwuid(uid).pw_name, default_uid=uid) == uid
    assert dropbox.resolve_group(grp.getgrgid(gid).gr_name, default_gid=gid) == gid


@pytest.mark.parametrize("kind", ["user", "group"])
def test_unknown_owner_or_group_fails_before_filesystem_changes(monkeypatch, kind):
    """Inputs: unavailable account name. Output: explicit resolution failure, never an arbitrary fallback ID."""
    module, lookup, resolve = (
        (dropbox.pwd, "getpwnam", dropbox.resolve_user)
        if kind == "user"
        else (dropbox.grp, "getgrnam", dropbox.resolve_group)
    )
    monkeypatch.setattr(module, lookup, Mock(side_effect=KeyError("fixture")))
    default = (
        {"default_uid": os.getuid()} if kind == "user" else {"default_gid": os.getgid()}
    )
    with pytest.raises(dropbox.SyncError, match="unknown owner"):
        resolve("missing-fixture-account", **default)
