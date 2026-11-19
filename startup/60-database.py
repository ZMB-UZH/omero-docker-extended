#!/usr/bin/env python3
"""Prepare the OMERO database without logging credentials or guessing its state."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


STATE_QUERY = """SELECT CASE
  WHEN pg_catalog.to_regclass('dbpatch') IS NOT NULL THEN 'existing'
  WHEN EXISTS (
    SELECT 1 FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE left(n.nspname, 3) <> 'pg_' AND n.nspname <> 'information_schema'
  ) THEN 'unrecognized'
  ELSE 'empty'
END"""

# Hold the lock through the packaged SQL and recheck under the same connection.
INIT_GUARD = f"""
SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended('omero-schema-init', 0));
DO $omero$
BEGIN
  IF ({STATE_QUERY}) <> 'empty' THEN
    RAISE EXCEPTION 'Database is not empty; no schema was initialized';
  END IF;
END
$omero$;
"""


class BootstrapError(RuntimeError):
    """A bounded diagnostic that contains no credentials or child output."""


def executable(name: str) -> str:
    """Resolve runtime tools through absolute search directories only.

    Inputs: tool name. Output: absolute executable path, or a safe startup error.
    """
    path = os.pathsep.join(part for part in os.get_exec_path() if os.path.isabs(part))
    found = shutil.which(name, path=path)
    if found is None:
        raise BootstrapError(f"Required database startup tool is missing: {name}.")
    return found


def run(
    argv: list[str],
    operation: str,
    *,
    env: dict[str, str],
    data: bytes | None = None,
    capture: bool = False,
    timeout: float | None = None,
) -> bytes:
    """Run a native command without displaying subprocess diagnostics.

    Inputs: command, operation label, environment, and I/O options.
    Output: captured bytes when requested; otherwise empty bytes.
    """
    try:
        result = subprocess.run(
            argv,
            env=env,
            input=data,
            stdin=subprocess.DEVNULL if data is None else None,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise BootstrapError(f"{operation} could not complete.") from None
    if result.returncode:
        raise BootstrapError(f"{operation} failed (exit status {result.returncode}).")
    return result.stdout if capture else b""


def java_argfile(arguments: list[str]) -> bytes:
    """Quote literal arguments using the Java launcher's argument-file syntax.

    Inputs: ordered argument strings. Output: UTF-8 argument-file bytes.
    """
    escapes = str.maketrans(
        {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\f": "\\f"}
    )
    return (
        "\n".join(f'"{arg.translate(escapes)}"' for arg in arguments) + "\n"
    ).encode()


def bootstrap_password_hash(server: Path, password: str) -> str:
    """Generate the native OMERO root hash with the credential on stdin only.

    Inputs: installed server path and root password. Output: validated native hash.
    """
    payload = java_argfile(
        [
            "-cp",
            str(server / "lib/server/*"),
            "ome.security.auth.PasswordUtil",
            password,
            "0",
        ]
    )
    digest = run(
        [executable("java"), "@/dev/stdin"],
        "OMERO root password hashing",
        env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        data=payload,
        capture=True,
        timeout=30,
    ).strip()
    if not re.fullmatch(rb"[A-Za-z0-9+/]{16,254}={0,2}", digest):
        raise BootstrapError("OMERO returned an invalid root password hash.")
    return digest.decode("ascii")


def write_schema(server: Path, sql_file: Path, password: str) -> None:
    """Supply a private native password hash to the packaged OMERO SQL generator.

    Inputs: server path, private SQL destination, and root password.
    Output: initial schema written to the destination with mode 0600.
    """
    from omero.cli import CLI
    from omero.plugins.db import DatabaseControl

    digest = bootstrap_password_hash(server, password)

    class InitialSchema(DatabaseControl):
        # Keep the packaged SQL templates, patch selection, and config handling.
        def _get_password_hash(self, args, root_pass=None, old_prompt=False):
            """Allow the generator to request only the initial salted root hash.

            Inputs: schema command arguments and optional credential modes.
            Output: the precomputed root hash for a supported request.
            """
            # The flag changes the native prompt text; this adapter never prompts.
            del old_prompt
            if args.user_id != "0" or args.no_salt or root_pass is not None:
                raise BootstrapError("Unexpected OMERO SQL generator password mode.")
            return digest

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                cli = CLI("omero-db-bootstrap")
                cli.register("db", InitialSchema, "Generate initial OMERO schema")
                cli.invoke(["db", "script", "-f", str(sql_file)])
        if not sql_file.is_file() or sql_file.stat().st_size == 0:
            raise BootstrapError("OMERO did not produce the initial schema.")
    except (Exception, SystemExit):
        raise BootstrapError("OMERO initial schema generation failed.") from None
    sql_file.chmod(0o600)


def prepare_database() -> None:
    """Wait for PostgreSQL; upgrade known schemas or initialize only an empty DB.

    Inputs: the server and PostgreSQL startup environment.
    Output: database prepared for OMERO or a fail-closed startup error.
    """
    server_root = os.environ.get("OMERODIR")
    db_password = os.environ.get("CONFIG_omero_db_pass") or os.environ.get(
        "OMERO_DB_PASS"
    )
    if not server_root or not db_password:
        raise BootstrapError(
            "Set OMERODIR and the OMERO database password before startup."
        )
    server = Path(server_root)
    if not server.is_absolute() or not server.is_dir():
        raise BootstrapError("OMERODIR must name the installed server directory.")
    os.chdir(server.parent)
    env = os.environ.copy()
    env.pop("ROOTPASS", None)
    env.update(
        PGHOST=env.get("CONFIG_omero_db_host") or "db",
        PGPORT=env.get("CONFIG_omero_db_port") or "5432",
        PGUSER=env.get("CONFIG_omero_db_user") or "omero",
        PGDATABASE=env.get("CONFIG_omero_db_name") or "omero",
        PGPASSWORD=db_password,
        PGCONNECT_TIMEOUT="5",
    )
    psql = [
        executable("psql"),
        "--no-psqlrc",
        "--no-password",
        "--quiet",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
    ]
    for attempt in range(50):
        try:
            run(
                [*psql, "--command=SELECT 1"],
                "PostgreSQL readiness probe",
                env=env,
                timeout=6,
            )
        except BootstrapError:
            if attempt == 49:
                raise BootstrapError(
                    "PostgreSQL did not become reachable for OMERO."
                ) from None
            time.sleep(1)
        else:
            break

    state = run(
        [*psql, "--command", STATE_QUERY],
        "OMERO database state check",
        env=env,
        capture=True,
        timeout=15,
    ).strip()
    if state == b"existing":
        run(
            [
                str(Path(sys.executable).with_name("omego")),
                "db",
                "upgrade",
                "--serverdir",
                str(server),
            ],
            "OMERO database upgrade",
            env=env,
        )
        return
    if state != b"empty":
        raise BootstrapError(
            "The database is not empty and has no recognized OMERO schema."
        )
    password = os.environ.get("ROOTPASS")
    if not password:
        raise BootstrapError(
            "Set ROOTPASS before initializing an empty OMERO database."
        )
    with tempfile.TemporaryFile(
        prefix="omero-schema-", dir=env.get("OMERO_TMPDIR")
    ) as sql:
        write_schema(server, Path(f"/proc/self/fd/{sql.fileno()}"), password)
        sql.seek(0)
        run(
            [*psql, "--command", INIT_GUARD, "--file=-"],
            "OMERO database initialization",
            env=env,
            data=sql.read(),
        )


def main() -> int:
    """Report bootstrap success or a safe failure without a raw traceback.

    Inputs: startup environment. Output: 0 after bootstrap, 1 on failure.
    """
    try:
        prepare_database()
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("ERROR: OMERO database startup could not complete.", file=sys.stderr)
        return 1
    print("OMERO database is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
