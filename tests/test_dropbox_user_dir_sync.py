from __future__ import annotations

from dataclasses import replace
import importlib.util
import os
import stat
import sys
import tempfile
import types
from pathlib import Path
from unittest import TestCase, main, mock


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "startup" / "dropbox_user_dir_sync.py"
DROPBOX_EXTERNAL_WRITE_MODE = (
    stat.S_ISGID | stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH
)
TEST_AUTH_ENV_VAR = "OMERO_TEST_AUTH_ENV"
TEST_AUTH_VALUE = "unused-auth-value"


def load_helper():
    """Return load helper."""
    spec = importlib.util.spec_from_file_location("dropbox_user_dir_sync", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load dropbox_user_dir_sync helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


class _ConfigService:
    """Represent config service."""

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def getConfigValue(self, name: str) -> str | None:
        """Return get config value."""
        return self.values.get(name)


class _AdminService:
    """Represent admin service."""

    def __init__(self, usernames: list[str]) -> None:
        self.usernames = usernames

    def lookupExperimenters(self) -> list[types.SimpleNamespace]:
        """Handle lookup experimenters."""
        return [
            types.SimpleNamespace(omeName=types.SimpleNamespace(val=username))
            for username in self.usernames
        ]


class _Conn:
    """Represent conn."""

    def __init__(self, values: dict[str, str], usernames: list[str]) -> None:
        self.config_service = _ConfigService(values)
        self.admin_service = _AdminService(usernames)
        self.closed = False

    def getConfigService(self) -> _ConfigService:
        """Return get config service."""
        return self.config_service

    def getAdminService(self) -> _AdminService:
        """Return get admin service."""
        return self.admin_service

    def close(self) -> None:
        """Handle close."""
        self.closed = True


def _config(**overrides: object):
    """Handle config."""
    config = helper.SyncConfig(
        host="unused",
        port=4064,
        secure=True,
        username="root",
        password_env=TEST_AUTH_ENV_VAR,
        create_root=True,
        owner="",
        group="",
        mode=DROPBOX_EXTERNAL_WRITE_MODE,
        allow_world_writable=False,
        status_file=None,
        connect_retries=1,
        connect_retry_delay_seconds=0,
    )
    return replace(config, **overrides)


class DropBoxUserDirSyncTests(TestCase):
    """Test cases for drop box user dir sync tests."""

    def test_resolves_default_root_from_omero_config(self) -> None:
        """Verify test resolves default root from OMERO config."""
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
        """Verify test resolves single watch dir from OMERO config."""
        conn = _Conn(
            {
                "omero.fs.importUsers": "default",
                "omero.fs.watchDir": "/dropbox-acceptor",
            },
            [],
        )

        self.assertEqual(Path("/dropbox-acceptor"), helper.resolve_dropbox_root(conn))

    def test_rejects_multiple_watch_dirs_for_username_root_convention(self) -> None:
        """Verify test rejects multiple watch dirs for username behavior."""
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
        """Verify test sync creates only safe first level usern behavior."""
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
            self.assertEqual(
                DROPBOX_EXTERNAL_WRITE_MODE,
                stat.S_IMODE((root / "alice").stat().st_mode),
            )

    def test_new_dropbox_root_inherits_parent_owner_group_and_mode(self) -> None:
        """Verify test new dropbox root inherits parent owner g behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "data"
            parent.mkdir()
            root = parent / "DropBox"

            root_state = helper.ensure_root(
                root,
                create_root=True,
                mode=DROPBOX_EXTERNAL_WRITE_MODE,
            )

            parent_stat = parent.stat()
            root_stat = root.stat()
            self.assertTrue(root_state.created)
            self.assertEqual(
                (parent_stat.st_uid, parent_stat.st_gid),
                (root_stat.st_uid, root_stat.st_gid),
            )
            self.assertEqual(
                DROPBOX_EXTERNAL_WRITE_MODE, stat.S_IMODE(root_stat.st_mode)
            )

    def test_new_dropbox_root_requires_existing_parent(self) -> None:
        """Verify test new dropbox root requires existing parent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "missing" / "DropBox"

            with self.assertRaisesRegex(helper.SyncError, "parent does not exist"):
                helper.ensure_root(
                    root,
                    create_root=True,
                    mode=DROPBOX_EXTERNAL_WRITE_MODE,
                )

    def test_sync_rejects_existing_username_symlink(self) -> None:
        """Verify test sync rejects existing username symlink."""
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
        """Verify test empty owner and group inherit dropbox ro behavior."""
        self.assertEqual(123, helper.resolve_user("", default_uid=123))
        self.assertEqual(456, helper.resolve_group("", default_gid=456))

    def test_sync_does_not_touch_existing_directory_permissions_when_matching(
        self,
    ) -> None:
        """Verify test sync does not touch existing directory p behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dropbox"
            root.mkdir()
            root_stat = root.stat()
            helper.ensure_user_directory(
                root,
                root.resolve(strict=True),
                "alice",
                _config(create_root=False),
                root_stat.st_uid,
                root_stat.st_gid,
            )
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
        """Verify test mode validation rejects world writable b behavior."""
        with self.assertRaisesRegex(helper.SyncError, "world-write"):
            helper.parse_mode("0777", allow_world_writable=False)

    def test_status_file_records_success_counts(self) -> None:
        """Verify test status file records success counts."""
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
        """Verify test failed connection attempts are closed be behavior."""

        class FakeGateway:
            """Test double for fake gateway."""

            instances: list["FakeGateway"] = []

            def __init__(self, *args: object, **kwargs: object) -> None:
                self.closed_with: bool | None = None
                FakeGateway.instances.append(self)

            @staticmethod
            def connect() -> bool:
                """Handle connect."""
                return False

            def close(self, hard: bool = True) -> None:
                """Handle close."""
                self.closed_with = hard

        config = _config(connect_retries=2)

        with (
            mock.patch.dict(os.environ, {TEST_AUTH_ENV_VAR: TEST_AUTH_VALUE}),
            mock.patch.object(helper, "import_omero_gateway", return_value=FakeGateway),
            self.assertRaisesRegex(helper.SyncError, "could not connect"),
        ):
            helper.connect(config)

        self.assertEqual(2, len(FakeGateway.instances))
        self.assertEqual(
            [True, True], [conn.closed_with for conn in FakeGateway.instances]
        )

    def test_close_connection_logs_unexpected_close_failures(self) -> None:
        """Verify test close connection logs unexpected close f behavior."""

        class FailingClose:
            """Represent failing close."""

            @staticmethod
            def close(hard: bool = True) -> None:
                """Handle close."""
                raise RuntimeError("close failed")

        with self.assertLogs(helper.LOGGER, level="DEBUG") as captured:
            helper.close_connection(FailingClose())

        self.assertTrue(
            any(
                "Failed to close OMERO connection cleanly." in message
                for message in captured.output
            )
        )

    def test_helper_does_not_encode_installation_specific_ids_or_paths(self) -> None:
        """Verify test helper does not encode installation spec behavior."""
        helper_text = HELPER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("65534", helper_text)
        self.assertNotIn("/opt/omero/omero_data", helper_text)


if __name__ == "__main__":
    main()
