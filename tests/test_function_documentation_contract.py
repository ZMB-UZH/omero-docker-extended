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
PLACEHOLDER_SUMMARY_PREFIXES = (
    "Run run ",
    "Run runtime ",
    "Run runner.",
    "Return get ",
    "Return whether is ",
    "Verify test ",
)
PLACEHOLDER_PHRASES = (
    "computed value",
    "Initialize the instance.",
    "provided inputs",
    "Return the wrapped.",
    "Return the wrapped binary.",
    "Inputs: test runner invokes it",
    "pytest/unittest supplies",
    "Output: asserts the ",
    "Output: fails if ",
    "caller-visible state transition",
    "unavailable state",
    "validation or external operations fail",
    "modeled service failures",
    "modeled failure path",
    "with focused assertions",
    "operation to the current runtime state",
    "fake the ",
    "value value",
    "call on test double",
)
ROBOTIC_SUMMARY_RES = (re.compile(r"^Represent [A-Za-z0-9 _-]+\.$"),)
BROKEN_GENERATED_SUMMARY_RES = (
    re.compile(r"\beffects from\b"),
    re.compile(r"\bReturn the or\b"),
    re.compile(
        r"^Parse the (?:bool|port|mode|github repository|deepsource repository)\.$",
        re.IGNORECASE,
    ),
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


def _title_from_name(name: str) -> str:
    """Return the generated title form that is too weak as a summary.

    Inputs: `name`. Output: `str`.
    """
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name.strip("_") or name)
    return " ".join(part for part in words.split("_") if part).capitalize() + "."


def _is_generated_pascal_return_summary(first_line: str) -> bool:
    """Return whether a summary is a generated PascalCase return phrase.

    Inputs: `first_line`. Output: `bool`.
    """
    if not first_line.endswith("."):
        return False

    body = first_line[:-1]
    for prefix in ("Return whether ", "Return "):
        if not body.startswith(prefix):
            continue
        words = body[len(prefix) :].split()
        if not words:
            return False
        if prefix == "Return " and words[0] in {"False", "None", "True"}:
            return False
        return all(_is_upper_or_pascal_word(word) for word in words)
    return False


def _is_upper_or_pascal_word(word: str) -> bool:
    """Return whether a word is ASCII uppercase or PascalCase.

    Inputs: `word`. Output: `bool`.
    """
    return (
        word.isascii()
        and word.isalpha()
        and (word.isupper() or (word[0].isupper() and word[1:].islower()))
    )


def _has_duplicate_or_filler_line(text: str) -> bool:
    """Return whether documentation contains broken generated filler lines.

    Inputs: `text`. Output: `bool`.
    """
    previous = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            previous = None
            continue
        if stripped in ("state.", previous):
            return True
        previous = stripped
    return False


def _has_placeholder_text(text: str, name: str) -> bool:
    """Return whether documentation still has generated placeholder phrasing.

    Inputs: `text`, `name`. Output: `bool`.
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return (
        any(phrase in text for phrase in PLACEHOLDER_PHRASES)
        or bool(re.search(r"\bOutput:\s*call result\b", text))
        or any(first_line.startswith(prefix) for prefix in PLACEHOLDER_SUMMARY_PREFIXES)
        or any(regex.search(first_line) for regex in ROBOTIC_SUMMARY_RES)
        or any(regex.search(first_line) for regex in BROKEN_GENERATED_SUMMARY_RES)
        or _is_generated_pascal_return_summary(first_line)
        or first_line == _title_from_name(name)
        or _has_duplicate_or_filler_line(text)
    )


def test_generated_pascal_return_summary_detection_is_deterministic() -> None:
    """Verify Pascal return placeholder detection uses exact token checks.

    Inputs: static summary examples. Output: asserts accepted and rejected forms.
    """
    generated = (
        "Return HTTP.",
        "Return Window Start.",
        "Return whether Active.",
    )
    accepted = (
        "Return True.",
        "Return the parsed mode.",
        "Return whether a summary is useful.",
        "Return Job ID 42.",
    )

    for summary in generated:
        assert _is_generated_pascal_return_summary(summary)
    for summary in accepted:
        assert not _is_generated_pascal_return_summary(summary)


def test_python_functions_have_compact_non_placeholder_docstrings() -> None:
    """Verify python functions have compact non placeholder docstrings.

    Inputs: repository fixtures. Output: fails on regressions in python functions have compact non placeholder docstrings.
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
            if not _has_function_io_text(docstring) or _has_placeholder_text(
                docstring, node.name
            ):
                failures.append(_relative(path, node.lineno, node.name))

    assert not failures, "Undocumented Python functions:\n" + "\n".join(failures[:200])


def test_stub_functions_have_leading_documentation_comments() -> None:
    """Verify stub functions have leading documentation comments.

    Inputs: repository fixtures. Output: fails on regressions in stub functions have leading documentation comments.
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
                or _has_placeholder_text(
                    previous.removeprefix("#").strip(), match.group("name")
                )
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented stub functions:\n" + "\n".join(failures[:200])


def test_shell_functions_have_leading_documentation_comments() -> None:
    """Verify shell functions have leading documentation comments.

    Inputs: repository fixtures. Output: fails on regressions in shell functions have leading documentation comments.
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
                or _has_placeholder_text(
                    previous.removeprefix("#").strip(), match.group("name")
                )
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented shell functions:\n" + "\n".join(failures[:200])


def test_named_javascript_functions_have_leading_documentation_comments() -> None:
    """Verify named javascript functions have leading documentation comments.

    Inputs: repository fixtures. Output: fails on regressions in named javascript functions have leading documentation comments.
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
                or _has_placeholder_text(comment_text, match.group("name"))
            ):
                failures.append(_relative(path, index + 1, match.group("name")))

    assert not failures, "Undocumented JavaScript functions:\n" + "\n".join(
        failures[:200]
    )
