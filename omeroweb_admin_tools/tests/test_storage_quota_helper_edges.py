from __future__ import annotations

import json
import fcntl
import multiprocessing
import os
from pathlib import Path

import pytest

from omeroweb_admin_tools.services import storage_quotas


@pytest.fixture(autouse=True)
def _quota_env(monkeypatch):
    """Record the quota env call on the test double for later assertions.

    Inputs: `monkeypatch` pytest monkeypatch fixture. Output: None.
    """
    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(storage_quotas.DEFAULT_GROUP_QUOTA_ENV, "0.25")
    monkeypatch.setenv(storage_quotas.AUTO_GROUP_QUOTA_ENV, "false")


def test_storage_quota_env_and_root_helpers_cover_validation_edges(
    monkeypatch,
    tmp_path,
):
    """Verify storage quota env and root helpers cover validation edges.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` temporary path fixture.
    Output: `real_resolve` result. Raises: FileNotFoundError for the exercised failure path.
    """
    monkeypatch.setenv(storage_quotas.AUTO_GROUP_QUOTA_ENV, "maybe")
    with pytest.raises(storage_quotas.QuotaError, match="expected one of"):
        storage_quotas.auto_set_default_group_quota_enabled()

    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, "0")
    with pytest.raises(storage_quotas.QuotaError, match="greater than 0"):
        storage_quotas.min_quota_gb()

    monkeypatch.setattr(
        storage_quotas, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid))
    )
    monkeypatch.setattr(
        storage_quotas, "getgrgid", lambda gid: (_ for _ in ()).throw(KeyError(gid))
    )
    assert storage_quotas._safe_username(7) == "7"
    assert storage_quotas._safe_groupname(8) == "8"

    monkeypatch.delenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", raising=False)
    monkeypatch.setenv("CONFIG_omero_managed_dir", "ManagedRepository")
    monkeypatch.setenv("OMERO_DATA_DIR", "")
    assert storage_quotas.managed_group_root() == Path("/OMERO/ManagedRepository")

    missing_root = tmp_path / "missing"
    assert storage_quotas._is_safe_managed_repository_root(missing_root) == (
        False,
        "path does not exist or is not a directory",
    )

    managed_root = tmp_path / "ManagedRepository"
    managed_root.mkdir()
    monkeypatch.setenv("OMERO_DATA_DIR", str(tmp_path))
    real_resolve = Path.resolve

    def _resolve(self, *args, **kwargs):
        """Resolve the resolve.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `real_resolve` result. Raises: FileNotFoundError for the exercised failure path.
        """
        if self == managed_root:
            raise FileNotFoundError("deferred mount metadata")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _resolve)
    assert storage_quotas._is_safe_managed_repository_root(managed_root) == (True, "")


def test_storage_quota_state_and_log_helpers_cover_normalization_paths(
    monkeypatch,
    tmp_path,
):
    """Verify storage quota state and log helpers cover normalization paths.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in storage quota state and log helpers cover normalization paths.
    """
    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps({"quotas_gb": {}, "logs": []}),
        encoding="utf-8",
    )
    loaded = storage_quotas._load_state(state_path)
    assert loaded[storage_quotas.STATE_SCHEMA_VERSION_KEY] == (
        storage_quotas.STATE_SCHEMA_VERSION
    )

    with pytest.raises(TypeError, match="Expected 'logs' to be a list"):
        storage_quotas._append_log({"logs": "bad"}, "info", "message")

    monkeypatch.setattr(storage_quotas, "DEFAULT_LOG_LIMIT", 2)
    state = {"logs": []}
    storage_quotas._append_log(state, "info", "first")
    storage_quotas._append_log(state, "info", "first")
    storage_quotas._append_log(state, "info", "second")
    storage_quotas._append_log(state, "warning", "third")
    assert [entry["message"] for entry in state["logs"]] == ["second", "third"]

    cache = storage_quotas._reconcile_event_cache({"_reconcile_event_cache": "bad"})
    assert cache == {}

    with pytest.raises(storage_quotas.QuotaError, match="must not be empty"):
        storage_quotas._normalize_group("   ")

    with pytest.raises(storage_quotas.QuotaError, match="Invalid quota value"):
        storage_quotas._normalize_quota_gb("not-a-number")

    with pytest.raises(storage_quotas.QuotaError, match="Invalid quota value"):
        storage_quotas._normalize_quota_gb(["not", "a", "scalar"])


def test_storage_quota_csv_filesystem_and_state_helpers_cover_edge_cases(
    monkeypatch,
    tmp_path,
):
    """Verify storage quota csv filesystem and state helpers cover edge cases.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in storage quota csv filesystem and state helpers cover edge cases.
    """
    with pytest.raises(storage_quotas.QuotaError, match="CSV file is empty"):
        storage_quotas.import_quotas_csv("")

    with pytest.raises(storage_quotas.QuotaError, match="at least 2 columns"):
        storage_quotas.import_quotas_csv("Group,Quota [GB]\nonly-group\n")

    with pytest.raises(storage_quotas.QuotaError, match="no quota rows"):
        storage_quotas.import_quotas_csv("Group,Quota [GB]\n,\n")

    assert storage_quotas.list_group_directories(tmp_path / "missing") == []

    class _FakePath:
        """Path-like object for quota safety edge coverage."""

        def __init__(self, action):
            """Create `_FakePath` with `action`.

            Inputs: `action` string. Output: initialized fake path.
            """
            self.action = action

        def __str__(self):
            """Return a stable display path.

            Inputs: none. Output: fake path text.
            """
            return "fake-quota-path"

        def is_symlink(self):
            """Return or raise the configured symlink result.

            Inputs: none. Output: bool symlink result. Raises: OSError for the
            configured read-failure case.
            """
            if self.action == "raise-symlink":
                raise OSError("denied")
            return self.action == "symlink"

        def stat(self, follow_symlinks=False):
            """Raise a deterministic stat failure.

            Inputs: `follow_symlinks` flag. Output: none. Raises: OSError.
            """
            raise OSError("denied")

    with pytest.raises(storage_quotas.QuotaError, match="must not be a symlink"):
        storage_quotas._assert_not_symlink(_FakePath("symlink"), "Quota state file")
    with pytest.raises(storage_quotas.QuotaError, match="Could not inspect"):
        storage_quotas._assert_not_symlink(
            _FakePath("raise-symlink"), "Quota state file"
        )

    original_os_name = storage_quotas.os.name
    monkeypatch.setattr(storage_quotas.os, "name", "posix", raising=False)
    with pytest.raises(storage_quotas.QuotaError, match="Could not inspect"):
        storage_quotas._assert_not_world_writable(
            _FakePath("raise-stat"), "Quota state file"
        )
    monkeypatch.setattr(storage_quotas.os, "name", original_os_name, raising=False)
    monkeypatch.setattr(
        storage_quotas, "_assert_not_world_writable", lambda *args: None
    )

    file_parent = tmp_path / "not-a-dir"
    file_parent.write_text("plain", encoding="utf-8")
    with pytest.raises(storage_quotas.QuotaError, match="parent is not a directory"):
        storage_quotas._assert_quota_state_path_safe(file_parent / "state.json")

    directory_state = tmp_path / "state-directory.json"
    directory_state.mkdir()
    with pytest.raises(storage_quotas.QuotaError, match="not a regular file"):
        storage_quotas._assert_quota_state_path_safe(directory_state)

    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: False if str(self) == "/proc/mounts" else real_exists(self),
    )
    assert storage_quotas.detect_filesystem(tmp_path) == storage_quotas.FilesystemInfo(
        fs_type="unknown",
        mount_point="",
        source="",
    )

    monkeypatch.setattr(Path, "exists", real_exists)
    real_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, encoding="utf-8": "badline\n/dev/sda1 /other ext4 rw 0 0\n",
    )
    assert storage_quotas.detect_filesystem(tmp_path) == storage_quotas.FilesystemInfo(
        fs_type="unknown",
        mount_point="",
        source="",
    )
    monkeypatch.setattr(Path, "read_text", real_read_text)

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": [],
                "logs": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    state = storage_quotas.get_state()
    assert state["quotas_gb"] == {}
    assert state["logs"] == []


def test_reconcile_quotas_covers_invalid_state_entries_and_persist_failure(
    monkeypatch,
    tmp_path,
):
    """Do not report successful reconciliation after a persistence failure.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in reconcile quotas covers invalid state entries and persist warnings.
    """
    invalid_state_path = tmp_path / "invalid-state.json"
    invalid_state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": [],
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(invalid_state_path))
    with pytest.raises(TypeError, match="Expected 'quotas_gb' to be a dict"):
        storage_quotas.reconcile_quotas([])

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": {"group-a": "bad"},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    managed_root = tmp_path / "ManagedRepository"
    managed_root.mkdir()
    monkeypatch.setattr(
        storage_quotas,
        "resolve_managed_group_root",
        lambda known_groups: (managed_root, "configured"),
    )
    monkeypatch.setattr(
        storage_quotas,
        "_is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setattr(
        storage_quotas,
        "detect_filesystem",
        lambda path: storage_quotas.FilesystemInfo("ext4", "/", "/dev/sda1"),
    )
    monkeypatch.setattr(
        storage_quotas,
        "managed_repository_compatibility",
        lambda: {
            "template": storage_quotas.EXPECTED_MANAGED_REPOSITORY_PREFIX,
            "expected_prefix": storage_quotas.EXPECTED_MANAGED_REPOSITORY_PREFIX,
            "is_compatible": True,
        },
    )
    monkeypatch.setattr(
        storage_quotas, "_path_access_summary", lambda path: {"mode_octal": "0770"}
    )
    monkeypatch.setattr(storage_quotas, "is_quota_enforcement_available", lambda: True)
    monkeypatch.setattr(
        storage_quotas,
        "_write_state",
        lambda path, state: (_ for _ in ()).throw(OSError("readonly")),
    )

    with pytest.raises(storage_quotas.QuotaError, match="storage is unavailable"):
        storage_quotas.reconcile_quotas([])


@pytest.mark.parametrize("second_writer", ["upsert", "reconcile"])
def test_quota_transactions_coordinate_separate_processes(
    tmp_path, monkeypatch, second_writer
):
    """Exercise real process locks around both quota mutation entry points.

    Inputs: temporary state, configured environment, and second writer type.
    Output: neither independent process loses the other process's quota.
    """
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("OMERO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(tmp_path / "managed"))
    context = multiprocessing.get_context("fork")
    writing = context.Event()
    release = context.Event()
    second_started = context.Event()
    real_write = storage_quotas._write_state

    def paused_write(path, state):
        """Pause the first transaction at its commit boundary.

        Inputs: state path and new document. Output: committed state after release.
        """
        if multiprocessing.current_process().name == "quota-first-writer":
            writing.set()
            if not release.wait(20):
                raise RuntimeError("Quota test did not release the first transaction")
        real_write(path, state)

    def write_second():
        """Attempt an independent update while the first transaction is open.

        Inputs: closed-over fixture and writer mode. Output: persisted second quota.
        """
        second_started.set()
        if second_writer == "reconcile":
            os.environ[storage_quotas.AUTO_GROUP_QUOTA_ENV] = "true"
            storage_quotas.reconcile_quotas(["fixture-second"])
        else:
            storage_quotas.upsert_quotas([("fixture-second", 0.25)])

    monkeypatch.setattr(storage_quotas, "_write_state", paused_write)
    first = context.Process(
        name="quota-first-writer",
        target=storage_quotas.upsert_quotas,
        args=([("fixture-first", 1.0)],),
    )
    second = context.Process(target=write_second)
    try:
        first.start()
        assert writing.wait(10)
        second.start()
        assert second_started.wait(10)
        with state_path.with_suffix(".json.lock").open("r+") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        release.set()
        for process in (first, second):
            if process.pid is not None:
                process.join(20)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
    assert first.exitcode == second.exitcode == 0
    assert json.loads(state_path.read_text())["quotas_gb"] == {
        "fixture-first": 1.0,
        "fixture-second": 0.25,
    }


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "public"])
def test_quota_lock_rejects_unsafe_existing_objects(tmp_path, monkeypatch, kind):
    """Reject sidecar substitution without altering the referenced object.

    Inputs: temporary storage, configured state path and unsafe lock kind.
    Output: the update fails and the unrelated object's content is unchanged.
    """
    path = tmp_path / "state.json"
    lock = path.with_suffix(".json.lock")
    target = tmp_path / "unrelated.txt"
    target.write_text("preserve")
    target.chmod(0o600)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(path))
    if kind == "symlink":
        lock.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, lock)
    elif kind == "directory":
        lock.mkdir()
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.touch(mode=0o644)
    with pytest.raises(storage_quotas.QuotaError):
        storage_quotas.upsert_quotas([("fixture", 1)])
    assert target.read_text() == "preserve"
    assert not path.exists()


def test_atomic_quota_write_retains_state_on_sync_failure(tmp_path, monkeypatch):
    """Never replace existing state when the temporary file cannot be synced.

    Inputs: temporary files and an injected fsync failure. Output: original state
    and unrelated legacy temporary data survive, with no new temporary remnants.
    """
    path = tmp_path / "state.json"
    path.write_text('{"quotas_gb":{"fixture":1},"logs":[]}')
    original = path.read_bytes()
    legacy = path.with_suffix(".json.tmp")
    legacy.write_text("operator-owned-recovery-data")

    def fail_sync(_descriptor):
        """Model a failed durability operation. Inputs: descriptor. Output: error."""
        raise OSError("durability failure")

    monkeypatch.setattr(storage_quotas.os, "fsync", fail_sync)
    with pytest.raises(storage_quotas.QuotaError, match="persisted atomically"):
        storage_quotas._write_state(path, {"quotas_gb": {"other": 2}, "logs": []})
    assert path.read_bytes() == original
    assert legacy.read_text() == "operator-owned-recovery-data"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, False])
def test_quota_update_rejects_nonfinite_and_boolean_values(
    tmp_path, monkeypatch, value
):
    """Reject values that cannot represent a real quota before persisting them.

    Inputs: temporary state, configured environment and invalid numeric input.
    Output: a validation error with the existing document unchanged.
    """
    path = tmp_path / "state.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(path))
    storage_quotas.upsert_quotas([("fixture", 1)])
    original = path.read_bytes()
    with pytest.raises(storage_quotas.QuotaError, match="Invalid quota value"):
        storage_quotas.upsert_quotas([("fixture", value)])
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "0.00001"])
def test_quota_environment_requires_finite_positive_precision(monkeypatch, value):
    """Reject nonfinite limits and values rounded down to zero.

    Inputs: patched minimum and invalid value. Output: explicit validation error.
    """
    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, value)
    with pytest.raises(storage_quotas.QuotaError, match="greater than 0"):
        storage_quotas.min_quota_gb()
