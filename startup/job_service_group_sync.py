#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import omero
from omero.gateway import BlitzGateway
from omero.model import ExperimenterI
from omero.rtypes import rbool, rstring


EXCLUDED_GROUP_NAMES = frozenset({"root", "system", "user"})


def _required_env(name: str) -> str:
    """Required env.

    Inputs: `name`. Output: `str`. Raises on invalid or unavailable state.
    """
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _parse_bool(value: str) -> bool:
    """Parse bool.

    Inputs: `value`. Output: `bool`. Raises on invalid or unavailable state.
    """
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _value(obj) -> object:
    """Return value.

    Inputs: `obj`. Output: `object`.
    """
    return getattr(obj, "val", obj)


def _group_name(group) -> str:
    """Group name.

    Inputs: `group`. Output: `str`.
    """
    return str(_value(group.name))


def _group_id(group) -> int:
    """Group ID.

    Inputs: `group`. Output: `int`.
    """
    return int(str(_value(group.id)))


def _eligible_groups(groups: Iterable) -> list:
    """Eligible groups.

    Inputs: `groups`. Output: `list`.
    """
    return [group for group in groups if _group_name(group) not in EXCLUDED_GROUP_NAMES]


def _new_job_experimenter(job_user: str):
    """New job experimenter.

    Inputs: `job_user`. Output: `experimenter`.
    """
    experimenter = ExperimenterI()
    experimenter.omeName = rstring(job_user)
    experimenter.firstName = rstring("Job")
    experimenter.lastName = rstring("Service")
    experimenter.ldap = rbool(False)
    return experimenter


def ensure_job_user(admin, job_user: str, job_pass: str, retries: int):
    """Ensure job user.

    Inputs: `admin`, `job_user`, `job_pass`, `retries`. Output:
    `admin.lookupExperimenter` result. Raises on invalid or unavailable state.
    """
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return admin.lookupExperimenter(job_user)
        except omero.ApiUsageException:
            pass

        try:
            default_group = admin.lookupGroup("user")
            admin.createExperimenterWithPassword(
                _new_job_experimenter(job_user),
                rstring(job_pass),
                default_group,
                [],
            )
            return admin.lookupExperimenter(job_user)
        except omero.ValidationException:
            return admin.lookupExperimenter(job_user)
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2 * attempt, 10))

    raise RuntimeError(f"failed to ensure OMERO user {job_user!r}") from last_error


def sync_memberships(args: argparse.Namespace) -> int:
    """Sync memberships.

    Inputs: `args`. Output: `int`. Raises on invalid or unavailable state.
    """
    root_pass = _required_env("ROOTPASS")
    job_pass = _required_env("OMERO_JOB_SERVICE_PASS")
    secure = _parse_bool(args.secure)

    conn = BlitzGateway(
        args.root_user,
        root_pass,
        host=args.host,
        port=args.port,
        secure=secure,
    )
    if not conn.connect():
        raise RuntimeError(
            f"failed to connect to OMERO at {args.host}:{args.port} as {args.root_user}"
        )

    try:
        admin = conn.getAdminService()
        job_exp = ensure_job_user(admin, args.job_user, job_pass, args.user_retries)
        current_group_ids = {
            int(str(group_id)) for group_id in admin.getMemberOfGroupIds(job_exp)
        }
        groups = _eligible_groups(admin.lookupGroups())
        missing_groups = [
            group for group in groups if _group_id(group) not in current_group_ids
        ]

        if missing_groups:
            admin.addGroups(
                ExperimenterI(int(str(_value(job_exp.id))), False), missing_groups
            )

        print(
            "job-service group sync complete: "
            f"eligible_groups={len(groups)} "
            f"added_groups={len(missing_groups)} "
            f"already_member={len(groups) - len(missing_groups)}"
        )
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Inputs: none. Output: `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description="Ensure the OMERO job-service user exists and belongs to all eligible groups.",
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--secure", default="true")
    parser.add_argument("--root-user", default="root")
    parser.add_argument("--job-user", required=True)
    parser.add_argument("--user-retries", default=3, type=int)
    return parser


def main(argv: list[str]) -> int:
    """Execute the command entrypoint.

    Inputs: `argv`. Output: `int`.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port <= 0:
        parser.error("--port must be a positive integer")
    if args.user_retries <= 0:
        parser.error("--user-retries must be a positive integer")
    try:
        return sync_memberships(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
