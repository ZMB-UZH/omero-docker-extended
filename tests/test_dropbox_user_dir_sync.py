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
    """Return load helper.

    Inputs: none. Output: `module`. Raises: RuntimeError for the exercised failure path.
    """
    spec = importlib.util.spec_from_file_location("dropbox_user_dir_sync", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load dropbox_user_dir_sync helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


class _ConfigService:
    """Test double for config service behavior in this module."""

    def __init__(self, values: dict[str, str]) -> None:
        """Create `_ConfigService` with `values`.

        Inputs: `values`. Output: None.
        """
        self.values = values

    def getConfigValue(self, name: str) -> str | None:
        """Return `_ConfigService`'s fake config value.

        Inputs: `name`. Output: `str | None`.
        """
        return self.values.get(name)


class _AdminService:
    """Test double for admin service behavior in this module."""

    def __init__(self, usernames: list[str]) -> None:
        """Create `_AdminService` with `usernames`.

        Inputs: `usernames`. Output: None.
        """
        self.usernames = usernames

    def lookupExperimenters(self) -> list[types.SimpleNamespace]:
        """Return the lookup Experimenters for `_AdminService`.

        Inputs: none. Output: `list[types.SimpleNamespace]`.
        """
        return [
            types.SimpleNamespace(omeName=types.SimpleNamespace(val=username))
            for username in self.usernames
        ]


class _Conn:
    """Test double for conn behavior in this module."""

    def __init__(self, values: dict[str, str], usernames: list[str]) -> None:
        """Create `_Conn` with `values` and `usernames`.

        Inputs: `values`, `usernames`. Output: None.
        """
        self.config_service = _ConfigService(values)
        self.admin_service = _AdminService(usernames)
        self.closed = False

    def getConfigService(self) -> _ConfigService:
        """Return `_Conn`'s fake config service.

        Inputs: none. Output: `_ConfigService`.
        """
        return self.config_service

    def getAdminService(self) -> _AdminService:
        """Return the fake admin service value used by this test double.

        Inputs: none. Output: `_AdminService`.
        """
        return self.admin_service

    def close(self) -> None:
        """Close `_Conn`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


def _config(**overrides: object):
    """Return the config.

    Inputs: `**overrides` (object). Output: `replace` result.
    """
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
        """Verify resolves default root from OMERO config.

        Inputs: repository fixtures. Output: fails on regressions in resolves default root from OMERO config.
        """
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
        """Verify resolves single watch dir from OMERO config.

        Inputs: repository fixtures. Output: fails on regressions in resolves single watch dir from OMERO config.
        """
        conn = _Conn(
            {
                "omero.fs.importUsers": "default",
                "omero.fs.watchDir": "/dropbox-acceptor",
            },
            [],
        )

        self.assertEqual(Path("/dropbox-acceptor"), helper.resolve_dropbox_root(conn))

    def test_rejects_multiple_watch_dirs_for_username_root_convention(self) -> None:
        """Confirm rejects multiple watch dirs for username root convention is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in rejects multiple watch dirs for username root convention.
        """
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
        """Verify sync creates only safe first level username directories.

        Inputs: repository fixtures. Output: fails on regressions in sync creates only safe first level username directories.
        """
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
        """Verify new dropbox root inherits parent owner group and mode.

        Inputs: repository fixtures. Output: fails on regressions in new dropbox root inherits parent owner group and mode.
        """
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
        """Verify new dropbox root requires existing parent.

        Inputs: repository fixtures. Output: fails on regressions in new dropbox root requires existing parent.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "missing" / "DropBox"

            with self.assertRaisesRegex(helper.SyncError, "parent does not exist"):
                helper.ensure_root(
                    root,
                    create_root=True,
                    mode=DROPBOX_EXTERNAL_WRITE_MODE,
                )

    def test_sync_rejects_existing_username_symlink(self) -> None:
        """Confirm sync rejects existing username symlink is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions when sync rejects existing username symlink accepts unsafe input.
        """
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
        """Verify empty owner and group inherit dropbox root IDs.

        Inputs: repository fixtures. Output: fails on regressions in empty owner and group inherit dropbox root IDs.
        """
        self.assertEqual(123, helper.resolve_user("", default_uid=123))
        self.assertEqual(456, helper.resolve_group("", default_gid=456))

    def test_sync_does_not_touch_existing_directory_permissions_when_matching(
        self,
    ) -> None:
        """Verify sync does not touch existing directory permissions when matching.

        Inputs: repository fixtures. Output: fails on regressions in sync does not touch existing directory permissions when matching.
        """
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
        """Confirm mode validation rejects world writable by default is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in mode validation rejects world writable by default.
        """
        with self.assertRaisesRegex(helper.SyncError, "world-write"):
            helper.parse_mode("0777", allow_world_writable=False)

    def test_status_file_records_success_counts(self) -> None:
        """Verify status file records success counts.

        Inputs: repository fixtures. Output: fails on regressions in status file records success counts.
        """
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
        """Verify failed connection attempts are closed before retry.

        Inputs: repository fixtures. Output: fails on regressions in failed connection attempts are closed before retry.
        """

        class FakeGateway:
            """Test double for fake gateway."""

            instances: list["FakeGateway"] = []

            def __init__(self, *args: object, **kwargs: object) -> None:
                """Create `FakeGateway` with its default state.

                Inputs: `*args`, `**kwargs`. Output: None.
                """
                self.closed_with: bool | None = None
                FakeGateway.instances.append(self)

            @staticmethod
            def connect() -> bool:
                """Open the connection for `FakeGateway`.

                Inputs: none. Output: `bool`.
                """
                return False

            def close(self, hard: bool = True) -> None:
                """Close `FakeGateway`'s fake resource handle.

                Inputs: `hard`. Output: None.
                """
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
        """Verify close connection logs unexpected close failures.

        Inputs: repository fixtures. Output: fails on regressions in close connection logs unexpected close failures.
        """

        class FailingClose:
            """Test double for failing close behavior in this module."""

            @staticmethod
            def close(hard: bool = True) -> None:
                """Close `FailingClose`'s fake resource handle.

                Inputs: `hard` (bool). Output: None. Raises: RuntimeError when validation or the called operation fails.
                """
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
        """Verify helper does not encode installation specific IDs or paths.

        Inputs: repository fixtures. Output: fails on regressions in helper does not encode installation specific IDs or paths.
        """
        helper_text = HELPER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("65534", helper_text)
        self.assertNotIn("/opt/omero/omero_data", helper_text)


if __name__ == "__main__":
    main()
