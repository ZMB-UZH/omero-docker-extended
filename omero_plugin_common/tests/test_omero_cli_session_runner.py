from __future__ import annotations

import io
import runpy
import sys
import types

from omero_plugin_common import omero_cli_session_runner


def test_runner_reads_session_key_from_stdin_and_invokes_cli(monkeypatch) -> None:
    """Verify the runner keeps the session key out of process argv.

    Inputs: pytest provides `monkeypatch`. Output: fails on runner plumbing
    regressions.
    """
    captured = {}

    class _FakeCLI:
        """Minimal OMERO CLI fake."""

        rv = 0

        def invoke(self, args):
            """Capture invoked OMERO CLI args.

            Inputs: CLI argument list. Output: None.
            """
            captured["args"] = list(args)

    omero_module = types.ModuleType("omero")
    cli_module = types.ModuleType("omero.cli")
    cli_module.CLI = _FakeCLI
    monkeypatch.setitem(sys.modules, "omero", omero_module)
    monkeypatch.setitem(sys.modules, "omero.cli", cli_module)
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin-session\n"))

    rc = omero_cli_session_runner.main(
        ["--host", "omeroserver", "--port", "4064", "--", "import", "file.tif"]
    )

    assert rc == 0
    assert captured["args"] == [
        "-k",
        "stdin-session",
        "-s",
        "omeroserver",
        "-p",
        "4064",
        "import",
        "file.tif",
    ]


def test_runner_rejects_missing_stdin_session_key(monkeypatch, capsys) -> None:
    """Verify the runner fails closed when stdin has no session key.

    Inputs: pytest fixtures. Output: asserts nonzero return and stderr.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    rc = omero_cli_session_runner.main(
        ["--host", "omeroserver", "--port", "4064", "--", "import", "file.tif"]
    )

    assert rc == 2
    assert "session key" in capsys.readouterr().err


def test_runner_rejects_missing_command(monkeypatch, capsys) -> None:
    """Verify the wrapper fails before reading stdin when no command is supplied.

    Inputs: pytest fixtures. Output: asserts argparse failure.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO("session-key\n"))

    try:
        omero_cli_session_runner.main(["--host", "omeroserver", "--port", "4064"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("argparse should reject missing OMERO CLI command")
    assert "missing OMERO CLI command" in capsys.readouterr().err


def test_runner_normalizes_cli_exit_paths(monkeypatch) -> None:
    """Verify SystemExit and non-integer CLI return values are normalized.

    Inputs: pytest monkeypatch fixture. Output: asserts normalized return codes.
    """

    class _SystemExitCLI:
        """OMERO CLI fake that raises SystemExit from invoke."""

        rv = 0

        @staticmethod
        def invoke(_args):
            """Raise a non-integer SystemExit value.

            Inputs: ignored CLI args. Output: raises SystemExit.
            """
            raise SystemExit("bad")

    class _BadReturnCLI:
        """OMERO CLI fake that reports an invalid return value."""

        rv = "bad"

        @staticmethod
        def invoke(_args):
            """Return without setting an integer return value.

            Inputs: ignored CLI args. Output: None.
            """
            return None

    cli_module = types.ModuleType("omero.cli")
    omero_module = types.ModuleType("omero")
    monkeypatch.setitem(sys.modules, "omero", omero_module)
    monkeypatch.setitem(sys.modules, "omero.cli", cli_module)

    cli_module.CLI = _SystemExitCLI
    monkeypatch.setattr(sys, "stdin", io.StringIO("session-key\n"))
    assert (
        omero_cli_session_runner.main(["--host", "h", "--port", "1", "--", "import"])
        == 1
    )

    cli_module.CLI = _BadReturnCLI
    monkeypatch.setattr(sys, "stdin", io.StringIO("session-key\n"))
    assert (
        omero_cli_session_runner.main(["--host", "h", "--port", "1", "--", "import"])
        == 1
    )


def test_runner_module_entrypoint_invokes_main(monkeypatch) -> None:
    """Verify the module entry point exits with the CLI return code.

    Inputs: pytest monkeypatch fixture. Output: asserts SystemExit code and CLI args.
    """
    captured = {}

    class _FakeCLI:
        """OMERO CLI fake for runpy execution."""

        rv = 0

        def invoke(self, args):
            """Capture CLI invocation arguments.

            Inputs: CLI argument list. Output: None.
            """
            captured["args"] = list(args)

    omero_module = types.ModuleType("omero")
    cli_module = types.ModuleType("omero.cli")
    cli_module.CLI = _FakeCLI
    monkeypatch.setitem(sys.modules, "omero", omero_module)
    monkeypatch.setitem(sys.modules, "omero.cli", cli_module)
    monkeypatch.setattr(sys, "stdin", io.StringIO("entry-session\n"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "omero_cli_session_runner",
            "--host",
            "h",
            "--port",
            "1",
            "--",
            "import",
        ],
    )
    monkeypatch.delitem(
        sys.modules,
        "omero_plugin_common.omero_cli_session_runner",
        raising=False,
    )

    try:
        runpy.run_module(
            "omero_plugin_common.omero_cli_session_runner", run_name="__main__"
        )
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("module entry point must raise SystemExit")
    assert captured["args"] == ["-k", "entry-session", "-s", "h", "-p", "1", "import"]
