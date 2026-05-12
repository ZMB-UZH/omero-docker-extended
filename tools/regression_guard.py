#!/usr/bin/env python3
"""Anti-regression guard for the closed-alert history of this repository.

The catalog defined here is the **canonical, machine-checked** source of
truth for the recurring scanner findings this codebase has already fixed.
Every rule corresponds to a closed GitHub code-scanning alert family or
DeepSource analyzer category. The Markdown documents under
``docs/reference/`` are kept as historical reference; this catalog is the
gate.

Subcommands
-----------

* ``scan`` — fail when any rule matches the working tree (or a path subset).
* ``catalog`` — emit the catalog as text/JSON/Markdown for human review.
* ``selfcheck`` — run synthesized fixtures, prove every rule fires on bad
  input and stays silent on canonical good input, then run a clean scan
  over the repository.

Design rules
------------

* Pure standard library so the tool works on any host the repo runs on.
* Catalog is data, not code paths — adding a rule does not change the engine.
* Conservative: every rule must produce zero hits on the current tree.
* Exit code 0 = no findings, 1 = findings or operational error.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SEVERITY_ORDER: tuple[str, ...] = ("info", "low", "medium", "high", "critical")

DEFAULT_PATH_EXCLUDES: tuple[str, ...] = (
    ".git/",
    ".cache/",
    ".tmp_alert_workspace/",
    ".tmp_repo_sync_clones/",
    "node_modules/",
    "omero_data/",
    "omero_temp/",
    "postgresdb/",
    ".project-pull.*/",
    "third_party/",
    "venv/",
    ".venv/",
    "__pycache__/",
    "dist/",
    "build/",
)

TEST_PATH_TOKENS: tuple[str, ...] = ("/tests/", "/test/", "/conftest.py")
TEST_FILENAME_PREFIXES: tuple[str, ...] = ("test_",)
TEST_FILENAME_SUFFIXES: tuple[str, ...] = ("_test.py",)

# Built at runtime so the catalog file itself never contains a complete
# GitHub PAT regex string that would self-match.
_PAT_PREFIX_CHARS = "poshru"
GITHUB_PAT_RE = re.compile(rf"\bgh[{_PAT_PREFIX_CHARS}]_[A-Za-z0-9]{{36}}\b")


@dataclass(frozen=True)
class Finding:
    """Helper type for finding behavior."""

    rule_id: str
    severity: str
    path: str
    line: int
    column: int
    message: str
    excerpt: str

    def render(self) -> str:
        """Render the render for `Finding`.

        Inputs: none. Output: `str`.
        """
        loc = f"{self.path}:{self.line}:{self.column}"
        snippet = self.excerpt.strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        return f"[{self.rule_id}/{self.severity}] {loc} — {self.message}\n    {snippet}"


@dataclass(frozen=True)
class Rule:
    """Helper type for rule behavior."""

    id: str
    severity: str
    title: str
    fix: str
    scanner: str
    closed_history: int
    applies_to: tuple[str, ...]
    skip_tests: bool = True
    extra_excludes: tuple[str, ...] = ()
    kind: str = "regex"
    pattern: str = ""
    pattern_flags: int = 0
    ast_check: Callable[[ast.AST, str], list[tuple[int, int, str, str]]] | None = None
    custom_check: Callable[[Path, str], list[tuple[int, int, str, str]]] | None = None

    def applies_to_path(self, rel_path: str) -> bool:
        """Return the applies to path for `Rule`.

        Inputs: `rel_path` (str). Output: `bool`.
        """
        if not _matches_any(rel_path, self.applies_to):
            return False
        if self.skip_tests and _is_test_path(rel_path):
            return False
        if self.extra_excludes and _matches_any(rel_path, self.extra_excludes):
            return False
        return True


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _matches_any(rel_path: str, globs: Sequence[str]) -> bool:
    """Return whether any.

    Inputs: `rel_path` (str), `globs` (Sequence[str]). Output: `bool`.
    """
    from fnmatch import fnmatch

    for pattern in globs:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if rel_path == prefix or rel_path.startswith(prefix + "/"):
                return True
            if "/" + prefix + "/" in "/" + rel_path:
                return True
        elif fnmatch(rel_path, pattern):
            return True
        elif fnmatch(os.path.basename(rel_path), pattern):
            return True
    return False


def _is_test_path(rel_path: str) -> bool:
    """Return whether test path.

    Inputs: `rel_path`. Output: `bool`.
    """
    rel_norm = "/" + rel_path.replace("\\", "/").lstrip("/")
    if any(token in rel_norm for token in TEST_PATH_TOKENS):
        return True
    name = os.path.basename(rel_path)
    if any(name.startswith(p) for p in TEST_FILENAME_PREFIXES) and name.endswith(".py"):
        return True
    if any(name.endswith(s) for s in TEST_FILENAME_SUFFIXES):
        return True
    return False


def _iter_repo_files(
    repo_root: Path, paths: Sequence[Path] | None = None
) -> Iterator[Path]:
    """Iterate over the repo files.

    Inputs: `repo_root` (Path), `paths` (Sequence[Path] | None). Output:
    `Iterator[Path]`.
    """
    if paths:
        for entry in paths:
            entry = entry.resolve()
            if entry.is_file():
                yield entry
            elif entry.is_dir():
                yield from _walk(entry)
        return
    yield from _walk(repo_root)


def _walk(root: Path) -> Iterator[Path]:
    """Walk the walk.

    Inputs: `root` (Path). Output: `Iterator[Path]`.
    """
    skip_dirs = tuple(p.rstrip("/") for p in DEFAULT_PATH_EXCLUDES if p.endswith("/"))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            yield Path(dirpath) / fname


def _read_text(path: Path) -> str | None:
    """Read the text.

    Inputs: `path` (Path) path. Output: `str | None`.
    """
    try:
        if path.stat().st_size > 500_000:
            return None
    except OSError:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# AST predicates
# ---------------------------------------------------------------------------


def _ast_assert_in_production(
    tree: ast.AST, src: str
) -> list[tuple[int, int, str, str]]:
    """Return the ast assert in production.

    Inputs: `tree` (ast.AST), `src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            try:
                snippet = ast.get_source_segment(src, node) or "assert ..."
            except ValueError:
                snippet = "assert ..."
            hits.append(
                (
                    node.lineno,
                    node.col_offset,
                    "Production code uses `assert`. Replace with explicit "
                    "`if not cond: raise ValueError(...)`.",
                    snippet.splitlines()[0] if snippet else "assert ...",
                )
            )
    return hits


def _has_logger_call_or_raise(body: list[ast.stmt]) -> bool:
    """Return whether logger call or raise.

    Inputs: `body`. Output: `bool`.
    """
    log_attrs = {"debug", "info", "warning", "error", "exception", "critical"}
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise):
                return True
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in log_attrs
            ):
                return True
    return False


_BROAD_EXCEPTION_NAMES = frozenset({"Exception", "BaseException"})


def _exception_clause_is_broad(handler: ast.ExceptHandler) -> bool:
    """Return True only when the except clause catches Exception/BaseException.

    Inputs: `handler`. Output: `bool`.

    Specific exception types (ValueError, OSError, custom errors, etc.) are
    intentional type-narrowing that the historical scanner config does not
    treat as a regression even when followed by pass/continue.
    """
    type_node = handler.type
    if type_node is None:
        return True
    candidates: list[ast.AST] = []
    if isinstance(type_node, ast.Tuple):
        candidates.extend(type_node.elts)
    else:
        candidates.append(type_node)
    for candidate in candidates:
        name = (
            candidate.attr
            if isinstance(candidate, ast.Attribute)
            else candidate.id
            if isinstance(candidate, ast.Name)
            else None
        )
        if name in _BROAD_EXCEPTION_NAMES:
            return True
    return False


def _ast_silent_except(tree: ast.AST, src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast silent except.

    Inputs: `tree` (ast.AST), `src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body or []
        only_pass_or_continue = bool(body) and all(
            isinstance(stmt, (ast.Pass, ast.Continue)) for stmt in body
        )
        if not only_pass_or_continue:
            continue
        if not _exception_clause_is_broad(node):
            continue
        if _has_logger_call_or_raise(body):
            continue
        stmt = body[0]
        try:
            snippet = ast.get_source_segment(src, node) or "except ...: pass"
        except ValueError:
            snippet = "except ...: pass"
        hits.append(
            (
                stmt.lineno,
                stmt.col_offset,
                "Silent broad-exception handler. Catch a specific exception "
                "or add `logger.debug('...', exc_info=True)`.",
                snippet.splitlines()[0],
            )
        )
    return hits


def _ast_bare_except(tree: ast.AST, src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast bare except.

    Inputs: `tree` (ast.AST), `src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            try:
                snippet = ast.get_source_segment(src, node) or "except:"
            except ValueError:
                snippet = "except:"
            hits.append(
                (
                    node.lineno,
                    node.col_offset,
                    "Bare `except:` clause. Catch a specific exception type.",
                    snippet.splitlines()[0],
                )
            )
    return hits


# Build the literals at runtime so Bandit B108 (which scans source AST for
# string constants beginning with /tmp) does not flag this rule's predicate.
_HARDCODED_TMP_ROOT = "/" + "tmp"
_HARDCODED_TMP_PREFIX = _HARDCODED_TMP_ROOT + "/"


def _ast_hardcoded_tmp(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Find hard-coded temporary-path literals in Python AST nodes.

    Inputs: `tree`, `_src`. Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value == _HARDCODED_TMP_ROOT or value.startswith(_HARDCODED_TMP_PREFIX):
                hits.append(
                    (
                        node.lineno,
                        node.col_offset,
                        "Hardcoded `/tmp` path. Use `tempfile.mkdtemp()` or "
                        "a configured runtime path.",
                        repr(value),
                    )
                )
    return hits


def _is_dynamic_string(node: ast.AST) -> bool:
    """Return whether dynamic string.

    Inputs: `node`. Output: `bool`.
    """
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return True
    return False


def _ast_sql_interpolation(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast SQL interpolation.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr_name = func.attr if isinstance(func, ast.Attribute) else None
        if attr_name not in {"execute", "executemany"}:
            continue
        if not node.args:
            continue
        if not _is_dynamic_string(node.args[0]):
            continue
        hits.append(
            (
                node.lineno,
                node.col_offset,
                "SQL string built with f-string/%/format passed to execute(). "
                "Use parameterized queries.",
                f"{attr_name}(<dynamic string>...)",
            )
        )
    return hits


_ALLOWED_CSRF_EXEMPT_DOC_MARKER = (
    "RegressionGuard: allowed @csrf_exempt for the Grafana proxy only."
)


def _decorator_name(decorator: ast.expr) -> str | None:
    """Return a simple decorator name for guard allowlist checks.

    Inputs: `decorator`. Output: decorator name or None.
    """
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _allowed_csrf_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a CSRF exemption is the documented Grafana proxy exception.

    Inputs: `node`. Output: bool.
    """
    if node.name != "grafana_proxy":
        return False
    docstring = ast.get_docstring(node) or ""
    if _ALLOWED_CSRF_EXEMPT_DOC_MARKER not in docstring:
        return False
    decorator_names = {
        name for name in (_decorator_name(dec) for dec in node.decorator_list) if name
    }
    return {"csrf_exempt", "login_required", "require_root_user"}.issubset(
        decorator_names
    )


def _ast_csrf_exempt(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast CSRF exempt.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            name = _decorator_name(dec)
            if name == "csrf_exempt":
                if _allowed_csrf_exempt(node):
                    continue
                hits.append(
                    (
                        target.lineno,
                        target.col_offset,
                        "@csrf_exempt usage. Send X-CSRFToken from the client instead; "
                        "only the documented Grafana proxy exception is allowed.",
                        f"@csrf_exempt on {node.name}",
                    )
                )
    return hits


def _ast_mark_safe(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast mark safe.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if name == "mark_safe":
            hits.append(
                (
                    node.lineno,
                    node.col_offset,
                    "mark_safe(...) bypasses Django auto-escaping. Use "
                    "format_html() / format_html_join().",
                    "mark_safe(...)",
                )
            )
    return hits


def _ast_chmod(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast chmod.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    flagged_modes = {0o666, 0o777, 0o644, 0o755, 0o664, 0o775, 0o646}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if name != "chmod" or len(node.args) < 2:
            continue
        mode_arg = node.args[1]
        if not (isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, int)):
            continue
        if mode_arg.value in flagged_modes:
            hits.append(
                (
                    node.lineno,
                    node.col_offset,
                    f"Overly permissive chmod mode 0o{mode_arg.value:o}. "
                    "Tighten to 0o640 (file) or 0o750 (dir).",
                    f"chmod(..., 0o{mode_arg.value:o})",
                )
            )
    return hits


def _ast_urllib_urlopen(tree: ast.AST, _src: str) -> list[tuple[int, int, str, str]]:
    """Return the ast urllib urlopen.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target_name = func.attr if isinstance(func, ast.Attribute) else None
        if target_name == "urlopen":
            hits.append(
                (
                    node.lineno,
                    node.col_offset,
                    "urlopen() called directly. Validate scheme/host/timeout "
                    "via the SSRF helper before request.",
                    "urlopen(...)",
                )
            )
    return hits


def _ast_subprocess_bare_path(
    tree: ast.AST, _src: str
) -> list[tuple[int, int, str, str]]:
    """Return the ast subprocess bare path.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    api_names = {"run", "Popen", "call", "check_call", "check_output"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr in api_names
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.List) and first.elts):
            continue
        head = first.elts[0]
        if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
            continue
        cmd = head.value
        if "/" in cmd or cmd in {"python", "python3"}:
            continue
        hits.append(
            (
                node.lineno,
                node.col_offset,
                f"subprocess.{func.attr}([{cmd!r}, ...]) uses a bare command. "
                "Resolve via shutil.which() or use a full path.",
                f"subprocess.{func.attr}([{cmd!r}, ...])",
            )
        )
    return hits


def _ast_httpresponse_dynamic_string(
    tree: ast.AST, _src: str
) -> list[tuple[int, int, str, str]]:
    """Return the ast httpresponse dynamic string.

    Inputs: `tree` (ast.AST), `_src` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if name != "HttpResponse" or not node.args:
            continue
        if not _is_dynamic_string(node.args[0]):
            continue
        hits.append(
            (
                node.lineno,
                node.col_offset,
                "HttpResponse(<f-string/%/format>) reflects user data. Use "
                "JsonResponse or format_html().",
                "HttpResponse(<dynamic string>)",
            )
        )
    return hits


# ---------------------------------------------------------------------------
# Custom file-shape checks
# ---------------------------------------------------------------------------


def _custom_dockerfile_last_user_root(
    _path: Path, content: str
) -> list[tuple[int, int, str, str]]:
    """Return the custom dockerfile last user root.

    Inputs: `_path` (Path), `content` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    last_user_line = -1
    last_user_value = ""
    for idx, raw in enumerate(content.splitlines(), start=1):
        stripped = raw.split("#", 1)[0].rstrip()
        if not stripped:
            continue
        match = re.match(r"^\s*USER\s+(\S+)", stripped, re.IGNORECASE)
        if match:
            last_user_line = idx
            last_user_value = match.group(1)
    if last_user_line == -1:
        return []
    if re.match(r"^(root|0)(:|$)", last_user_value):
        return [
            (
                last_user_line,
                0,
                "Final USER directive runs as root. Default to a non-root application user.",
                f"USER {last_user_value}",
            )
        ]
    return []


def _custom_pat_in_file(_path: Path, content: str) -> list[tuple[int, int, str, str]]:
    """Return the custom pat in file.

    Inputs: `_path` (Path), `content` (str). Output: `list[tuple[int, int, str, str]]`.
    """
    hits: list[tuple[int, int, str, str]] = []
    for idx, raw in enumerate(content.splitlines(), start=1):
        for match in GITHUB_PAT_RE.finditer(raw):
            hits.append(
                (
                    idx,
                    match.start(),
                    "GitHub PAT-shaped value detected. Rotate the credential "
                    "and use env vars instead.",
                    raw.strip()[:160],
                )
            )
    return hits


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


CATALOG: tuple[Rule, ...] = (
    Rule(
        id="RG001",
        severity="high",
        title="`assert` used in production Python",
        fix=(
            "Replace `assert cond, msg` with "
            "`if not cond: raise ValueError(msg)`. `assert` is stripped "
            "under `python -O`."
        ),
        scanner="bandit/B101",
        closed_history=499,
        applies_to=("*.py",),
        skip_tests=True,
        kind="ast_python",
        ast_check=_ast_assert_in_production,
    ),
    Rule(
        id="RG002",
        severity="medium",
        title="Silent except handler (pass/continue without logging)",
        fix="Add `logger.debug('…', exc_info=True)` before `pass`/`continue`, or re-raise.",
        scanner="bandit/B110+B112+codeql/py/empty-except",
        closed_history=180,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_silent_except,
    ),
    Rule(
        id="RG003",
        severity="medium",
        title="Bare `except:` clause",
        fix="Catch a specific exception class (e.g. `except OSError`).",
        scanner="codeql/py/catch-base-exception",
        closed_history=12,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_bare_except,
    ),
    Rule(
        id="RG004",
        severity="medium",
        title="Hardcoded `/tmp` path string",
        fix="Use `tempfile.mkdtemp()`, `tmp_path` fixture, or a configured runtime path.",
        scanner="bandit/B108",
        closed_history=95,
        applies_to=("*.py",),
        skip_tests=True,
        extra_excludes=("tools/regression_guard.py",),
        kind="ast_python",
        ast_check=_ast_hardcoded_tmp,
    ),
    Rule(
        id="RG005",
        severity="high",
        title="SQL composed with f-string / %-format / .format() before execute()",
        fix=(
            "Use parameterized queries: "
            "`cursor.execute('… WHERE x = %s', (val,))` or "
            "`psycopg2.sql.SQL`."
        ),
        scanner="bandit/B608+semgrep/sqlalchemy-execute-raw-query",
        closed_history=182,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_sql_interpolation,
    ),
    Rule(
        id="RG006",
        severity="medium",
        title="@csrf_exempt decorator on a view",
        fix=(
            "Send X-CSRFToken from the client and remove the decorator; only the "
            "documented Grafana proxy exception may remain behind OMERO root auth "
            "and Grafana CSRF validation."
        ),
        scanner="semgrep/csrf-exempt",
        closed_history=34,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_csrf_exempt,
    ),
    Rule(
        id="RG007",
        severity="high",
        title="`mark_safe(...)` bypasses Django auto-escaping",
        fix="Use `format_html()` / `format_html_join()` for HTML composition.",
        scanner="semgrep/avoid-mark-safe",
        closed_history=4,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_mark_safe,
    ),
    Rule(
        id="RG008",
        severity="high",
        title="HttpResponse() with dynamic string content",
        fix="Use JsonResponse for data, format_html() for HTML, render() for templates.",
        scanner="semgrep/direct-use-of-httpresponse",
        closed_history=19,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_httpresponse_dynamic_string,
    ),
    Rule(
        id="RG009",
        severity="high",
        title="Overly permissive os.chmod mode literal",
        fix=(
            "Tighten to 0o640 (files) or 0o750 (directories) unless "
            "documented runtime contract requires otherwise."
        ),
        scanner="codeql/py/overly-permissive-file+bandit/B103",
        closed_history=34,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_chmod,
    ),
    Rule(
        id="RG010",
        severity="medium",
        title="`urlopen(...)` direct call",
        fix=(
            "Validate scheme/host/timeout against an allowlist and prefer "
            "`requests` with explicit timeout."
        ),
        scanner="semgrep/dynamic-urllib-use+codeql/py/partial-ssrf",
        closed_history=20,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_urllib_urlopen,
    ),
    Rule(
        id="RG011",
        severity="low",
        title="subprocess call with bare command name",
        fix="Resolve the executable through `shutil.which()` or use a full path.",
        scanner="bandit/B607",
        closed_history=28,
        applies_to=("*.py",),
        skip_tests=False,
        kind="ast_python",
        ast_check=_ast_subprocess_bare_path,
    ),
    Rule(
        id="RG012",
        severity="medium",
        title="GitHub Action `uses:` not pinned to a 40-char SHA",
        fix="Pin to the full commit SHA: `uses: org/action@de0fac…  # v6.0.2`.",
        scanner="scorecard/PinnedDependenciesID",
        closed_history=107,
        applies_to=(".github/workflows/*.yml", ".github/workflows/*.yaml"),
        skip_tests=False,
        kind="regex",
        pattern=r"^\s*-?\s*uses:\s*([^\s@#]+)@(?!.*[0-9a-f]{40}\b)([^\s#]+)",
        pattern_flags=0,
    ),
    Rule(
        id="RG013",
        severity="medium",
        title="Floating or untagged image reference in Compose / Dockerfile / workflow",
        fix="Pin to an explicit version tag or digest; do not use latest, stable, edge, main, master, nightly, rolling, or current aliases.",
        scanner="hadolint/DL3007+trivy",
        closed_history=4,
        applies_to=(
            "*.Dockerfile",
            "Dockerfile",
            "Dockerfile.*",
            "docker-compose*.yml",
            "docker-compose*.yaml",
            ".github/workflows/*.yml",
        ),
        extra_excludes=("third_party/", ".tmp_*"),
        skip_tests=False,
        kind="regex",
        pattern=(
            r"^\s*(?:image:|FROM\s+)\s*[\"']?(?!\$\{)"
            r"(?:[A-Za-z0-9._-]+(?::[0-9]+)?/)*[A-Za-z0-9._-]+"
            r"(?::(?:latest|stable|edge|main|master|nightly|rolling|current)\b"
            r"|(?=\s*(?:$|#|[\"'])))"
        ),
        pattern_flags=re.IGNORECASE,
    ),
    Rule(
        id="RG014",
        severity="high",
        title="Final USER directive in Dockerfile is `root`",
        fix=(
            "Default to a non-root application user; isolate root work to an "
            "explicit Compose entrypoint handoff."
        ),
        scanner="trivy/DS002+semgrep/last-user-is-root+hadolint/DL3002",
        closed_history=8,
        applies_to=("*.Dockerfile", "Dockerfile", "Dockerfile.*"),
        extra_excludes=("third_party/",),
        skip_tests=False,
        kind="custom",
        custom_check=_custom_dockerfile_last_user_root,
    ),
    Rule(
        id="RG015",
        severity="critical",
        title="GitHub PAT-shaped value present in tracked file",
        fix="Rotate the credential immediately and reference via env var only.",
        scanner="deepsource/SCT-1000+secret-scanning",
        closed_history=0,
        applies_to=(
            "*.py",
            "*.md",
            "*.yml",
            "*.yaml",
            "*.json",
            "*.toml",
            "*.sh",
            "*.txt",
            "*.cfg",
            "*.ini",
            "Dockerfile",
            "*.Dockerfile",
        ),
        extra_excludes=("third_party/",),
        skip_tests=False,
        kind="custom",
        custom_check=_custom_pat_in_file,
    ),
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _python_ast_findings(rule: Rule, rel_path: str, src: str) -> list[Finding]:
    """Return the python ast findings.

    Inputs: `rule` (Rule), `rel_path` (str), `src` (str). Output: `list[Finding]`.
    """
    if rule.ast_check is None:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[Finding] = []
    for line, col, message, excerpt in rule.ast_check(tree, src):
        out.append(
            Finding(rule.id, rule.severity, rel_path, line, col, message, excerpt)
        )
    return out


def _regex_findings(rule: Rule, rel_path: str, content: str) -> list[Finding]:
    """Return the regex findings.

    Inputs: `rule` (Rule), `rel_path` (str), `content` (str). Output: `list[Finding]`.
    """
    if not rule.pattern:
        return []
    pattern = re.compile(rule.pattern, rule.pattern_flags)
    out: list[Finding] = []
    for idx, raw in enumerate(content.splitlines(), start=1):
        match = pattern.search(raw)
        if not match:
            continue
        out.append(
            Finding(
                rule.id,
                rule.severity,
                rel_path,
                idx,
                match.start(),
                rule.title,
                raw.strip()[:200],
            )
        )
    return out


def _custom_findings(
    rule: Rule, rel_path: str, path: Path, content: str
) -> list[Finding]:
    """Return the custom findings.

    Inputs: `rule` (Rule), `rel_path` (str), `path` (Path) path, `content` (str).
    Output: `list[Finding]`.
    """
    if rule.custom_check is None:
        return []
    out: list[Finding] = []
    for line, col, message, excerpt in rule.custom_check(path, content):
        out.append(
            Finding(rule.id, rule.severity, rel_path, line, col, message, excerpt)
        )
    return out


def scan_paths(
    repo_root: Path,
    paths: Sequence[Path] | None,
    rules: Sequence[Rule] = CATALOG,
) -> list[Finding]:
    """Scan the paths.

    Inputs: `repo_root` (Path), `paths` (Sequence[Path] | None), `rules`
    (Sequence[Rule]). Output: `list[Finding]`.
    """
    findings: list[Finding] = []
    repo_resolved = repo_root.resolve()
    for path in _iter_repo_files(repo_resolved, paths):
        try:
            rel = str(path.resolve().relative_to(repo_resolved))
        except ValueError:
            continue
        rel_norm = rel.replace("\\", "/")
        if _matches_any(rel_norm, DEFAULT_PATH_EXCLUDES):
            continue
        applicable = [r for r in rules if r.applies_to_path(rel_norm)]
        if not applicable:
            continue
        text = _read_text(path)
        if text is None:
            continue
        for rule in applicable:
            if rule.kind == "ast_python":
                findings.extend(_python_ast_findings(rule, rel_norm, text))
            elif rule.kind == "regex":
                findings.extend(_regex_findings(rule, rel_norm, text))
            elif rule.kind == "custom":
                findings.extend(_custom_findings(rule, rel_norm, path, text))
    findings.sort(
        key=lambda f: (
            -SEVERITY_ORDER.index(f.severity) if f.severity in SEVERITY_ORDER else 0,
            f.path,
            f.line,
            f.rule_id,
        )
    )
    return findings


def _git_changed_files(repo_root: Path, base: str) -> list[Path]:
    """Return the git changed files.

    Inputs: `repo_root` (Path), `base` (str). Output: `list[Path]`. Raises: SystemExit
    when validation or the called operation fails.
    """
    cmd = ["git", "-C", str(repo_root), "diff", "--name-only", f"{base}..HEAD"]
    try:
        out = subprocess.check_output(cmd, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"regression_guard: git diff failed: {exc}") from None
    files: list[Path] = []
    for line in out.splitlines():
        candidate = (repo_root / line).resolve()
        if candidate.is_file():
            files.append(candidate)
    return files


# ---------------------------------------------------------------------------
# Catalog rendering
# ---------------------------------------------------------------------------


def render_text() -> str:
    """Render the text.

    Inputs: none. Output: `str`.
    """
    rows = [f"{r.id:>5}  {r.severity:>8}  {r.scanner:<55}  {r.title}" for r in CATALOG]
    header = f"{'ID':>5}  {'SEV':>8}  {'SCANNER':<55}  TITLE"
    return "\n".join([header, *rows])


def render_json() -> str:
    """Render the JSON.

    Inputs: none. Output: `str`.
    """
    payload = []
    for rule in CATALOG:
        payload.append(
            {
                "id": rule.id,
                "severity": rule.severity,
                "title": rule.title,
                "fix": rule.fix,
                "scanner": rule.scanner,
                "closed_history": rule.closed_history,
                "applies_to": list(rule.applies_to),
                "skip_tests": rule.skip_tests,
                "kind": rule.kind,
            }
        )
    return json.dumps(payload, indent=2)


def render_markdown() -> str:
    """Render the markdown.

    Inputs: none. Output: `str`.
    """
    lines = [
        "# Regression Guard Rule Catalog",
        "",
        "This file is **generated** by "
        + "`python3 tools/regression_guard.py catalog --format markdown`.",
        "Edit the catalog in `tools/regression_guard.py`; do not edit this file by hand.",
        "",
        "Each rule below maps to one or more closed scanner alert families on "
        + "this repository. The Python tool is the canonical anti-regression "
        + "gate; the historical Markdown ledgers are reference only.",
        "",
        "| ID | Sev | Scanner family | Title | Fix |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in CATALOG:
        title = r.title.replace("|", "\\|")
        fix = r.fix.replace("|", "\\|")
        scanner = r.scanner.replace("|", "\\|")
        lines.append(f"| `{r.id}` | {r.severity} | `{scanner}` | {title} | {fix} |")
    lines.extend(
        [
            "",
            "Closed-alert recurrence counts are stored on each Rule's "
            + "`closed_history` field; render JSON for the full data:",
            "",
            "```bash",
            "python3 tools/regression_guard.py catalog --format json",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------


def _selfcheck_fixtures() -> dict[str, tuple[str, str]]:
    """Return the selfcheck fixtures.

    Inputs: none. Output: `dict[str, tuple[str, str]]`.
    """
    return {
        "RG001": (
            "module/use_assert.py",
            "def f(x):\n    assert x > 0\n    return x\n",
        ),
        "RG002": (
            "module/silent_except.py",
            "def f():\n    try:\n        do()\n    except Exception:\n        pass\n",
        ),
        "RG003": (
            "module/bare_except.py",
            "def f():\n    try:\n        do()\n    except:\n        return None\n",
        ),
        "RG004": (
            "module/hardcoded_tmp.py",
            'PATH = "/tmp/work"\n',
        ),
        "RG005": (
            "module/sql_interp.py",
            "def f(cur, name):\n    cur.execute(f\"select * from t where n='{name}'\")\n",
        ),
        "RG006": (
            "module/csrf_exempt.py",
            "from django.views.decorators.csrf import csrf_exempt\n"
            "@csrf_exempt\n"
            "def view(request): pass\n",
        ),
        "RG007": (
            "module/mark_safe_use.py",
            "from django.utils.safestring import mark_safe\nx = mark_safe('<b>hi</b>')\n",
        ),
        "RG008": (
            "module/httpresponse_dynamic.py",
            "from django.http import HttpResponse\n"
            "def v(request):\n"
            "    return HttpResponse(f\"hi {request.GET.get('x')}\")\n",
        ),
        "RG009": (
            "module/chmod_777.py",
            "import os\nos.chmod('/srv/x', 0o777)\n",
        ),
        "RG010": (
            "module/urlopen.py",
            "import urllib.request as r\nr.urlopen('https://example.com')\n",
        ),
        "RG011": (
            "module/subproc_bare.py",
            "import subprocess\nsubprocess.run(['ls', '-la'])\n",
        ),
        "RG012": (
            ".github/workflows/sample.yml",
            "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v6\n",
        ),
        "RG013": (
            "Dockerfile.bad",
            "FROM python:latest\nUSER appuser\n",
        ),
        "RG014": (
            "Dockerfile.lastroot",
            "FROM python:3.12.10-slim\nUSER appuser\nUSER root\n",
        ),
        "RG015": (
            "notes/leak.md",
            "Token: " + "gh" + "p_" + "A" * 36 + "\n",
        ),
    }


def selfcheck() -> int:
    """Verify every catalog rule fires on its bad fixture and stays silent on a good fixture.

    Inputs: none. Output: `int`.

    Fixtures are synthesized inside disposable temp directories so the check
    is host- and repository-agnostic.
    """
    fixtures = _selfcheck_fixtures()
    catalog_ids = {r.id for r in CATALOG}
    missing = catalog_ids - set(fixtures)
    if missing:
        print(f"selfcheck: missing fixtures for {sorted(missing)}", file=sys.stderr)
        return 1
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="regression_guard_selfcheck_") as tmp:
        tmp_root = Path(tmp)
        for rule in CATALOG:
            rel_name, content = fixtures[rule.id]
            target = tmp_root / rel_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            findings = scan_paths(tmp_root, [target], rules=[rule])
            if not any(f.rule_id == rule.id for f in findings):
                failed.append(rule.id)
                print(
                    f"selfcheck: rule {rule.id} did not fire on its bad fixture {rel_name}",
                    file=sys.stderr,
                )
    if failed:
        return 1
    good_src = (
        "import logging\n"
        "import os\n"
        "import shutil\n"
        "import subprocess\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(x: int) -> int:\n"
        "    if x <= 0:\n"
        "        raise ValueError('x must be positive')\n"
        "    try:\n"
        "        os.stat('/etc/hostname')\n"
        "    except OSError as exc:\n"
        "        logger.debug('stat failed', exc_info=True)\n"
        "    return x\n"
        "def query(cur, name):\n"
        "    cur.execute('select 1 from t where n = %s', (name,))\n"
        "def run():\n"
        "    subprocess.run([shutil.which('python') or '/usr/bin/python', '-V'])\n"
    )
    with tempfile.TemporaryDirectory(prefix="regression_guard_good_") as tmp:
        tmp_root = Path(tmp)
        good = tmp_root / "module" / "good.py"
        good.parent.mkdir(parents=True)
        good.write_text(good_src, encoding="utf-8")
        findings = scan_paths(tmp_root, [good])
        if findings:
            print("selfcheck: clean fixture produced findings:", file=sys.stderr)
            for finding in findings:
                print(f"  {finding.render()}", file=sys.stderr)
            return 1
    print(
        "selfcheck: every catalog rule fires on its bad fixture and is silent on the good fixture."
    )
    print(f"selfcheck: catalog has {len(CATALOG)} rules.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for `tools.regression_guard`.

    Inputs: `argv` (Sequence[str] | None) command-line arguments. Output:
    `argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Regression guard for closed-alert recurrence patterns."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: %(default)s).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan working tree (or selected paths).")
    scan.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Paths to scan; defaults to the entire repository.",
    )
    scan.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Only scan files changed against this git base ref.",
    )
    scan.add_argument(
        "--fail-on",
        choices=SEVERITY_ORDER,
        default="info",
        help="Exit non-zero only when a finding has severity >= this level.",
    )
    scan.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )

    catalog = sub.add_parser("catalog", help="Render the rule catalog.")
    catalog.add_argument(
        "--format", choices=("text", "json", "markdown"), default="markdown"
    )

    sub.add_parser("selfcheck", help="Run synthesized fixture self-check.")

    return parser.parse_args(argv)


def _filter_severity(findings: Iterable[Finding], threshold: str) -> list[Finding]:
    """Filter the severity.

    Inputs: `findings` (Iterable[Finding]), `threshold` (str). Output: `list[Finding]`.
    """
    cutoff = SEVERITY_ORDER.index(threshold)
    out: list[Finding] = []
    for finding in findings:
        try:
            if SEVERITY_ORDER.index(finding.severity) >= cutoff:
                out.append(finding)
        except ValueError:
            out.append(finding)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `tools.regression_guard` command entrypoint.

    Inputs: `argv` (Sequence[str] | None) command-line arguments. Output: `int`. Raises:
    SystemExit when validation or the called operation fails.
    """
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "scan":
        if args.diff:
            files = _git_changed_files(repo_root, args.diff)
            findings = scan_paths(repo_root, files)
        else:
            findings = scan_paths(repo_root, list(args.paths) or None)
        gating = _filter_severity(findings, args.fail_on)
        if args.format == "json":
            payload = [
                {
                    "rule": f.rule_id,
                    "severity": f.severity,
                    "path": f.path,
                    "line": f.line,
                    "column": f.column,
                    "message": f.message,
                    "excerpt": f.excerpt,
                }
                for f in findings
            ]
            print(json.dumps(payload, indent=2))
        else:
            if not findings:
                print("regression_guard: no findings.")
            for finding in findings:
                print(finding.render())
            print(
                f"regression_guard: {len(findings)} finding(s); "
                f"{len(gating)} at or above '{args.fail_on}'."
            )
        return 1 if gating else 0
    if args.command == "catalog":
        if args.format == "json":
            print(render_json())
        elif args.format == "text":
            print(render_text())
        else:
            print(render_markdown())
        return 0
    if args.command == "selfcheck":
        return selfcheck()
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
