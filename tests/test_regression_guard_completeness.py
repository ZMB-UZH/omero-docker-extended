"""A prevention scan must never report success after silently losing source coverage."""

from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import regression_guard as guard


def test_large_python_source_is_scanned_to_the_end(tmp_path):
    """Inputs: a realistic large module with a final finding. Output: exact finding, not a size-based skip."""
    source = tmp_path / "large.py"
    source.write_text("# harmless padding\n" * 30_000 + "assert value\n")
    assert source.stat().st_size > 500_000
    findings = guard.scan_paths(tmp_path, [source])
    assert [(item.rule_id, item.line) for item in findings] == [("RG001", 30_001)]


@pytest.mark.parametrize(
    "kind", ["syntax", "encoding", "read_failure", "resource_limit"]
)
def test_incomplete_scan_is_a_failed_operation(tmp_path, monkeypatch, capsys, kind):
    """Inputs: an unscannable applicable source. Output: nonzero status and no clean-scan claim."""
    source = tmp_path / "source.py"
    source.write_text("answer = 42\n")
    expected = {
        "syntax": "parse",
        "encoding": "UTF-8",
        "read_failure": "read",
        "resource_limit": "limit",
    }[kind]
    if kind == "syntax":
        source.write_text("def invalid(:\n")
    elif kind == "encoding":
        source.write_bytes(b"value = '\xff'\n")
    elif kind == "resource_limit":
        monkeypatch.setattr(guard, "MAX_SOURCE_BYTES", 8, raising=False)
    else:
        original_open = Path.open

        def fail_selected(path, *args, **kwargs):
            """Inputs: source open. Output: a permission failure after inventory discovery."""
            if path == source:
                raise PermissionError("fixture inaccessible source")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_selected)
    assert guard.main(["--repo-root", str(tmp_path), "scan", "--format", "json"]) == 1
    captured = capsys.readouterr()
    assert expected in captured.err
    assert "source.py" in captured.err
    assert not captured.out


def test_cli_parse_failure_is_not_empty_sarif_equivalent(tmp_path):
    """Inputs: native CLI with malformed Python. Output: failed operation with a useful diagnostic."""
    (tmp_path / "broken.py").write_text("def broken(:\n")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(guard.__file__)),
            "--repo-root",
            str(tmp_path),
            "scan",
            "--format",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "parse" in result.stderr and "broken.py" in result.stderr
    assert result.stdout == ""


def test_scan_directory_cannot_follow_symlink_outside_root(tmp_path):
    """Inputs: a source-like link outside the declared root. Output: only owned source is inspected."""
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("assert outside\n")
    (root / "link.py").symlink_to(outside)
    (root / "included.py").write_text("assert included\n")
    assert [(item.rule_id, item.path) for item in guard.scan_paths(root, [root])] == [
        ("RG001", "included.py")
    ]
    assert outside.read_text() == "assert outside\n"


@pytest.mark.parametrize(
    "failure", ["missing_fixture", "missed_finding", "false_positive"]
)
def test_selfcheck_rejects_broken_rule_catalog(tmp_path, monkeypatch, capsys, failure):
    """Inputs: a deliberately broken check. Output: self-validation fails on missing coverage or wrong results."""
    original_scan = guard.scan_paths
    if failure == "missing_fixture":
        monkeypatch.setattr(guard, "_selfcheck_fixtures", lambda: {})
        expected = "missing fixtures"
    elif failure == "missed_finding":
        monkeypatch.setattr(guard, "scan_paths", lambda *_args, **_kwargs: [])
        expected = "did not fire"
    else:

        def false_positive(root, paths, rules=guard.CATALOG):
            """Inputs: real selfcheck fixture. Output: one controlled false positive on the clean fixture."""
            if Path(paths[0]).name == "good.py":
                return [
                    guard.Finding(
                        "fixture", "high", "good.py", 1, 0, "false positive", "value"
                    )
                ]
            return original_scan(root, paths, rules)

        monkeypatch.setattr(guard, "scan_paths", false_positive)
        expected = "clean fixture produced findings"
    assert guard.selfcheck() == 1
    assert expected in capsys.readouterr().err


def test_optional_rule_engines_do_not_invent_findings(tmp_path):
    """Inputs: empty optional rule implementations. Output: no unrelated or synthetic results."""
    rule = replace(guard.CATALOG[0], pattern="", ast_check=None, custom_check=None)
    assert guard._python_ast_findings(rule, "source.py", "answer = 42") == []
    assert guard._regex_findings(rule, "source.py", "answer = 42") == []
    assert (
        guard._custom_findings(rule, "source.py", tmp_path / "source.py", "answer = 42")
        == []
    )
    assert json.loads(guard.render_json())


@pytest.mark.parametrize(
    ("handler", "body", "expected"),
    [
        ("", "pass", True),
        ("Exception", "pass", True),
        ("builtins.BaseException", "continue", True),
        ("(OSError, Exception)", "pass", True),
        ("OSError", "pass", False),
        ("(OSError, ValueError)", "continue", False),
        ("Exception", "raise", False),
        ("Exception", "logger.exception('operation failed')", False),
    ],
)
def test_broad_exception_detection_preserves_logged_and_narrow_handlers(
    handler, body, expected
):
    """Inputs: actual Python handler syntax. Output: only pass/continue-only broad handlers are flagged."""
    clause = f"except {handler}:" if handler else "except:"
    source = (
        f"while True:\n    try:\n        operation()\n    {clause}\n        {body}\n"
    )
    findings = guard._ast_silent_except(ast.parse(source), source)
    assert bool(findings) == expected
    if findings:
        assert findings[0][0:2] == (5, 8)


@pytest.mark.parametrize(
    "engine", ["_ast_assert_in_production", "_ast_silent_except", "_ast_bare_except"]
)
def test_ast_diagnostic_survives_unavailable_source_segment(monkeypatch, engine):
    """Inputs: real AST and failed excerpt extraction. Output: the finding is retained with a safe excerpt."""
    source = "try:\n    assert value\nexcept:\n    pass\n"
    tree = ast.parse(source)

    def fail_excerpt(*_args):
        """Inputs: AST segment request. Output: simulated unsupported source positions."""
        raise ValueError("fixture source mapping failure")

    monkeypatch.setattr(guard.ast, "get_source_segment", fail_excerpt)
    findings = getattr(guard, engine)(tree, source)
    assert len(findings) == 1 and findings[0][3]


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("'select %s' % name", True),
        ("'select ' + name", True),
        ("'select {}'.format(name)", True),
        ("query", False),
    ],
)
def test_sql_detector_distinguishes_interpolation_from_parameter_binding(
    expression, expected
):
    """Inputs: executable SQL AST shapes. Output: dynamic queries flagged, parameterized identifiers retained."""
    source = f"cursor.execute({expression}, (value,))\ncursor.execute()\n"
    assert bool(guard._ast_sql_interpolation(ast.parse(source), source)) == expected


def test_unusual_decorator_and_keyword_only_subprocess_do_not_crash_detector():
    """Inputs: supported AST expressions outside simple-name forms. Output: no false finding or crash."""
    decorator = (
        ast.parse("@(lambda function: function)\ndef wrapped():\n    return 1\n")
        .body[0]
        .decorator_list[0]
    )
    assert guard._decorator_name(decorator) is None
    source = "subprocess.run(args=command)\n"
    assert guard._ast_subprocess_bare_path(ast.parse(source), source) == []


@pytest.mark.parametrize(
    "path,pattern",
    [("scope", "scope/"), ("one/scope/source.py", "scope/"), ("sub/.env", ".env")],
)
def test_directory_and_basename_patterns_match_explicit_scope(path, pattern):
    """Inputs: root/nested directory and basename patterns. Output: stable intended matching."""
    assert guard._matches_any(path, [pattern])
    assert not guard._matches_any("unrelated/source.py", [pattern])


@pytest.mark.parametrize(
    "path", ["test_module.py", "module_test.py", "nested/test_module.py"]
)
def test_test_filename_conventions_are_recognized(path):
    """Inputs: root and nested test filenames. Output: the documented test classification."""
    assert guard._is_test_path(path)


def test_long_finding_excerpt_is_bounded_without_losing_identity():
    """Inputs: long source excerpt. Output: rule, location and diagnostic retained without full source dump."""
    rendered = guard.Finding(
        "rule", "high", "source.py", 7, 3, "diagnostic", "x" * 500
    ).render()
    assert "rule/high" in rendered and "source.py:7:3" in rendered
    assert "diagnostic" in rendered
    assert rendered.count("x") == 200
