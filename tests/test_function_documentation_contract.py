"""Regression checks for compact function documentation coverage."""

from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".cache",
    ".git",
    "node_modules",
    "omero_data",
    "omero_temp",
    "postgresdb",
    "third_party",
}
PLACEHOLDER_DOCSTRING_PREFIXES = (
    "Run ",
    "Run run ",
    "Run runtime ",
    "Run runner.",
    "Return get ",
    "Return whether is ",
    "Verify test ",
)
PYI_FUNCTION_RE = re.compile(r"^(?P<indent>\s*)def\s+(?P<name>[A-Za-z_]\w*)\b")
SHELL_FUNCTION_RES = (
    re.compile(r"^(?P<indent>\s*)(?:function\s+)?(?P<name>[A-Za-z_]\w*)\s*\(\)\s*\{"),
    re.compile(r"^(?P<indent>\s*)function\s+(?P<name>[A-Za-z_]\w*)\s*\{"),
)
JS_FUNCTION_RES = (
    re.compile(
        r"^(?P<indent>\s*)(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*\("
    ),
    re.compile(
        r"^(?P<indent>\s*)(?:const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*="
        r"\s*(?:async\s*)?\([^)]*\)\s*=>"
    ),
    re.compile(
        r"^(?P<indent>\s*)(?:const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*="
        r"\s*(?:async\s*)?function\b"
    ),
    re.compile(
        r"^(?P<indent>\s*)(?:const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*="
        r"\s*\(?\s*(?:async\s*)?\([^)]*\)\s*=>"
    ),
    re.compile(
        r"^(?P<indent>\s*)(?:const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*="
        r"\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>"
    ),
)


def _is_repo_source(path: Path) -> bool:
    """Return whether repo source.

    Inputs: `path`. Output: `bool`.
    """
    relative_parts = path.relative_to(REPO_ROOT).parts
    return not any(part in EXCLUDED_PARTS for part in relative_parts)


def _previous_nonblank(lines: list[str], index: int) -> str:
    """Return the previous non-empty line before index.

    Inputs: `lines`, `index`. Output: `str`.
    """
    cursor = index - 1
    while cursor >= 0:
        if lines[cursor].strip():
            return lines[cursor].lstrip()
        cursor -= 1
    return ""


def _relative(path: Path, line_number: int, name: str) -> str:
    """Return a compact source location for assertion output.

    Inputs: `path`, `line_number`, `name`. Output: `str`.
    """
    return f"{path.relative_to(REPO_ROOT)}:{line_number}:{name}"


def _has_function_io_text(text: str) -> bool:
    """Return whether documentation states compact input and output contracts.

    Inputs: `text`. Output: `bool`.
    """
    return text.count("Inputs:") == 1 and text.count("Output:") == 1


def _has_placeholder_text(text: str) -> bool:
    """Return whether documentation still has generated placeholder phrasing.

    Inputs: `text`. Output: `bool`.
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return first_line.startswith(PLACEHOLDER_DOCSTRING_PREFIXES) or (
        "provided inputs" in first_line
    )


def test_python_functions_have_compact_non_placeholder_docstrings() -> None:
    """Verify python functions have compact non placeholder docstrings.

    Inputs: none. Output: None.
    """
    failures: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if not _is_repo_source(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            docstring = ast.get_docstring(node, clean=True)
            if not docstring:
                failures.append(_relative(path, node.lineno, node.name))
                continue
            if not _has_function_io_text(docstring) or _has_placeholder_text(docstring):
                failures.append(_relative(path, node.lineno, node.name))

    assert not failures, "Undocumented Python functions:\n" + "\n".join(failures[:200])


def test_stub_functions_have_leading_documentation_comments() -> None:
    """Verify stub functions have leading documentation comments.

    Inputs: none. Output: None.
    """
    failures: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.pyi")):
        if not _is_repo_source(path):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = PYI_FUNCTION_RE.match(line)
            if not match:
                continue
            previous = _previous_nonblank(lines, index)
            if (
                not previous.startswith("#")
                or not _has_function_io_text(previous)
                or _has_placeholder_text(previous.removeprefix("#").strip())
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented stub functions:\n" + "\n".join(failures[:200])


def test_shell_functions_have_leading_documentation_comments() -> None:
    """Verify shell functions have leading documentation comments.

    Inputs: none. Output: None.
    """
    failures: list[str] = []
    shell_paths = list(REPO_ROOT.rglob("*.sh")) + list(REPO_ROOT.rglob("*.bash"))
    for path in sorted(shell_paths):
        if not _is_repo_source(path):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = next(
                (
                    candidate
                    for regex in SHELL_FUNCTION_RES
                    if (candidate := regex.match(line))
                ),
                None,
            )
            if not match:
                continue
            previous = _previous_nonblank(lines, index)
            if (
                not previous.startswith("#")
                or not _has_function_io_text(previous)
                or _has_placeholder_text(previous.removeprefix("#").strip())
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented shell functions:\n" + "\n".join(failures[:200])


def test_named_javascript_functions_have_leading_documentation_comments() -> None:
    """Verify named javascript functions have leading documentation comments.

    Inputs: none. Output: None.
    """
    failures: list[str] = []
    js_paths = [
        path
        for pattern in ("*.js", "*.mjs", "*.html")
        for path in REPO_ROOT.rglob(pattern)
    ]
    for path in sorted(js_paths):
        if not _is_repo_source(path):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = next(
                (
                    candidate
                    for regex in JS_FUNCTION_RES
                    if (candidate := regex.match(line))
                ),
                None,
            )
            if not match:
                continue
            previous = _previous_nonblank(lines, index)
            comment_text = previous
            for prefix in ("//", "/*", "*"):
                if comment_text.startswith(prefix):
                    comment_text = comment_text.removeprefix(prefix).strip()
                    break
            if (
                not previous.startswith(("//", "/*", "*"))
                or not _has_function_io_text(comment_text)
                or _has_placeholder_text(comment_text)
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented JavaScript functions:\n" + "\n".join(
        failures[:200]
    )
