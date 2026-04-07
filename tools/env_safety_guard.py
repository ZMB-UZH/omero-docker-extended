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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = ".env_manifest"
BACKUP_DIR_NAME = ".env_backups"

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(repo_root: Path) -> list[Path]:
    """Return resolved paths listed in the manifest."""
    manifest_path = repo_root / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"ERROR: Manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    entries: list[Path] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        resolved = (repo_root / line).resolve()
        entries.append(resolved)
    return entries


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


def cmd_backup(repo_root: Path) -> int:
    """Create a timestamped backup of all manifest entries."""
    entries = load_manifest(repo_root)
    if not entries:
        print("WARNING: Manifest is empty — nothing to back up.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backup_dir = repo_root / BACKUP_DIR_NAME / timestamp

    # Avoid collisions when called in rapid succession
    suffix = 0
    while backup_dir.exists():
        suffix += 1
        backup_dir = repo_root / BACKUP_DIR_NAME / f"{timestamp}_{suffix}"

    missing_count = 0
    backed_up = 0

    for entry in entries:
        rel = entry.relative_to(repo_root)
        if not entry.exists():
            print(f"  SKIP (missing): {rel}", file=sys.stderr)
            missing_count += 1
            continue

        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
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
        target = backups_root / backup_name
        if not target.is_dir():
            print(f"ERROR: Backup not found: {backup_name}", file=sys.stderr)
            return 1
    else:
        target = available[0]

    restored = 0
    for backup_file in target.rglob("*"):
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
