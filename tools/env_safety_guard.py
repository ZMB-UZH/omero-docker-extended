#!/usr/bin/env python3
"""Guard against accidental deletion of untracked deployment configuration files.

This tool maintains a manifest of critical untracked files that must survive
any file-sync, rsync, or tree-replacement operation.  It can:

  --check     Verify every manifest entry exists and is non-empty.  Exit 1 on failure.
  --backup    Create a timestamped backup of all manifest entries.
  --restore   Restore the most recent backup (or a named one via --backup-name).
  --list      List available backups.

The manifest lives at .env_manifest in the repository root.  Each non-comment,
non-blank line is a path relative to the repo root that MUST exist on the host
and MUST NOT be deleted by automated operations.

Design goals:
  - Zero external dependencies (stdlib only).
  - Usable from CI, from git hooks, and from interactive shells.
  - Backups are stored under .env_backups/<timestamp>/ and are themselves
    gitignored.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MANIFEST_NAME = ".env_manifest"
BACKUP_DIR_NAME = ".env_backups"
INSTALLATION_PATHS_ENV_NAME = "installation_paths.env"
DOT_ENV_NAME = ".env"
PRIVATE_DIR_MODE = 0o700
EXPECTED_COMPOSE_ENV_FILES = (
    "installation_paths.env",
    "env/omero_secrets.env",
    "env/omeroserver.env",
    "env/omeroweb.env",
    "env/omero-celery.env",
    "env/grafana.env",
)
ENV_TEMPLATE_PAIRS = (
    ("installation_paths_example.env", "installation_paths.env"),
    ("env/omeroweb_example.env", "env/omeroweb.env"),
    ("env/omeroserver_example.env", "env/omeroserver.env"),
    ("env/omero-celery_example.env", "env/omero-celery.env"),
    ("env/grafana_example.env", "env/grafana.env"),
    ("env/omero_secrets_example.env", "env/omero_secrets.env"),
)
DOT_ENV_REQUIRED_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "OMERO_INSTALLATION_PATH",
    "OMERO_DATABASE_PATH",
    "OMERO_PLUGIN_DATABASE_PATH",
    "OMERO_DATA_PATH",
    "OMERO_TMP_PATH",
    "OMERO_DATA_DIR",
    "OMERO_USER_DATA_PATH",
    "OMERO_IMPORT_PATH",
    "OMERO_SERVER_VAR_PATH",
    "OMERO_SERVER_LOGS_PATH",
    "OMERO_WEB_VAR_PATH",
    "OMERO_WEB_LOGS_PATH",
    "OMERO_WEB_SUPERVISOR_LOGS_PATH",
    "OMERO_WEB_HOST_PORT",
    "CONFIG_omero_web_application__server_port",
    "PORTAINER_DATA_PATH",
    "PROMETHEUS_DATA_PATH",
    "GRAFANA_DATA_PATH",
    "LOKI_DATA_PATH",
    "ALLOY_DATA_PATH",
    "PG_MAINTENANCE_DATA_PATH",
    "NODE_EXPORTER_TEXTFILE_PATH",
    "CROWDSEC_DB_PATH",
    "CROWDSEC_CONFIG_PATH",
    "OMERO_DROPBOX_VERSION",
    "OMERO_CLI_ZARR_VERSION",
    "OME_ZARR_PY_VERSION",
    "BIOFORMATS2RAW_VERSION",
    "REDIS_SAVE_POLICY",
    "REDIS_APPENDONLY",
    "REDIS_MAXMEMORY",
    "REDIS_MAXMEMORY_POLICY",
    "REDIS_DATA_TMPFS_SIZE",
    "OMERO_DB_PASS",
    "OMP_PLUGIN_DB_PASS",
)
DOT_ENV_REQUIRED_ALLOW_EMPTY_KEYS = frozenset({"REDIS_SAVE_POLICY"})

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(repo_root: Path) -> list[Path]:
    """Return manifest entry paths anchored under the supplied repository root."""
    manifest_path = repo_root / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"ERROR: Manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    entries: list[Path] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Keep the manifest entry lexically anchored under the caller-provided
        # repo root. Deployment worktrees intentionally use symlinked env files,
        # and resolving them here would escape the worktree and break repo-
        # relative bookkeeping for checks and backups.
        entries.append(repo_root / validate_relative_manifest_path(line))
    return entries


def validate_relative_manifest_path(raw_path: str) -> Path:
    """Validate and return a repo-relative manifest path."""
    path_text = raw_path.strip()
    raw_parts = path_text.split("/")
    relative_path = PurePosixPath(path_text)
    invalid = (
        not path_text
        or "\\" in path_text
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(ord(character) < 32 for character in path_text)
    )
    if invalid:
        raise SystemExit(
            f"Invalid {MANIFEST_NAME} entry: {raw_path!r}. "
            "Entries must be clean repo-relative paths."
        )
    return Path(relative_path)


def ensure_private_dir(path: Path) -> None:
    """Create a private directory or tighten an existing one."""
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RuntimeError(f"Refusing unsafe backup directory path: {path}")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(PRIVATE_DIR_MODE)


def validate_backup_name(backup_name: str) -> str:
    """Validate a backup directory name supplied by the operator."""
    candidate = PurePosixPath(backup_name.strip())
    invalid = (
        not str(candidate)
        or "\\" in backup_name
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.parts[0] in {".", ".."}
        or any(ord(character) < 32 for character in backup_name)
    )
    if invalid:
        raise ValueError("Backup name must be one listed directory name.")
    return candidate.parts[0]


def load_env_assignments(env_path: Path) -> dict[str, str]:
    """Return simple KEY=VALUE assignments from an env-style file."""
    if not env_path.exists():
        return {}

    assignments: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        assignments[key] = value.strip().strip("\"'")
    return assignments


def parse_env_keys(env_path: Path) -> list[str]:
    """Return env assignment keys in file order without exposing values."""
    keys: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if key:
            keys.append(key)
    return keys


def parse_compose_env_files(raw_value: str) -> list[str]:
    """Return normalized COMPOSE_ENV_FILES entries."""
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def derive_compose_project_name(installation_path: str | Path) -> str:
    """Return a deterministic compose project name for an installation path."""
    install_root = Path(str(installation_path).strip() or ".")
    stem = install_root.name.strip() or "omero"
    normalized = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-_")
    if not normalized:
        normalized = "omero"
    if not normalized[0].isalnum():
        normalized = f"omero-{normalized}"
    return normalized


def expected_compose_project_name(repo_root: Path) -> str:
    """Return the canonical compose project name for the declared installation."""
    installation_env = load_env_assignments(repo_root / INSTALLATION_PATHS_ENV_NAME)
    installation_path = installation_env.get("OMERO_INSTALLATION_PATH", "").strip()
    if not installation_path:
        raise ValueError(
            f"Missing OMERO_INSTALLATION_PATH in {INSTALLATION_PATHS_ENV_NAME}"
        )
    return derive_compose_project_name(installation_path)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_check(repo_root: Path) -> int:
    """Verify every manifest entry exists and is non-empty."""
    entries = load_manifest(repo_root)
    if not entries:
        print("WARNING: Manifest is empty — nothing to check.", file=sys.stderr)
        return 1

    missing: list[str] = []
    empty: list[str] = []

    for entry in entries:
        rel = entry.relative_to(repo_root)
        if not entry.exists():
            missing.append(str(rel))
        elif entry.stat().st_size == 0:
            empty.append(str(rel))

    if missing or empty:
        if missing:
            print(
                f"CRITICAL: {len(missing)} manifest file(s) MISSING:",
                file=sys.stderr,
            )
            for m in missing:
                print(f"  - {m}", file=sys.stderr)
        if empty:
            print(
                f"WARNING: {len(empty)} manifest file(s) are EMPTY:",
                file=sys.stderr,
            )
            for e in empty:
                print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: All {len(entries)} manifest entries present and non-empty.")
    return 0


def cmd_compose_guard(repo_root: Path) -> int:
    """Refuse compose operations from non-canonical worktrees."""
    if cmd_check(repo_root) != 0:
        return 1

    installation_env = load_env_assignments(repo_root / INSTALLATION_PATHS_ENV_NAME)
    installation_path = installation_env.get("OMERO_INSTALLATION_PATH", "").strip()
    if not installation_path:
        print(
            f"CRITICAL: {INSTALLATION_PATHS_ENV_NAME} does not define OMERO_INSTALLATION_PATH.",
            file=sys.stderr,
        )
        return 1

    declared_root = Path(installation_path).expanduser().resolve()
    current_root = repo_root.resolve()
    expected_project_name = expected_compose_project_name(repo_root)
    dot_env = load_env_assignments(repo_root / DOT_ENV_NAME)
    configured_project_name = dot_env.get("COMPOSE_PROJECT_NAME", "").strip()

    errors: list[str] = []
    if current_root != declared_root:
        errors.append(
            "Repository root does not match OMERO_INSTALLATION_PATH: "
            f"{current_root} != {declared_root}"
        )
    if dot_env and configured_project_name != expected_project_name:
        errors.append(
            ".env COMPOSE_PROJECT_NAME does not match the canonical project name: "
            f"{configured_project_name or '<missing>'} != {expected_project_name}"
        )

    if errors:
        print(
            "CRITICAL: Refusing docker compose from this checkout because it can "
            "target the live bind mounts with a second compose project.",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "Run compose only from the declared OMERO_INSTALLATION_PATH after "
            "regenerating the installation .env if needed.",
            file=sys.stderr,
        )
        return 1

    print(
        "OK: Compose guard passed for "
        f"{current_root} (project {expected_project_name})."
    )
    return 0


def cmd_dot_env_check(repo_root: Path) -> int:
    """Verify generated .env shape without printing deployment values."""
    dot_env_path = repo_root / DOT_ENV_NAME
    if not dot_env_path.exists():
        print(f"ERROR: Missing {DOT_ENV_NAME}.", file=sys.stderr)
        return 1

    dot_env = load_env_assignments(dot_env_path)
    failures: list[str] = []
    expected_project_name = expected_compose_project_name(repo_root)
    configured_project_name = dot_env.get("COMPOSE_PROJECT_NAME", "").strip()
    if configured_project_name != expected_project_name:
        failures.append(
            ".env COMPOSE_PROJECT_NAME does not match the canonical project name: "
            f"{configured_project_name or '<missing>'} != {expected_project_name}"
        )

    if "COMPOSE_ENV_FILES" in dot_env:
        configured_env_files = parse_compose_env_files(dot_env["COMPOSE_ENV_FILES"])
        if tuple(configured_env_files) != EXPECTED_COMPOSE_ENV_FILES:
            failures.append(
                ".env COMPOSE_ENV_FILES must be comma-separated if present: "
                f"{','.join(EXPECTED_COMPOSE_ENV_FILES)}"
            )

    missing_keys = [
        key
        for key in DOT_ENV_REQUIRED_KEYS
        if key not in dot_env
        or (key not in DOT_ENV_REQUIRED_ALLOW_EMPTY_KEYS and not dot_env[key])
    ]
    if missing_keys:
        failures.append(
            ".env is missing compose interpolation keys: " + ", ".join(missing_keys)
        )

    if failures:
        print(
            f"ERROR: {DOT_ENV_NAME} is not in the generated expected shape.",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print("No values were printed.", file=sys.stderr)
        return 1

    print(f"OK: {DOT_ENV_NAME} contains the expected compose interpolation keys.")
    return 0


def cmd_template_check(repo_root: Path) -> int:
    """Verify deployment env files keep the same assignment keys as templates."""
    failures = 0
    for example_rel, actual_rel in ENV_TEMPLATE_PAIRS:
        example_path = repo_root / example_rel
        actual_path = repo_root / actual_rel
        if not example_path.is_file():
            print(f"ERROR: Missing template: {example_rel}", file=sys.stderr)
            failures += 1
            continue
        if not actual_path.is_file():
            print(f"ERROR: Missing deployment env file: {actual_rel}", file=sys.stderr)
            failures += 1
            continue

        example_keys = parse_env_keys(example_path)
        actual_keys = parse_env_keys(actual_path)
        if actual_keys == example_keys:
            continue

        example_set = set(example_keys)
        actual_set = set(actual_keys)
        missing = [key for key in example_keys if key not in actual_set]
        extra = [key for key in actual_keys if key not in example_set]
        print(
            f"ERROR: {actual_rel} does not match {example_rel} assignment keys.",
            file=sys.stderr,
        )
        if missing:
            print(f"  Missing keys: {', '.join(missing)}", file=sys.stderr)
        if extra:
            print(f"  Extra keys: {', '.join(extra)}", file=sys.stderr)
        if not missing and not extra:
            print("  Key set matches, but order differs.", file=sys.stderr)
        failures += 1

    if failures:
        print(
            "No values were printed. Do not edit deployment env files unless the "
            "user explicitly grants a one-off exception.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: All {len(ENV_TEMPLATE_PAIRS)} deployment env files match templates.")
    return 0


def cmd_backup(repo_root: Path) -> int:
    """Create a timestamped backup of all manifest entries."""
    entries = load_manifest(repo_root)
    if not entries:
        print("WARNING: Manifest is empty — nothing to back up.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backups_root = repo_root / BACKUP_DIR_NAME
    backup_dir = backups_root / timestamp

    # Avoid collisions when called in rapid succession
    suffix = 0
    while backup_dir.exists():
        suffix += 1
        backup_dir = repo_root / BACKUP_DIR_NAME / f"{timestamp}_{suffix}"

    missing_count = 0
    backed_up = 0
    backup_started = False

    for entry in entries:
        rel = entry.relative_to(repo_root)
        if not entry.exists():
            print(f"  SKIP (missing): {rel}", file=sys.stderr)
            missing_count += 1
            continue

        if not backup_started:
            ensure_private_dir(backups_root)
            ensure_private_dir(backup_dir)
            backup_started = True
        dest = backup_dir / rel
        ensure_private_dir(dest.parent)
        shutil.copy2(entry, dest)
        backed_up += 1

    if backed_up == 0:
        print("ERROR: No files to back up (all missing).", file=sys.stderr)
        return 1

    print(f"Backup created: {backup_dir.relative_to(repo_root)}")
    print(f"  Files backed up: {backed_up}")
    if missing_count:
        print(f"  Files skipped (missing): {missing_count}")
    return 0


def cmd_restore(repo_root: Path, backup_name: str | None = None) -> int:
    """Restore from a backup."""
    backups_root = repo_root / BACKUP_DIR_NAME
    if not backups_root.exists():
        print("ERROR: No backups directory found.", file=sys.stderr)
        return 1

    available = sorted(
        [d for d in backups_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    if not available:
        print("ERROR: No backups found.", file=sys.stderr)
        return 1

    if backup_name:
        try:
            safe_backup_name = validate_backup_name(backup_name)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        target = backups_root / safe_backup_name
        if not target.is_dir():
            print(f"ERROR: Backup not found: {safe_backup_name}", file=sys.stderr)
            return 1
    else:
        target = available[0]

    restored = 0
    for backup_file in target.rglob("*"):
        if backup_file.is_symlink():
            print(f"ERROR: Refusing symlink in backup: {backup_file}", file=sys.stderr)
            return 1
        if not backup_file.is_file():
            continue
        rel = backup_file.relative_to(target)
        dest = repo_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, dest)
        restored += 1
        print(f"  Restored: {rel}")

    if restored == 0:
        print("WARNING: Backup was empty — nothing restored.", file=sys.stderr)
        return 1

    print(f"Restored {restored} file(s) from {target.name}")
    return 0


def cmd_list(repo_root: Path) -> int:
    """List available backups."""
    backups_root = repo_root / BACKUP_DIR_NAME
    if not backups_root.exists():
        print("No backups directory found.")
        return 0

    available = sorted(
        [d for d in backups_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    if not available:
        print("No backups found.")
        return 0

    for d in available:
        file_count = sum(1 for _ in d.rglob("*") if _.is_file())
        print(f"  {d.name}  ({file_count} files)")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guard against accidental deletion of untracked deployment config files."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Verify all manifest entries exist and are non-empty.")
    sub.add_parser(
        "compose-guard",
        help="Refuse compose operations from a non-canonical checkout or project name.",
    )
    sub.add_parser(
        "dot-env-check",
        help="Check generated .env shape without printing deployment values.",
    )
    sub.add_parser(
        "template-check",
        help="Compare deployment env assignment keys against tracked templates.",
    )
    sub.add_parser(
        "backup", help="Create a timestamped backup of all manifest entries."
    )

    restore_parser = sub.add_parser("restore", help="Restore from a backup.")
    restore_parser.add_argument(
        "--backup-name",
        default=None,
        help="Name of a specific backup to restore. Defaults to the most recent.",
    )

    sub.add_parser("list", help="List available backups.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root. Defaults to the current directory.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    if args.command == "check":
        return cmd_check(repo_root)
    if args.command == "compose-guard":
        return cmd_compose_guard(repo_root)
    if args.command == "dot-env-check":
        return cmd_dot_env_check(repo_root)
    if args.command == "template-check":
        return cmd_template_check(repo_root)
    if args.command == "backup":
        return cmd_backup(repo_root)
    if args.command == "restore":
        return cmd_restore(repo_root, args.backup_name)
    if args.command == "list":
        return cmd_list(repo_root)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
