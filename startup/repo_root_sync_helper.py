#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable


TOKEN_PATTERN = re.compile(r"%[A-Za-z0-9_]+%")
KNOWN_TEMPLATE_TOKENS = {
    "%group%",
    "%user%",
    "%year%",
    "%month%",
    "%day%",
    "%time%",
}
VOLATILE_TEMPLATE_TOKENS = {
    "%year%",
    "%month%",
    "%day%",
    "%time%",
}


def _validate_path_component(value: str, label: str) -> str:
    component = str(value or "").strip()
    if (
        not component
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
        or "\x00" in component
    ):
        raise ValueError(f"Invalid {label}: {value!r}")
    return component


def _template_parts(repo_template: str) -> list[str]:
    template = str(repo_template or "").strip()
    if not template:
        raise ValueError("omero.fs.repo.path must not be empty.")
    return [part for part in template.split("/") if part]


def stable_shared_prefix_parts(repo_template: str) -> list[str]:
    stable_parts: list[str] = []

    for raw_part in _template_parts(repo_template):
        tokens = set(TOKEN_PATTERN.findall(raw_part))
        unknown_tokens = tokens - KNOWN_TEMPLATE_TOKENS
        if unknown_tokens:
            raise ValueError(
                "omero.fs.repo.path contains unsupported tokens: "
                + ", ".join(sorted(unknown_tokens))
            )

        if "%user%" in raw_part or tokens.intersection(VOLATILE_TEMPLATE_TOKENS):
            break

        preview = raw_part.replace("%group%", "GROUP")
        if "%" in preview:
            raise ValueError(
                "omero.fs.repo.path contains unresolved token syntax in the stable "
                f"shared-prefix region: {raw_part}"
            )

        stable_parts.append(raw_part)

    return stable_parts


def _stable_prefix_matcher(raw_part: str) -> re.Pattern[str]:
    pieces: list[str] = ["^"]
    cursor = 0
    token_count = 0

    for match in TOKEN_PATTERN.finditer(raw_part):
        pieces.append(re.escape(raw_part[cursor : match.start()]))
        token = match.group(0)
        if token != "%group%":
            raise ValueError(
                "Only %group% is allowed in stable shared-prefix template segments, "
                f"got: {raw_part}"
            )
        pieces.append(r"[^/\\\x00]+")
        cursor = match.end()
        token_count += 1

    pieces.append(re.escape(raw_part[cursor:]))
    pieces.append("$")
    matcher = re.compile("".join(pieces))
    if token_count == 0:
        return matcher
    return matcher


def _parse_install_groups(install_groups: str) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()

    for raw_entry in str(install_groups or "").split(","):
        entry = raw_entry.strip()
        if not entry or entry.startswith("#"):
            continue
        group_name = entry.split(":", 1)[0].strip()
        if not group_name:
            continue
        group_name = _validate_path_component(group_name, "install group")
        if group_name in seen:
            continue
        seen.add(group_name)
        groups.append(group_name)

    return groups


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _configured_groups(
    install_groups: str,
    ldap_enabled: str,
    ldap_group: str,
) -> list[str]:
    groups = _parse_install_groups(install_groups)
    seen = set(groups)
    normalized_ldap_group = str(ldap_group or "").strip()

    if (
        _truthy(ldap_enabled)
        and normalized_ldap_group
        and normalized_ldap_group != "default"
        and not normalized_ldap_group.startswith(":")
    ):
        normalized_ldap_group = _validate_path_component(
            normalized_ldap_group, "ldap group"
        )
        if normalized_ldap_group not in seen:
            groups.append(normalized_ldap_group)

    return groups


def _emit_cumulative_paths(parts: Iterable[str]) -> list[str]:
    current: list[str] = []
    paths: list[str] = []
    for part in parts:
        current.append(part)
        paths.append("/".join(current))
    return paths


def configured_seed_paths(
    repo_template: str,
    install_groups: str,
    ldap_enabled: str,
    ldap_group: str,
) -> list[str]:
    stable_parts = stable_shared_prefix_parts(repo_template)
    if not stable_parts:
        return []

    requires_group = any("%group%" in part for part in stable_parts)
    configured_groups = _configured_groups(install_groups, ldap_enabled, ldap_group)
    if requires_group and not configured_groups:
        return []

    emitted: list[str] = []
    seen: set[str] = set()
    group_values = configured_groups if requires_group else [None]

    for group_name in group_values:
        rendered_parts: list[str] = []
        for raw_part in stable_parts:
            rendered = raw_part.replace("%group%", group_name or "")
            if "%" in rendered:
                raise ValueError(
                    "omero.fs.repo.path left unresolved token syntax in the stable "
                    f"shared-prefix region: {raw_part}"
                )
            rendered_parts.append(
                _validate_path_component(
                    rendered,
                    "managed-repository stable shared-prefix segment",
                )
            )
        for path in _emit_cumulative_paths(rendered_parts):
            if path in seen:
                continue
            seen.add(path)
            emitted.append(path)

    return emitted


def planned_paths(
    managed_root: str,
    repo_template: str,
    install_groups: str,
    ldap_enabled: str,
    ldap_group: str,
) -> list[str]:
    del managed_root
    # Only deterministic configured seeds are authoritative here. The raw
    # filesystem root can contain internal OMERO directories, stale test data,
    # or historical group trees that should not block installation-time
    # normalization of the current deployment contract.
    return configured_seed_paths(
        repo_template,
        install_groups,
        ldap_enabled,
        ldap_group,
    )


def lookup_prefix(root_pass: str, repo_dir_path: str, expected_managed_dir: str) -> int:
    try:
        from omero.gateway import BlitzGateway
    except Exception as exc:  # pragma: no cover - exercised in runtime only
        print(
            f"ERROR: failed to import OMERO Python bindings for repository lookup: {exc}",
            file=sys.stderr,
        )
        return 1

    repo_dir_path = str(repo_dir_path or "").strip("/")
    expected_managed_dir = str(expected_managed_dir or "").rstrip("/")

    if not repo_dir_path:
        print("ERROR: empty repository path", file=sys.stderr)
        return 2
    if not expected_managed_dir.startswith("/"):
        print("ERROR: expected managed dir must be absolute", file=sys.stderr)
        return 2

    path_parts = repo_dir_path.split("/")
    dir_name = path_parts[-1]
    parent_path = "/"
    if len(path_parts) > 1:
        parent_path = "/" + "/".join(path_parts[:-1]) + "/"

    def unwrap_text(value):
        if value is None:
            return ""
        inner = getattr(value, "val", value)
        return "" if inner is None else str(inner)

    def model_attr(model_obj, attr_name):
        value = getattr(model_obj, attr_name, None)
        if value is None:
            value = getattr(model_obj, f"_{attr_name}", None)
        return value

    def repo_description_path(model_obj):
        desc_path = unwrap_text(model_attr(model_obj, "path"))
        desc_name = unwrap_text(model_attr(model_obj, "name"))
        if not desc_name:
            return ""
        return (desc_path.rstrip("/") + "/" + desc_name).rstrip("/")

    def repo_description_uuid(model_obj):
        return unwrap_text(model_attr(model_obj, "hash"))

    conn = BlitzGateway("root", root_pass, host="localhost", port=4064)
    try:
        if not conn.connect():
            print("ERROR: failed to connect as root", file=sys.stderr)
            return 1
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        target_repo_uuid = ""
        repo_map = conn.c.sf.sharedResources().repositories()
        for description in getattr(repo_map, "descriptions", []):
            if repo_description_path(description) != expected_managed_dir:
                continue
            target_repo_uuid = repo_description_uuid(description)
            if target_repo_uuid:
                break

        if not target_repo_uuid:
            print(
                f"ERROR: failed to resolve active repository uuid for {expected_managed_dir}",
                file=sys.stderr,
            )
            return 1

        candidates = list(
            conn.getObjects("OriginalFile", attributes={"name": dir_name})
        )
        for obj in candidates:
            if obj.getPath() == parent_path and obj.getRepo() == target_repo_uuid:
                print(f"FOUND|{obj.getId()}|{obj.getOwnerOmeName()}|{obj.getRepo()}")
                return 0

        print("MISSING")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan and inspect managed-repository shared-prefix sync state."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stable_depth_parser = subparsers.add_parser(
        "stable-depth",
        help="Print the deterministic shared-prefix depth before user/volatile tokens.",
    )
    stable_depth_parser.add_argument("--repo-template", required=True)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Print the deterministic shared-prefix normalization plan.",
    )
    plan_parser.add_argument("--managed-root", required=True)
    plan_parser.add_argument("--repo-template", required=True)
    plan_parser.add_argument("--install-groups", default="")
    plan_parser.add_argument("--ldap-config", default="false")
    plan_parser.add_argument("--ldap-group", default="")

    lookup_parser = subparsers.add_parser(
        "lookup",
        help="Look up a repository prefix directory in the active repository.",
    )
    lookup_parser.add_argument("--root-pass", required=True)
    lookup_parser.add_argument("--repo-dir-path", required=True)
    lookup_parser.add_argument("--expected-managed-dir", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "stable-depth":
            print(len(stable_shared_prefix_parts(args.repo_template)))
            return 0

        if args.command == "plan":
            for path in planned_paths(
                args.managed_root,
                args.repo_template,
                args.install_groups,
                args.ldap_config,
                args.ldap_group,
            ):
                print(path)
            return 0

        if args.command == "lookup":
            return lookup_prefix(
                args.root_pass,
                args.repo_dir_path,
                args.expected_managed_dir,
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
