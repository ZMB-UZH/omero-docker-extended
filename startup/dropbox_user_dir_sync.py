#!/usr/bin/env python3
"""Synchronize OMERO.dropbox per-user acceptor directories.

The script reads the DropBox acceptor root from live OMERO configuration:

* ``omero.fs.watchDir`` when set to a single directory
* otherwise ``omero.data.dir`` joined with ``omero.fs.defaultDropBoxDir``

It then creates only the missing first-level username directories. It does not
walk payload trees and never changes files below existing user directories.
"""

from __future__ import annotations

import argparse
import grp
import logging
import os
import pwd
import re
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LOGGER = logging.getLogger(__name__)


class SyncError(RuntimeError):
    """Raised for configuration or synchronization failures."""


@dataclass(frozen=True)
class SyncConfig:
    host: str
    port: int
    secure: bool
    username: str
    password_env: str
    create_root: bool
    owner: str
    group: str
    mode: int
    allow_world_writable: bool
    status_file: Path | None
    connect_retries: int
    connect_retry_delay_seconds: float


@dataclass(frozen=True)
class SyncResult:
    root: Path
    eligible_users: int
    created: int
    existing: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class RootState:
    stat: os.stat_result
    created: bool


def parse_bool(value: str, *, name: str) -> bool:
    """Parse bool.

    Inputs: `value`, `name`. Output: `bool`. Raises on invalid or unavailable state.
    """
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SyncError(f"{name} must be a boolean value, got {value!r}")


def parse_mode(value: str, *, allow_world_writable: bool) -> int:
    """Parse mode.

    Inputs: `value`, `allow_world_writable`. Output: `int`. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    raw = value.strip()
    if not re.fullmatch(r"[0-7]{3,4}", raw):
        raise SyncError(
            f"directory mode must be a 3- or 4-digit octal value, got {value!r}"
        )
    mode = int(raw, 8)
    if mode & stat.S_IWOTH and not allow_world_writable:
        raise SyncError(
            "directory mode grants world-write; set "
            "OMERO_DROPBOX_USER_DIR_ALLOW_WORLD_WRITABLE=1 only if this is intentional"
        )
    return mode


def resolve_user(value: str, *, default_uid: int) -> int:
    """Resolve user.

    Inputs: `value`, `default_uid`. Output: `int`. Raises on invalid or unavailable
    state.

    state.
    """
    raw = value.strip()
    if not raw:
        return default_uid
    if raw.isdigit():
        return int(raw)
    try:
        return pwd.getpwnam(raw).pw_uid
    except KeyError as exc:
        raise SyncError(f"unknown owner user for DropBox directories: {raw!r}") from exc


def resolve_group(value: str, *, default_gid: int) -> int:
    """Resolve group.

    Inputs: `value`, `default_gid`. Output: `int`. Raises on invalid or unavailable
    state.

    state.
    """
    raw = value.strip()
    if not raw:
        return default_gid
    if raw.isdigit():
        return int(raw)
    try:
        return grp.getgrnam(raw).gr_gid
    except KeyError as exc:
        raise SyncError(
            f"unknown owner group for DropBox directories: {raw!r}"
        ) from exc


def sanitize_for_log(value: str) -> str:
    """Sanitize for log.

    Inputs: `value`. Output: `str`.
    """
    return re.sub(r"[\r\n\t\x00-\x1f\x7f]+", "_", value)[:256]


def validate_username_component(username: str) -> str | None:
    """Validate username component.

    Inputs: `username`. Output: `str | None`.
    """
    if not username:
        return "empty username"
    if username in {".", ".."}:
        return "reserved path component"
    if "/" in username or "\\" in username:
        return "path separator in username"
    if "\x00" in username or any(ord(char) < 32 for char in username):
        return "control character in username"
    if len(os.fsencode(username)) > 255:
        return "username path component is longer than 255 bytes"
    return None


def import_omero_gateway():
    """Import OMERO gateway.

    Inputs: none. Output: `BlitzGateway`. Raises on invalid or unavailable state.
    """
    try:
        from omero.gateway import BlitzGateway
    except ImportError as exc:  # pragma: no cover - exercised in image/runtime
        raise SyncError(
            "OMERO Python gateway is not importable in this environment"
        ) from exc
    return BlitzGateway


def close_connection(conn) -> None:
    """Close connection.

    Inputs: `conn`. Output: None.
    """
    try:
        conn.close(hard=True)
    except TypeError:  # pragma: no cover - compatibility with older gateways
        conn.close()
    except Exception:  # pragma: no cover - depends on gateway shutdown state
        LOGGER.debug("Failed to close OMERO connection cleanly.", exc_info=True)


def connect(config: SyncConfig):
    """Open the connection.

    Inputs: `config`. Output: `conn`. Raises on invalid or unavailable state.
    """
    password = os.environ.get(config.password_env, "")
    if not password:
        raise SyncError(
            f"{config.password_env} must be set when DropBox user directory sync is enabled"
        )

    BlitzGateway = import_omero_gateway()
    last_error: Exception | None = None
    for attempt in range(1, config.connect_retries + 1):
        conn = BlitzGateway(
            config.username,
            password,
            host=config.host,
            port=config.port,
            secure=config.secure,
        )
        try:
            if conn.connect():
                return conn
            last_error = SyncError("OMERO login returned false")
        except Exception as exc:  # pragma: no cover - depends on live OMERO timing
            last_error = exc
        close_connection(conn)
        if attempt < config.connect_retries:
            time.sleep(config.connect_retry_delay_seconds)
    raise SyncError(
        f"could not connect to OMERO after {config.connect_retries} attempt(s): {last_error}"
    )


def config_value(conn, name: str, default: str = "") -> str:
    """Config value.

    Inputs: `conn`, `name`, `default`. Output: `str`.
    """
    value = conn.getConfigService().getConfigValue(name)
    if value is None:
        return default
    return str(value)


def resolve_dropbox_root(conn) -> Path:
    """Resolve dropbox root.

    Inputs: `conn`. Output: `Path`. Raises on invalid or unavailable state.
    """
    import_users = config_value(conn, "omero.fs.importUsers", "default").strip()
    watch_dir_raw = config_value(conn, "omero.fs.watchDir", "").strip()
    nonempty_watch_dirs = [
        part.strip() for part in watch_dir_raw.split(";") if part.strip()
    ]

    if import_users and import_users != "default":
        raise SyncError(
            "OMERO_DROPBOX user directory sync requires omero.fs.importUsers=default "
            "so usernames are first-level directories below one acceptor root"
        )

    if len(nonempty_watch_dirs) > 1:
        raise SyncError(
            "OMERO_DROPBOX user directory sync requires a single DropBox acceptor root; "
            "omero.fs.watchDir contains multiple directories"
        )

    if nonempty_watch_dirs:
        root = Path(nonempty_watch_dirs[0])
    else:
        data_dir = config_value(conn, "omero.data.dir", "").strip()
        default_dropbox_dir = config_value(
            conn, "omero.fs.defaultDropBoxDir", "DropBox"
        ).strip()
        if not data_dir:
            raise SyncError(
                "omero.data.dir is empty; cannot resolve default DropBox root"
            )
        if not default_dropbox_dir:
            raise SyncError(
                "omero.fs.defaultDropBoxDir is empty; cannot resolve default DropBox root"
            )
        default_path = Path(default_dropbox_dir)
        root = (
            default_path
            if default_path.is_absolute()
            else Path(data_dir) / default_path
        )

    if not root.is_absolute():
        raise SyncError(f"resolved DropBox root must be absolute, got {root}")
    return root


def list_experimenter_usernames(conn) -> list[str]:
    """List experimenter usernames.

    Inputs: `conn`. Output: `list[str]`.
    """
    experimenters = conn.getAdminService().lookupExperimenters()
    usernames = [
        str(exp.omeName.val) for exp in experimenters if exp.omeName and exp.omeName.val
    ]
    return sorted(set(usernames), key=str.casefold)


def filter_usernames(usernames: Iterable[str]) -> tuple[list[str], int]:
    """Filter usernames.

    Inputs: `usernames`. Output: `tuple[list[str], int]`.
    """
    eligible: list[str] = []
    skipped = 0
    for username in usernames:
        reason = validate_username_component(username)
        if reason:
            print(
                f"WARN skipped unsafe OMERO username {sanitize_for_log(username)!r}: {reason}",
                file=sys.stderr,
            )
            skipped += 1
            continue
        eligible.append(username)
    return eligible, skipped


def ensure_root(root: Path, *, create_root: bool, mode: int) -> RootState:
    """Ensure root.

    Inputs: `root`, `create_root`, `mode`. Output: `RootState`. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    try:
        root_lstat = root.lstat()
    except FileNotFoundError:
        if not create_root:
            raise SyncError(f"DropBox root does not exist: {root}") from None
        parent = root.parent
        try:
            parent_lstat = parent.lstat()
        except FileNotFoundError:
            raise SyncError(f"DropBox root parent does not exist: {parent}") from None
        if not stat.S_ISDIR(parent_lstat.st_mode):
            raise SyncError(f"DropBox root parent is not a directory: {parent}")
        root.mkdir(mode=mode, exist_ok=False)
        root_lstat = root.lstat()
        if (root_lstat.st_uid, root_lstat.st_gid) != (
            parent_lstat.st_uid,
            parent_lstat.st_gid,
        ):
            os.chown(root, parent_lstat.st_uid, parent_lstat.st_gid)
            root_lstat = root.lstat()
        if stat.S_IMODE(root_lstat.st_mode) != mode:
            os.chmod(root, mode)
        root_lstat = root.lstat()
        return RootState(root_lstat, created=True)

    if stat.S_ISLNK(root_lstat.st_mode):
        raise SyncError(f"DropBox root must not be a symlink: {root}")
    if not stat.S_ISDIR(root_lstat.st_mode):
        raise SyncError(f"DropBox root is not a directory: {root}")
    return RootState(root_lstat, created=False)


def ensure_user_directory(
    root: Path,
    root_real: Path,
    username: str,
    config: SyncConfig,
    uid: int,
    gid: int,
) -> str:
    """Ensure user directory.

    Inputs: `root`, `root_real`, `username`, `config`, `uid`, `gid`. Output: `str`.
    Raises on invalid or unavailable state.
    """
    target = root / username
    if target.parent.resolve(strict=True) != root_real:
        raise SyncError(
            f"resolved username directory escaped DropBox root: {sanitize_for_log(username)!r}"
        )

    created = False
    try:
        target_lstat = target.lstat()
    except FileNotFoundError:
        target.mkdir(mode=config.mode)
        created = True
        target_lstat = target.lstat()

    if stat.S_ISLNK(target_lstat.st_mode):
        raise SyncError(
            f"username directory is a symlink and will not be modified: {target}"
        )
    if not stat.S_ISDIR(target_lstat.st_mode):
        raise SyncError(f"username path exists but is not a directory: {target}")

    if (target_lstat.st_uid, target_lstat.st_gid) != (uid, gid):
        os.chown(target, uid, gid)
        target_lstat = target.lstat()

    if stat.S_IMODE(target_lstat.st_mode) != config.mode:
        os.chmod(target, config.mode)
    return "created" if created else "existing"


def write_status(path: Path, values: dict[str, str | int]) -> None:
    """Write status.

    Inputs: `path`, `values`. Output: None.
    """
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def sync(config: SyncConfig) -> SyncResult:
    """Sync.

    Inputs: `config`. Output: `SyncResult`.
    """
    conn = connect(config)
    try:
        root = resolve_dropbox_root(conn)
        usernames = list_experimenter_usernames(conn)
    finally:
        close_connection(conn)

    eligible_users, skipped = filter_usernames(usernames)
    root_state = ensure_root(root, create_root=config.create_root, mode=config.mode)
    root_real = root.resolve(strict=True)
    uid = resolve_user(config.owner, default_uid=root_state.stat.st_uid)
    gid = resolve_group(config.group, default_gid=root_state.stat.st_gid)

    created = 0
    existing = 0
    failed = 0
    for username in eligible_users:
        try:
            result = ensure_user_directory(root, root_real, username, config, uid, gid)
        except Exception as exc:
            failed += 1
            print(
                f"ERROR failed to ensure DropBox directory for {sanitize_for_log(username)!r}: {exc}",
                file=sys.stderr,
            )
            continue
        if result == "created":
            created += 1
        else:
            existing += 1

    return SyncResult(
        root=root,
        eligible_users=len(eligible_users),
        created=created,
        existing=existing,
        skipped=skipped,
        failed=failed,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Inputs: none. Output: `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--host", required=True)
    sync_parser.add_argument("--port", required=True, type=int)
    sync_parser.add_argument("--secure", required=True)
    sync_parser.add_argument("--username", default="root")
    sync_parser.add_argument("--password-env", default="ROOTPASS")
    sync_parser.add_argument("--create-root", required=True)
    sync_parser.add_argument("--owner", default="")
    sync_parser.add_argument("--group", default="")
    sync_parser.add_argument("--mode", required=True)
    sync_parser.add_argument("--allow-world-writable", required=True)
    sync_parser.add_argument("--status-file", default="")
    sync_parser.add_argument("--connect-retries", required=True, type=int)
    sync_parser.add_argument("--connect-retry-delay-seconds", required=True, type=float)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--mode", required=True)
    validate_parser.add_argument("--allow-world-writable", required=True)
    return parser


def config_from_args(args: argparse.Namespace) -> SyncConfig:
    """Config from args.

    Inputs: `args`. Output: `SyncConfig`. Raises on invalid or unavailable state.
    """
    allow_world_writable = parse_bool(
        args.allow_world_writable, name="allow-world-writable"
    )
    if args.connect_retries < 1:
        raise SyncError("connect retries must be at least 1")
    if args.connect_retry_delay_seconds < 0:
        raise SyncError("connect retry delay must be non-negative")
    return SyncConfig(
        host=args.host,
        port=args.port,
        secure=parse_bool(args.secure, name="secure"),
        username=args.username,
        password_env=args.password_env,
        create_root=parse_bool(args.create_root, name="create-root"),
        owner=args.owner,
        group=args.group,
        mode=parse_mode(args.mode, allow_world_writable=allow_world_writable),
        allow_world_writable=allow_world_writable,
        status_file=Path(args.status_file) if args.status_file else None,
        connect_retries=args.connect_retries,
        connect_retry_delay_seconds=args.connect_retry_delay_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    """Execute the command entrypoint.

    Inputs: `argv`. Output: `int`.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            allow_world_writable = parse_bool(
                args.allow_world_writable, name="allow-world-writable"
            )
            parse_mode(args.mode, allow_world_writable=allow_world_writable)
            return 0

        config = config_from_args(args)
        result = sync(config)
        status = "ok" if result.failed == 0 else "error"
        now = int(time.time())
        status_values: dict[str, str | int] = {
            "status": status,
            "last_success_epoch": now if status == "ok" else 0,
            "dropbox_root": str(result.root),
            "eligible_user_count": result.eligible_users,
            "created_count": result.created,
            "existing_count": result.existing,
            "skipped_count": result.skipped,
            "failed_count": result.failed,
        }
        if config.status_file:
            write_status(config.status_file, status_values)
        for key, value in status_values.items():
            print(f"{key}={value}")
        return 0 if status == "ok" else 1
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        status_file = (
            Path(getattr(args, "status_file", ""))
            if getattr(args, "status_file", "")
            else None
        )
        if status_file:
            write_status(
                status_file,
                {
                    "status": "error",
                    "last_success_epoch": 0,
                    "dropbox_root": "",
                    "eligible_user_count": 0,
                    "created_count": 0,
                    "existing_count": 0,
                    "skipped_count": 0,
                    "failed_count": 1,
                },
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
