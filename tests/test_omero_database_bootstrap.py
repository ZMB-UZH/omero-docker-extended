"""Exercise database startup decisions without touching a deployment."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import secrets
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "startup/60-database.py"
SPEC = importlib.util.spec_from_file_location("omero_database_bootstrap", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    """Isolate startup from the caller's filesystem and environment.

    Inputs: temporary workspace and environment overrides.
    Output: fixture server path, temp directory, and synthetic environment.
    """
    monkeypatch.chdir(tmp_path)
    server = tmp_path / "server"
    server.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    values = {
        "OMERODIR": str(server),
        "OMERO_TMPDIR": str(temp),
        "CONFIG_omero_db_host": "db.fixture",
        "CONFIG_omero_db_port": "5438",
        "CONFIG_omero_db_user": "fixture-owner",
        "CONFIG_omero_db_name": "fixture-db",
        "CONFIG_omero_db_pass": secrets.token_urlsafe(),
        "ROOTPASS": secrets.token_urlsafe(),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(bootstrap, "executable", lambda name: f"/fixture/{name}")
    return server, temp, values


@pytest.mark.parametrize("state", [b"unrecognized", b"unknown"])
def test_never_initialize_an_unrecognized_database(runtime, monkeypatch, state):
    """Refuse unknown database state without running the schema generator.

    Inputs: unrecognized state response. Output: error before any schema write.
    """
    run = Mock(side_effect=[b"", state])
    write = Mock()
    monkeypatch.setattr(bootstrap, "run", run)
    monkeypatch.setattr(bootstrap, "write_schema", write)
    with pytest.raises(bootstrap.BootstrapError, match="no recognized OMERO schema"):
        bootstrap.prepare_database()
    assert run.call_count == 2
    write.assert_not_called()


@pytest.mark.parametrize("failed", [True, False])
def test_existing_schema_only_upgrades(runtime, monkeypatch, failed):
    """Keep recognized installations on the native upgrade path.

    Inputs: existing schema with a successful or failed native upgrade.
    Output: one upgrade attempt and no initial schema generation.
    """
    upgrade = bootstrap.BootstrapError("upgrade failed") if failed else b""
    run = Mock(side_effect=[b"", b"existing\n", upgrade])
    write = Mock()
    monkeypatch.delenv("ROOTPASS")
    monkeypatch.setattr(bootstrap, "run", run)
    monkeypatch.setattr(bootstrap, "write_schema", write)
    if failed:
        with pytest.raises(bootstrap.BootstrapError, match="upgrade failed"):
            bootstrap.prepare_database()
    else:
        bootstrap.prepare_database()
    args = run.call_args.args[0]
    assert args[1:3] == ["db", "upgrade"]
    assert run.call_args.kwargs["env"]["PGPORT"] == "5438"
    assert run.call_count == 3
    write.assert_not_called()


def test_cannot_treat_a_failed_schema_query_as_empty(runtime, monkeypatch):
    """Distinguish a failed state check from a genuinely empty database.

    Inputs: failed state query. Output: startup refusal without schema generation.
    """
    monkeypatch.setattr(
        bootstrap,
        "run",
        Mock(side_effect=[b"", bootstrap.BootstrapError("state check failed")]),
    )
    write = Mock()
    monkeypatch.setattr(bootstrap, "write_schema", write)
    with pytest.raises(bootstrap.BootstrapError, match="state check failed"):
        bootstrap.prepare_database()
    write.assert_not_called()


def test_readiness_retries_only_before_classification(runtime, monkeypatch):
    """Retry readiness before making a database-state decision.

    Inputs: PostgreSQL that becomes available on retry.
    Output: readiness retried, then one classified upgrade.
    """
    run = Mock(
        side_effect=[bootstrap.BootstrapError("not ready"), b"", b"existing", b""]
    )
    sleep = Mock()
    monkeypatch.setattr(bootstrap, "run", run)
    monkeypatch.setattr(bootstrap.time, "sleep", sleep)
    bootstrap.prepare_database()
    sleep.assert_called_once_with(1)
    assert run.call_args_list[0].args == run.call_args_list[1].args


def test_unreachable_postgres_fails_without_schema_work(runtime, monkeypatch):
    """Bound startup attempts when PostgreSQL never answers.

    Inputs: consistently failed readiness probes. Output: 50 probes, then refusal.
    """
    run = Mock(side_effect=bootstrap.BootstrapError("probe failed"))
    monkeypatch.setattr(bootstrap, "run", run)
    monkeypatch.setattr(bootstrap.time, "sleep", Mock())
    with pytest.raises(bootstrap.BootstrapError, match="did not become reachable"):
        bootstrap.prepare_database()
    assert run.call_count == 50
    assert {call.args[1] for call in run.call_args_list} == {
        "PostgreSQL readiness probe"
    }


@pytest.mark.parametrize("failed", [True, False])
def test_initialization_uses_private_sql_and_rechecks_state(
    runtime, monkeypatch, failed
):
    """Keep the initial schema private and recheck emptiness before applying it.

    Inputs: empty database and either outcome of SQL execution.
    Output: guarded stdin SQL and no named temporary credential material.
    """
    server, temp, expected = runtime
    steps = []

    def database_call(argv, operation, *, env, **options):
        """Inspect the PostgreSQL command and simulated input channel.

        Inputs: operation, command arguments, environment, and run options.
        Output: simulated query bytes or a requested initialization failure.
        """
        steps.append(operation)
        assert "ROOTPASS" not in env
        assert expected["ROOTPASS"] not in argv
        assert expected["CONFIG_omero_db_pass"] not in argv
        if operation == "OMERO database state check":
            return b"empty"
        if operation == "OMERO database initialization":
            assert bootstrap.INIT_GUARD in argv
            assert "pg_advisory_lock" in bootstrap.INIT_GUARD
            assert bootstrap.STATE_QUERY in bootstrap.INIT_GUARD
            assert argv[-1] == "--file=-"
            assert options["data"] == b"packaged schema"
            assert list(temp.iterdir()) == []
            if failed:
                raise bootstrap.BootstrapError("initialization failed")
        return b""

    def write_sql(selected_server, path, credential):
        """Verify the generator receives an anonymous private SQL destination.

        Inputs: selected server, open descriptor path, and fixture credential.
        Output: fixture SQL written through the descriptor.
        """
        assert selected_server == server and credential == expected["ROOTPASS"]
        assert path.parent == Path("/proc/self/fd")
        assert path.stat().st_mode & 0o777 == 0o600
        path.write_text("packaged schema")

    monkeypatch.setattr(bootstrap, "run", database_call)
    monkeypatch.setattr(bootstrap, "write_schema", write_sql)
    if failed:
        with pytest.raises(bootstrap.BootstrapError, match="initialization failed"):
            bootstrap.prepare_database()
    else:
        bootstrap.prepare_database()
    assert steps == [
        "PostgreSQL readiness probe",
        "OMERO database state check",
        "OMERO database initialization",
    ]
    assert list(temp.iterdir()) == []


def test_initialization_requires_an_explicit_root_password(runtime, monkeypatch):
    """Do not initialize an empty database with an implicit root password.

    Inputs: empty database and absent ROOTPASS. Output: startup refusal.
    """
    monkeypatch.delenv("ROOTPASS")
    monkeypatch.setattr(bootstrap, "run", Mock(side_effect=[b"", b"empty"]))
    with pytest.raises(bootstrap.BootstrapError, match="Set ROOTPASS"):
        bootstrap.prepare_database()


def test_real_java_input_encoding_uses_no_credential_argv(runtime, monkeypatch):
    """Keep quoted and escaped password bytes out of process arguments.

    Inputs: a password with whitespace, quotes, and escapes.
    Output: Java stdin argument-file bytes and a validated hash response.
    """
    server, _, _ = runtime
    credential = 'fixture with whitespace\t"quote" and backslash\\\nline'
    run = Mock(return_value=b"A" * 22 + b"==\n")
    monkeypatch.setattr(bootstrap, "run", run)
    assert bootstrap.bootstrap_password_hash(server, credential) == "A" * 22 + "=="
    argv = run.call_args.args[0]
    assert argv == ["/fixture/java", "@/dev/stdin"]
    assert (
        b'"fixture with whitespace\\t\\"quote\\" and backslash\\\\\\nline"\n'
        in run.call_args.kwargs["data"]
    )
    assert not any("PASS" in key for key in run.call_args.kwargs["env"])
    run.return_value = b"unexpected output"
    with pytest.raises(bootstrap.BootstrapError, match="invalid root password hash"):
        bootstrap.bootstrap_password_hash(server, credential)


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "new-prompt",
        "wrong-user",
        "unsalted",
        "provided-root",
        "empty",
        "cli-error",
    ],
)
def test_packaged_sql_generator_is_private(runtime, monkeypatch, capsys, mode):
    """Exercise the SQL generator adapter without relaying its output.

    Inputs: mocked packaged CLI and a selected generator outcome.
    Output: private SQL on success or a sanitized generation error.
    """
    server, temp, expected = runtime
    sql = temp / "fixture.sql"
    digest = Mock(return_value="synthetic-native-hash")
    monkeypatch.setattr(bootstrap, "bootstrap_password_hash", digest)

    class FixtureCLI:
        def __init__(self, program):
            """Check the bootstrap CLI's name.

            Inputs: CLI program name. Output: fixture initialized for registration.
            """
            assert program == "omero-db-bootstrap"

        def register(self, command, control, _help):
            """Install the supplied schema generator adapter in the fixture.

            Inputs: command, adapter class, and help text.
            Output: adapter instance stored for invocation.
            """
            assert command == "db"
            self.control = control()

        def invoke(self, args):
            """Exercise native hash lookup and the selected SQL generation path.

            Inputs: schema command arguments. Output: fixture SQL or a CLI failure.
            """
            assert args == ["db", "script", "-f", str(sql)]
            print(expected["ROOTPASS"])
            if mode == "cli-error":
                raise SystemExit(5)
            hashed = self.control._get_password_hash(
                SimpleNamespace(
                    user_id="1" if mode == "wrong-user" else "0",
                    no_salt=mode == "unsalted",
                ),
                root_pass=expected["ROOTPASS"] if mode == "provided-root" else None,
                old_prompt=mode != "new-prompt",
            )
            assert hashed == digest.return_value
            if mode in {"success", "new-prompt"}:
                sql.write_text("native schema")

    for name in ("omero", "omero.cli", "omero.plugins", "omero.plugins.db"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["omero.cli"].CLI = FixtureCLI
    sys.modules["omero.plugins.db"].DatabaseControl = object
    if mode in {"success", "new-prompt"}:
        bootstrap.write_schema(server, sql, expected["ROOTPASS"])
        assert sql.stat().st_mode & 0o777 == 0o600
    else:
        with pytest.raises(bootstrap.BootstrapError, match="schema generation failed"):
            bootstrap.write_schema(server, sql, expected["ROOTPASS"])
    assert capsys.readouterr().out == ""


def test_invalid_environment_exits_before_subprocess(runtime, monkeypatch, capsys):
    """Reject missing or malformed server configuration at startup.

    Inputs: absent and non-absolute server paths. Output: safe nonzero exits.
    """
    monkeypatch.setenv("OMERODIR", "relative")
    assert bootstrap.main() == 1
    assert "OMERODIR must name" in capsys.readouterr().err
    monkeypatch.delenv("OMERODIR")
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert stopped.value.code == 1
    assert "Set OMERODIR" in capsys.readouterr().err


@pytest.mark.parametrize("capture", [True, False])
def test_command_success_and_errors_do_not_emit_child_output(monkeypatch, capture):
    """Keep child diagnostics private for success and failure.

    Inputs: selected capture mode and mocked subprocess results.
    Output: requested bytes or a sanitized command error.
    """
    process = Mock(
        return_value=subprocess.CompletedProcess([], 0, b"result", b"private detail")
    )
    monkeypatch.setattr(bootstrap.subprocess, "run", process)
    args = ["/fixture/psql"]
    assert bootstrap.run(args, "fixture command", env={}, capture=capture) == (
        b"result" if capture else b""
    )
    assert process.call_args.kwargs["stderr"] == subprocess.DEVNULL
    process.return_value.returncode = 7
    with pytest.raises(
        bootstrap.BootstrapError, match=r"fixture command failed \(exit status 7\)"
    ):
        bootstrap.run(args, "fixture command", env={})
    process.side_effect = OSError("private daemon details")
    with pytest.raises(
        bootstrap.BootstrapError, match="fixture command could not complete"
    ):
        bootstrap.run(args, "fixture command", env={})


def test_unknown_failure_is_not_logged(monkeypatch, capsys):
    """Do not expose unexpected exceptions from bootstrap.

    Inputs: exception containing arbitrary detail. Output: generic error and exit 1.
    """
    monkeypatch.setattr(
        bootstrap, "prepare_database", Mock(side_effect=ValueError("private detail"))
    )
    assert bootstrap.main() == 1
    assert (
        capsys.readouterr().err == "ERROR: OMERO database startup could not complete.\n"
    )


def test_success_is_reported_only_after_bootstrap(monkeypatch, capsys):
    """Emit readiness only after database preparation returns successfully.

    Inputs: successful preparation callback. Output: readiness and exit 0.
    """
    prepare = Mock()
    monkeypatch.setattr(bootstrap, "prepare_database", prepare)
    assert bootstrap.main() == 0
    prepare.assert_called_once_with()
    assert capsys.readouterr().out == "OMERO database is ready.\n"


def test_runtime_tool_resolves_only_on_absolute_path(monkeypatch):
    """Ignore relative search directories during tool resolution.

    Inputs: mixed PATH entries and tool availability. Output: path or safe error.
    """
    monkeypatch.setenv("PATH", ":./unknown:/opt/runtime/bin:/usr/bin")
    which = Mock(return_value="/opt/runtime/bin/psql")
    monkeypatch.setattr(bootstrap.shutil, "which", which)
    assert bootstrap.executable("psql") == "/opt/runtime/bin/psql"
    which.assert_called_once_with("psql", path="/opt/runtime/bin:/usr/bin")
    which.return_value = None
    with pytest.raises(bootstrap.BootstrapError, match="psql"):
        bootstrap.executable("psql")
