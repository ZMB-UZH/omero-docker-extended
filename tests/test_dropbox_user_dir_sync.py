from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "startup" / "dropbox_user_dir_sync.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("dropbox_user_dir_sync", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load dropbox_user_dir_sync helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


class _ConfigService:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def getConfigValue(self, name: str) -> str | None:
        return self.values.get(name)


class _AdminService:
    def __init__(self, usernames: list[str]) -> None:
        self.usernames = usernames

    def lookupExperimenters(self) -> list[types.SimpleNamespace]:
        return [
            types.SimpleNamespace(omeName=types.SimpleNamespace(val=username))
            for username in self.usernames
        ]


class _Conn:
    def __init__(self, values: dict[str, str], usernames: list[str]) -> None:
        self.config_service = _ConfigService(values)
        self.admin_service = _AdminService(usernames)
        self.closed = False

    def getConfigService(self) -> _ConfigService:
        return self.config_service

    def getAdminService(self) -> _AdminService:
        return self.admin_service

    def close(self) -> None:
        self.closed = True


def _config(**overrides: object):
    values = {
        "host": "unused",
        "port": 4064,
        "secure": True,
        "username": "root",
        "password_env": "ROOTPASS",
        "create_root": True,
        "owner": "",
        "group": "",
        "mode": 0o2775,
        "allow_world_writable": False,
        "status_file": None,
        "connect_retries": 1,
        "connect_retry_delay_seconds": 0,
    }
    values.update(overrides)
    return helper.SyncConfig(**values)


class DropBoxUserDirSyncTests(unittest.TestCase):
    def test_resolves_default_root_from_omero_config(self) -> None:
        conn = _Conn(
            {
                "omero.fs.importUsers": "default",
                "omero.fs.watchDir": "",
                "omero.data.dir": "/configured-data",
                "omero.fs.defaultDropBoxDir": "Incoming",
            },
            [],
        )

        self.assertEqual(
            Path("/configured-data/Incoming"), helper.resolve_dropbox_root(conn)
        )

    def test_resolves_single_watch_dir_from_omero_config(self) -> None:
        conn = _Conn(
            {
                "omero.fs.importUsers": "default",
                "omero.fs.watchDir": "/dropbox-acceptor",
            },
            [],
        )

        self.assertEqual(Path("/dropbox-acceptor"), helper.resolve_dropbox_root(conn))

    def test_rejects_multiple_watch_dirs_for_username_root_convention(self) -> None:
        conn = _Conn(
            {
                "omero.fs.importUsers": "default",
                "omero.fs.watchDir": "/one;/two",
            },
            [],
        )

        with self.assertRaisesRegex(helper.SyncError, "single DropBox acceptor root"):
            helper.resolve_dropbox_root(conn)

    def test_sync_creates_only_safe_first_level_username_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dropbox"
            conn = _Conn(
                {
                    "omero.fs.importUsers": "default",
                    "omero.fs.watchDir": str(root),
                },
                ["alice", "bob", "../bad", "bad/name"],
            )
            config = _config()

            with mock.patch.object(helper, "connect", return_value=conn):
                result = helper.sync(config)

            self.assertEqual(2, result.created)
            self.assertEqual(2, result.skipped)
            self.assertTrue((root / "alice").is_dir())
            self.assertTrue((root / "bob").is_dir())
            self.assertEqual(0o2775, stat.S_IMODE((root / "alice").stat().st_mode))

    def test_new_dropbox_root_inherits_parent_owner_group_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "data"
            parent.mkdir()
            root = parent / "DropBox"

            root_state = helper.ensure_root(root, create_root=True, mode=0o2775)

            parent_stat = parent.stat()
            root_stat = root.stat()
            self.assertTrue(root_state.created)
            self.assertEqual(
                (parent_stat.st_uid, parent_stat.st_gid),
                (root_stat.st_uid, root_stat.st_gid),
            )
            self.assertEqual(0o2775, stat.S_IMODE(root_stat.st_mode))

    def test_new_dropbox_root_requires_existing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "missing" / "DropBox"

            with self.assertRaisesRegex(helper.SyncError, "parent does not exist"):
                helper.ensure_root(root, create_root=True, mode=0o2775)

    def test_sync_rejects_existing_username_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dropbox"
            root.mkdir()
            (root / "target").mkdir()
            (root / "alice").symlink_to(root / "target")
            conn = _Conn(
                {
                    "omero.fs.importUsers": "default",
                    "omero.fs.watchDir": str(root),
                },
                ["alice"],
            )

            with mock.patch.object(helper, "connect", return_value=conn):
                result = helper.sync(_config(create_root=False))

            self.assertEqual(1, result.failed)
            self.assertTrue((root / "alice").is_symlink())

    def test_empty_owner_and_group_inherit_dropbox_root_ids(self) -> None:
        self.assertEqual(123, helper.resolve_user("", default_uid=123))
        self.assertEqual(456, helper.resolve_group("", default_gid=456))

    def test_sync_does_not_touch_existing_directory_permissions_when_matching(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dropbox"
            root.mkdir()
            user_dir = root / "alice"
            user_dir.mkdir()
            os.chmod(user_dir, 0o2775)
            conn = _Conn(
                {
                    "omero.fs.importUsers": "default",
                    "omero.fs.watchDir": str(root),
                },
                ["alice"],
            )
            config = _config(create_root=False)

            with (
                mock.patch.object(helper, "connect", return_value=conn),
                mock.patch.object(helper.os, "chown") as chown_mock,
                mock.patch.object(helper.os, "chmod") as chmod_mock,
            ):
                result = helper.sync(config)

            self.assertEqual(1, result.existing)
            chown_mock.assert_not_called()
            chmod_mock.assert_not_called()

    def test_mode_validation_rejects_world_writable_by_default(self) -> None:
        with self.assertRaisesRegex(helper.SyncError, "world-write"):
            helper.parse_mode("0777", allow_world_writable=False)

    def test_status_file_records_success_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dropbox"
            status_file = Path(tmpdir) / "status" / "dropbox.status"
            conn = _Conn(
                {
                    "omero.fs.importUsers": "default",
                    "omero.fs.watchDir": str(root),
                },
                ["alice"],
            )
            config = _config(status_file=status_file)

            with mock.patch.object(helper, "connect", return_value=conn):
                result = helper.sync(config)
                helper.write_status(
                    status_file,
                    {
                        "status": "ok",
                        "last_success_epoch": 123,
                        "dropbox_root": result.root,
                        "eligible_user_count": result.eligible_users,
                        "created_count": result.created,
                        "existing_count": result.existing,
                        "skipped_count": result.skipped,
                        "failed_count": result.failed,
                    },
                )

            status_text = status_file.read_text(encoding="utf-8")
            self.assertIn("status=ok", status_text)
            self.assertIn("dropbox_root=", status_text)
            self.assertIn("created_count=1", status_text)

    def test_failed_connection_attempts_are_closed_before_retry(self) -> None:
        class FakeGateway:
            instances: list["FakeGateway"] = []

            def __init__(self, *args: object, **kwargs: object) -> None:
                self.closed_with: bool | None = None
                FakeGateway.instances.append(self)

            def connect(self) -> bool:
                return False

            def close(self, hard: bool = True) -> None:
                self.closed_with = hard

        config = _config(connect_retries=2)

        with (
            mock.patch.dict(os.environ, {"ROOTPASS": "unused"}),
            mock.patch.object(helper, "import_omero_gateway", return_value=FakeGateway),
            self.assertRaisesRegex(helper.SyncError, "could not connect"),
        ):
            helper.connect(config)

        self.assertEqual(2, len(FakeGateway.instances))
        self.assertEqual(
            [True, True], [conn.closed_with for conn in FakeGateway.instances]
        )

    def test_helper_does_not_encode_installation_specific_ids_or_paths(self) -> None:
        helper_text = HELPER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("65534", helper_text)
        self.assertNotIn("/opt/omero/omero_data", helper_text)


if __name__ == "__main__":
    unittest.main()
