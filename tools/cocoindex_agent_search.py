#!/usr/bin/env python3
"""Host-side CocoIndex Code workflow for AI-agent semantic routing."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import fcntl
import hashlib
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import tempfile
import tomllib
import venv
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, TextIO, cast


PACKAGE_NAME = "cocoindex-code"
PACKAGE_VERSION = "0.2.31"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}[full]=={PACKAGE_VERSION}"
MCP_SERVER_NAME = "cocoindex-code"
MCP_PYTHON_COMMAND = "python3"
MCP_JSONRPC_VERSION = "2.0"
MCP_SEARCH_TOOL_NAME = "search"
ARTIFACT_ROOT_ENV = "AGENT_COCOINDEX_HOME"
REPO_ROOT_ENV = "AGENT_COCOINDEX_REPO"
TIMEOUT_ENV_PREFIX = "AGENT_COCOINDEX_TIMEOUT_"
MIRROR_SCHEMA_VERSION = "1"
FILE_COPY_CHUNK_BYTES = 1024 * 1024
DENIED_MIRROR_BASENAMES = frozenset({".env"})
DENIED_MIRROR_SUFFIXES = (".env",)
DENIED_MIRROR_PARTS = frozenset({".codex", ".cocoindex_code"})
MIRROR_INCLUDE_PATTERNS = ("*",)
MIRROR_EXCLUDE_PATTERNS = (".cocoindex_code/**", "**/.cocoindex_code/**")
DISK_BYTES_ENV_PREFIX = "AGENT_COCOINDEX_DISK_"
MIN_DEFAULT_FREE_BYTES = 2 * 1024 * 1024 * 1024
MAX_DEFAULT_FREE_BYTES = 20 * 1024 * 1024 * 1024
COLD_INDEX_NOTICE = (
    "NOTICE: CocoIndex is building a cold semantic index for this repository; "
    "the first search can take several minutes and later searches reuse the "
    "external cache."
)
INDEX_REQUIRED_MESSAGE = (
    "No active CocoIndex semantic index is recorded for this repository. Run "
    "`python3 tools/cocoindex_agent_search.py index` explicitly when disk "
    "headroom and system load are safe."
)
ACTIVE_INDEX_SCHEMA_VERSION = 1
DEFAULT_TIMEOUTS_SECONDS = {
    "install": 7200,
    "verify_install": 300,
    "init": 1800,
    "index": 14400,
    "search": 600,
    "status": 600,
    "rg": 600,
    "mcp_smoke": 600,
}
MCP_STARTUP_TIMEOUT_SECONDS = 600
MCP_TOOL_TIMEOUT_SECONDS = DEFAULT_TIMEOUTS_SECONDS["index"]
MCP_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MCP_PROTOCOL_PROBE_ATTEMPTS = 3
MCP_PROTOCOL_PROBE_RETRY_DELAY_SECONDS = 0.25

SEARCH_FILE_RE = r"^File: (.*?):\d+(?:-\d+)? "
RG_FILE_RE = r"^(?:\./)?([^:\n]+):\d+:"
LOGGER = logging.getLogger(__name__)


class McpSearchToolUnavailable(RuntimeError):
    """Raised when an initialized MCP server briefly returns no search tool."""


class JsonRpcError(RuntimeError):
    """Raised for JSON-RPC request errors that should be reported to the client."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class IndexRequiredError(RuntimeError):
    """Raised when a safe search refuses to build an index implicitly."""


@dataclass(frozen=True)
class CocoIndexContext:
    """Resolved host-side paths for the CocoIndex agent workflow."""

    repo_root: Path
    artifact_root: Path
    mirror_repo: Path
    mirror_digest: str

    @property
    def venv_dir(self) -> Path:
        return self.artifact_root / "venv" / f"{PACKAGE_NAME}-{PACKAGE_VERSION}"

    @property
    def ccc_bin(self) -> Path:
        return self.venv_dir / "bin" / "ccc"

    @property
    def settings_dir(self) -> Path:
        return self.artifact_root / "settings"

    @property
    def runtime_dir(self) -> Path:
        return self.artifact_root / "runtime" / self.mirror_digest

    @property
    def db_root(self) -> Path:
        return self.artifact_root / "db"

    @property
    def db_dir(self) -> Path:
        return self.db_root / self.mirror_digest

    @property
    def cache_dir(self) -> Path:
        return self.artifact_root / "cache"

    @property
    def hf_home(self) -> Path:
        return self.artifact_root / "huggingface"

    @property
    def pip_cache(self) -> Path:
        return self.artifact_root / "pip-cache"


@dataclass(frozen=True)
class BenchmarkCase:
    """Validated benchmark input case."""

    name: str
    query: str
    rg: str
    expected: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkResult:
    """Measured result for one benchmark case."""

    case: str
    rg_ms: float
    rg_returncode: int
    rg_chars: int
    rg_line_count: int
    rg_unique_files: int
    rg_first_files: list[str]
    rg_expected_rank: int | None
    coco_ms: float
    coco_chars: int
    coco_line_count: int
    coco_unique_files: int
    coco_first_files: list[str]
    coco_expected_rank: int | None
    focused_rg_ms: float
    focused_rg_returncode: int
    focused_rg_chars: int
    focused_rg_line_count: int
    focused_rg_unique_files: int
    hybrid_chars: int

    def as_payload(self) -> dict[str, object]:
        """Return a JSON-serializable benchmark record."""
        return {
            "case": self.case,
            "rg_ms": self.rg_ms,
            "rg_returncode": self.rg_returncode,
            "rg_chars": self.rg_chars,
            "rg_line_count": self.rg_line_count,
            "rg_unique_files": self.rg_unique_files,
            "rg_first_files": self.rg_first_files,
            "rg_expected_rank": self.rg_expected_rank,
            "coco_ms": self.coco_ms,
            "coco_chars": self.coco_chars,
            "coco_line_count": self.coco_line_count,
            "coco_unique_files": self.coco_unique_files,
            "coco_first_files": self.coco_first_files,
            "coco_expected_rank": self.coco_expected_rank,
            "focused_rg_ms": self.focused_rg_ms,
            "focused_rg_returncode": self.focused_rg_returncode,
            "focused_rg_chars": self.focused_rg_chars,
            "focused_rg_line_count": self.focused_rg_line_count,
            "focused_rg_unique_files": self.focused_rg_unique_files,
            "hybrid_chars": self.hybrid_chars,
        }


def resolve_required_executable(name: str) -> str:
    """Resolve a command path or fail with a direct error."""
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"Required command is not available in PATH: {name}")
    return resolved


def run_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and capture output for deterministic error reporting."""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not execute command {' '.join(args)}: {exc}"
        ) from exc


def checked_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and raise with stdout/stderr on failure."""
    completed = run_command(args, cwd=cwd, env=env, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed with exit {completed.returncode}: {' '.join(args)}",
                    "STDOUT:",
                    completed.stdout,
                    "STDERR:",
                    completed.stderr,
                ]
            )
        )
    return completed


def run_command_with_input(
    args: list[str],
    *,
    cwd: Path,
    input_text: str,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with stdin and capture deterministic output."""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not execute command {' '.join(args)}: {exc}"
        ) from exc


def checked_git_command(
    repo_root: Path,
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git with command-scoped trust for the targeted repository."""
    trusted_root = repo_root.resolve()
    return checked_command(
        [
            resolve_required_executable("git"),
            "-c",
            f"safe.directory={trusted_root}",
            *args,
        ],
        cwd=cwd or trusted_root,
        timeout=timeout,
    )


def default_artifact_root() -> Path:
    """Return the host-side artifact root without using repo-local paths."""
    override = os.environ.get(ARTIFACT_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    data_home = os.environ.get("XDG_DATA_HOME")
    data_root = (
        Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    )
    return (data_root / "agent-cocoindex-code").resolve()


def timeout_seconds(name: str) -> int:
    """Return a generous command timeout, optionally overridden by env."""
    if name not in DEFAULT_TIMEOUTS_SECONDS:
        raise RuntimeError(f"Unknown CocoIndex timeout name: {name}")
    env_name = f"{TIMEOUT_ENV_PREFIX}{name.upper()}"
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return DEFAULT_TIMEOUTS_SECONDS[name]
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{env_name} must be a positive integer.")
    return value


def env_bytes(name: str, default: int) -> int:
    """Return a positive byte limit from the environment."""
    raw_value = os.environ.get(f"{DISK_BYTES_ENV_PREFIX}{name}")
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"{DISK_BYTES_ENV_PREFIX}{name} must be a positive integer byte count."
        ) from exc
    if value <= 0:
        raise RuntimeError(
            f"{DISK_BYTES_ENV_PREFIX}{name} must be a positive integer byte count."
        )
    return value


def artifact_usage_bytes(artifact_root: Path) -> int:
    """Return current artifact bytes without following symlinks."""
    if not artifact_root.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(artifact_root):
        root_path = Path(root)
        dirs[:] = [entry for entry in dirs if not (root_path / entry).is_symlink()]
        for name in files:
            path = root_path / name
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                LOGGER.debug("Could not stat CocoIndex artifact file.", exc_info=True)
                continue
            total += stat.st_size
    return total


def default_min_free_bytes(total_bytes: int) -> int:
    """Return a host-scaled minimum free-space floor."""
    return min(
        MAX_DEFAULT_FREE_BYTES,
        max(MIN_DEFAULT_FREE_BYTES, total_bytes // 20),
    )


def require_disk_budget(context: CocoIndexContext, operation: str) -> None:
    """Fail closed before expensive disk-heavy CocoIndex operations."""
    disk_root = context.artifact_root
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    usage = shutil.disk_usage(disk_root)
    min_free_bytes = env_bytes("MIN_FREE_BYTES", default_min_free_bytes(usage.total))
    if usage.free < min_free_bytes:
        raise RuntimeError(
            f"Refusing CocoIndex {operation}: filesystem containing "
            f"{context.artifact_root} has only {usage.free} free bytes, below the "
            f"configured {min_free_bytes} byte minimum."
        )
    max_artifact_bytes = os.environ.get(f"{DISK_BYTES_ENV_PREFIX}MAX_ARTIFACT_BYTES")
    if max_artifact_bytes is not None:
        artifact_limit = env_bytes("MAX_ARTIFACT_BYTES", 1)
        artifact_bytes = artifact_usage_bytes(context.artifact_root)
        if artifact_bytes > artifact_limit:
            raise RuntimeError(
                f"Refusing CocoIndex {operation}: artifact root {context.artifact_root} "
                f"already uses {artifact_bytes} bytes, above the configured "
                f"{artifact_limit} byte limit."
            )


def discover_git_root_candidate(start: Path) -> Path:
    """Return the nearest ancestor containing a Git worktree marker."""
    current = start.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"{start} is not inside a Git work tree.")


def resolve_repo_root() -> Path:
    """Resolve the repository root from env or the current Git checkout."""
    override = os.environ.get(REPO_ROOT_ENV)
    if override:
        candidate = Path(override).expanduser().resolve()
        repo_candidate = discover_git_root_candidate(candidate)
        completed = checked_git_command(
            repo_candidate,
            ["rev-parse", "--show-toplevel"],
            cwd=candidate,
        )
        resolved = Path(completed.stdout.strip()).resolve()
        if resolved != candidate:
            raise RuntimeError(
                f"{REPO_ROOT_ENV} must point at the Git repository root: {candidate}"
            )
        return resolved
    candidate = discover_git_root_candidate(Path.cwd())
    completed = checked_git_command(
        candidate,
        ["rev-parse", "--show-toplevel"],
        cwd=Path.cwd(),
    )
    return Path(completed.stdout.strip()).resolve()


def validate_repo_relative_path(raw_path: str) -> PurePosixPath:
    """Validate a tracked Git path before mirroring it."""
    raw_parts = raw_path.split("/")
    path = PurePosixPath(raw_path)
    invalid = (
        not raw_path
        or "\\" in raw_path
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(ord(character) < 32 for character in raw_path)
    )
    if invalid:
        raise RuntimeError(f"Unsafe tracked path reported by Git: {raw_path!r}")
    return path


def is_allowed_example_env_path(path: PurePosixPath) -> bool:
    """Return whether an env-looking file is an intentional example contract."""
    name = path.name
    return name.endswith("_example.env") or name.endswith(".example.env")


def is_denied_mirror_path(path: PurePosixPath) -> bool:
    """Return whether a Git-visible path must never enter the semantic mirror."""
    if DENIED_MIRROR_PARTS.intersection(path.parts):
        return True
    if path.name in DENIED_MIRROR_BASENAMES:
        return True
    if path.name.endswith(DENIED_MIRROR_SUFFIXES) and not is_allowed_example_env_path(
        path
    ):
        return True
    return False


def tracked_files(
    repo_root: Path, excluded_paths: frozenset[PurePosixPath] = frozenset()
) -> list[PurePosixPath]:
    """Return validated Git-visible, non-ignored files."""
    completed = checked_git_command(
        repo_root,
        ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    )
    paths = [
        validate_repo_relative_path(path)
        for path in completed.stdout.split("\0")
        if path
    ]
    denied = [path.as_posix() for path in paths if is_denied_mirror_path(path)]
    if denied:
        raise RuntimeError(
            "Refusing to mirror deployment-local or CocoIndex artifact paths: "
            + ", ".join(sorted(denied))
        )
    return sorted((path for path in paths if path not in excluded_paths), key=str)


def repo_status_porcelain(repo_root: Path) -> str:
    """Return porcelain status, including untracked files, without printing paths."""
    return checked_git_command(
        repo_root,
        ["status", "--porcelain=v1"],
        timeout=timeout_seconds("rg"),
    ).stdout


def require_clean_index_target(repo_root: Path, *, allow_dirty: bool) -> None:
    """Prevent accidental per-edit index churn unless the caller opts in."""
    if allow_dirty:
        return
    if repo_status_porcelain(repo_root).strip():
        raise RuntimeError(
            "Refusing to build or refresh a CocoIndex index from a dirty worktree. "
            "Commit or stash first, or pass the explicit dirty-index flag when "
            "that disk-heavy operation is intentional."
        )


def verified_repo_source_path(repo_root: Path, relative_path: PurePosixPath) -> Path:
    """Return a repository file path that is safe to read or copy."""
    path_text = relative_path.as_posix()
    source_path = repo_root / Path(relative_path)
    if source_path.is_symlink():
        raise RuntimeError(f"Refusing to mirror tracked symlink: {path_text}")
    resolved = source_path.resolve()
    if not resolved.is_relative_to(repo_root):
        raise RuntimeError(f"Tracked path escapes repository root: {path_text}")
    return source_path


def repo_file_sha256(source_path: Path) -> bytes:
    """Return a file content digest without loading the whole file into memory."""
    digest = hashlib.sha256()
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(FILE_COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.digest()


def file_digest(repo_root: Path, paths: list[PurePosixPath]) -> str:
    """Hash repository file contents without retaining file payloads."""
    digest = hashlib.sha256()
    digest.update(f"schema:{MIRROR_SCHEMA_VERSION}\0".encode())
    for relative_path in paths:
        path_text = relative_path.as_posix()
        digest.update(path_text.encode())
        digest.update(b"\0")
        source_path = verified_repo_source_path(repo_root, relative_path)
        if not source_path.exists():
            digest.update(b"missing\0")
            continue
        digest.update(repo_file_sha256(source_path))
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def file_digest_and_mirror_source(
    repo_root: Path, paths: list[PurePosixPath]
) -> tuple[str, dict[str, bytes]]:
    """Hash small test fixtures and keep bytes for legacy unit assertions."""
    files: dict[str, bytes] = {}
    for relative_path in paths:
        source_path = verified_repo_source_path(repo_root, relative_path)
        if not source_path.exists():
            continue
        payload = source_path.read_bytes()
        path_text = relative_path.as_posix()
        files[path_text] = payload
    return file_digest(repo_root, paths), files


def repo_visible_file_total_bytes(
    repo_root: Path,
    paths: list[PurePosixPath],
) -> int:
    """Return total source bytes that a mirror copy would write."""
    total = 0
    for relative_path in paths:
        source_path = verified_repo_source_path(repo_root, relative_path)
        if source_path.exists():
            total += source_path.stat().st_size
    return total


def require_mirror_write_budget(
    context: CocoIndexContext,
    source_bytes: int,
) -> None:
    """Fail before copying when the mirror cannot fit with free-space headroom."""
    disk_root = context.artifact_root
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    usage = shutil.disk_usage(disk_root)
    min_free_bytes = env_bytes("MIN_FREE_BYTES", default_min_free_bytes(usage.total))
    required_free = source_bytes + min_free_bytes
    if usage.free < required_free:
        raise RuntimeError(
            f"Refusing CocoIndex mirror: source files require {source_bytes} bytes "
            f"and the filesystem containing {context.artifact_root} has only "
            f"{usage.free} free bytes before the {min_free_bytes} byte reserve."
        )


def copy_repo_files(
    repo_root: Path,
    paths: list[PurePosixPath],
    target_root: Path,
) -> tuple[str, int]:
    """Copy repository files to a mirror while recomputing the content digest."""
    digest = hashlib.sha256()
    digest.update(f"schema:{MIRROR_SCHEMA_VERSION}\0".encode())
    copied_files = 0
    for relative_path in paths:
        path_text = relative_path.as_posix()
        digest.update(path_text.encode())
        digest.update(b"\0")
        source_path = verified_repo_source_path(repo_root, relative_path)
        if not source_path.exists():
            digest.update(b"missing\0")
            continue
        file_digest_value = hashlib.sha256()
        target = target_root / path_text
        target.parent.mkdir(parents=True, exist_ok=True)
        copied_files += 1
        with source_path.open("rb") as source, target.open("wb") as destination:
            for chunk in iter(lambda: source.read(FILE_COPY_CHUNK_BYTES), b""):
                file_digest_value.update(chunk)
                destination.write(chunk)
        digest.update(file_digest_value.digest())
        digest.update(b"\0")
    return digest.hexdigest()[:32], copied_files


def lock_path(artifact_root: Path, name: str) -> Path:
    """Return a named lock path under the artifact root."""
    locks = artifact_root / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    return locks / f"{name}.lock"


class FileLock:
    """Process lock for install and mirror creation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: TextIO | None = None

    def __enter__(self) -> "FileLock":
        self.handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def ccc_env(context: CocoIndexContext) -> dict[str, str]:
    """Return the isolated CocoIndex environment for the resolved mirror."""
    env = os.environ.copy()
    env.update(
        {
            "COCOINDEX_CODE_DIR": str(context.settings_dir),
            "COCOINDEX_CODE_RUNTIME_DIR": str(context.runtime_dir),
            "COCOINDEX_CODE_DB_PATH_MAPPING": (
                f"{context.mirror_repo.resolve()}={context.db_dir.resolve()}"
            ),
            "HF_HOME": str(context.hf_home),
            "XDG_CACHE_HOME": str(context.cache_dir),
            "PIP_CACHE_DIR": str(context.pip_cache),
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return env


def ccc_supervised_env(context: CocoIndexContext) -> dict[str, str]:
    """Return a CocoIndex env where the wrapper owns daemon startup."""
    env = ccc_env(context)
    env["COCOINDEX_CODE_DAEMON_SUPERVISED"] = "1"
    return env


def wrapper_script_arg(*, pin_repo: bool) -> str:
    """Return the script path for MCP configs without pinning checkout paths by default."""
    script_path = Path(__file__).resolve()
    if pin_repo:
        return str(script_path)
    script_repo = discover_git_root_candidate(script_path)
    return script_path.relative_to(script_repo).as_posix()


@contextmanager
def patched_process_env(env: dict[str, str]) -> Any:
    """Temporarily replace process env for imported CocoIndex helpers."""
    original = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def resolve_context(
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
    repo_root: Path | None = None,
) -> CocoIndexContext:
    """Resolve repo and artifact paths, including the current mirror digest."""
    repo_root = repo_root or resolve_repo_root()
    artifact_root = default_artifact_root()
    paths = tracked_files(repo_root, excluded_paths)
    digest = file_digest(repo_root, paths)
    return CocoIndexContext(
        repo_root=repo_root,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / digest / "repo",
        mirror_digest=digest,
    )


def resolve_mcp_handshake_context() -> CocoIndexContext:
    """Resolve only the paths needed for lightweight MCP handshake probes."""
    repo_root = resolve_repo_root()
    artifact_root = default_artifact_root()
    digest = "mcp-handshake"
    return CocoIndexContext(
        repo_root=repo_root,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / digest / "repo",
        mirror_digest=digest,
    )


def repo_active_key(repo_root: Path) -> str:
    """Return a host-local key for active-index metadata."""
    return hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()[:32]


def active_index_path(artifact_root: Path, repo_root: Path) -> Path:
    """Return the active-index metadata path for one local repository root."""
    return artifact_root / "active" / f"{repo_active_key(repo_root)}.json"


def validate_mirror_digest(value: object) -> str:
    """Validate a stored mirror digest before using it as a path component."""
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError("Active CocoIndex metadata contains an invalid digest.")
    return value


def resolve_active_index_context() -> CocoIndexContext:
    """Resolve the last explicit index for the current repo without hashing files."""
    repo_root = resolve_repo_root()
    artifact_root = default_artifact_root()
    metadata_path = active_index_path(artifact_root, repo_root)
    if not metadata_path.exists():
        raise IndexRequiredError(INDEX_REQUIRED_MESSAGE)
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Active CocoIndex metadata is invalid JSON: {metadata_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Active CocoIndex metadata must be an object: {metadata_path}"
        )
    if payload.get("schema") != ACTIVE_INDEX_SCHEMA_VERSION:
        raise RuntimeError(
            f"Active CocoIndex metadata schema is unsupported: {metadata_path}"
        )
    if payload.get("package") != PACKAGE_REQUIREMENT:
        raise RuntimeError(
            f"Active CocoIndex metadata package is stale: {metadata_path}"
        )
    if payload.get("source_repo") != str(repo_root):
        raise RuntimeError(
            f"Active CocoIndex metadata does not match this repo: {metadata_path}"
        )
    digest = validate_mirror_digest(payload.get("mirror_digest"))
    return CocoIndexContext(
        repo_root=repo_root,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / digest / "repo",
        mirror_digest=digest,
    )


def write_active_index_metadata(context: CocoIndexContext) -> None:
    """Record the latest explicit index for read-only MCP/search operations."""
    metadata_path = active_index_path(context.artifact_root, context.repo_root)
    payload = {
        "schema": ACTIVE_INDEX_SCHEMA_VERSION,
        "package": PACKAGE_REQUIREMENT,
        "source_repo": str(context.repo_root),
        "mirror_digest": context.mirror_digest,
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        metadata_path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def ensure_installed(context: CocoIndexContext) -> None:
    """Install the pinned full host package into the versioned venv."""
    require_disk_budget(context, "install")
    with FileLock(lock_path(context.artifact_root, "install")):
        if context.ccc_bin.exists():
            try:
                verify_install(context)
                return
            except RuntimeError:
                shutil.rmtree(context.venv_dir)

        context.venv_dir.parent.mkdir(parents=True, exist_ok=True)
        if context.venv_dir.exists():
            shutil.rmtree(context.venv_dir)
        venv.EnvBuilder(with_pip=True, clear=True).create(context.venv_dir)
        pip = context.venv_dir / "bin" / "python"
        install_env = os.environ.copy()
        install_env["PIP_CACHE_DIR"] = str(context.pip_cache)
        context.pip_cache.mkdir(parents=True, exist_ok=True)
        checked_command(
            [str(pip), "-m", "pip", "install", PACKAGE_REQUIREMENT],
            cwd=context.repo_root,
            env=install_env,
            timeout=timeout_seconds("install"),
        )
        verify_install(context)


def verify_install(context: CocoIndexContext) -> None:
    """Verify the pinned package and full local embedding dependency exist."""
    python = context.venv_dir / "bin" / "python"
    script = (
        "import importlib.metadata, importlib.util\n"
        f"version = importlib.metadata.version({PACKAGE_NAME!r})\n"
        f"expected = {PACKAGE_VERSION!r}\n"
        "if version != expected:\n"
        "    raise SystemExit(f'expected {expected}, found {version}')\n"
        "if importlib.util.find_spec('sentence_transformers') is None:\n"
        "    raise SystemExit('sentence_transformers is missing; full extra is not installed')\n"
        "print(version)\n"
    )
    checked_command(
        [str(python), "-c", script],
        cwd=context.repo_root,
        timeout=timeout_seconds("verify_install"),
    )
    checked_command(
        [str(context.ccc_bin), "--help"],
        cwd=context.repo_root,
        timeout=timeout_seconds("verify_install"),
    )


def ensure_mirror(
    context: CocoIndexContext,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> None:
    """Create the immutable external mirror for current Git-visible files."""
    require_disk_budget(context, "mirror")
    manifest_path = context.mirror_repo.parent / "manifest.json"
    if manifest_path.exists() and context.mirror_repo.exists():
        return

    paths = tracked_files(context.repo_root, excluded_paths)
    source_bytes = repo_visible_file_total_bytes(context.repo_root, paths)
    require_mirror_write_budget(context, source_bytes)
    digest = file_digest(context.repo_root, paths)
    if digest != context.mirror_digest:
        raise RuntimeError(
            "Repository contents changed while resolving the mirror digest."
        )

    with FileLock(lock_path(context.artifact_root, f"mirror-{context.mirror_digest}")):
        if manifest_path.exists() and context.mirror_repo.exists():
            return
        build_root = context.mirror_repo.parent / f".build-{os.getpid()}"
        if build_root.exists():
            shutil.rmtree(build_root)
        repo_build = build_root / "repo"
        repo_build.mkdir(parents=True, exist_ok=True)
        copied_digest, copied_files = copy_repo_files(
            context.repo_root, paths, repo_build
        )
        if copied_digest != context.mirror_digest:
            raise RuntimeError(
                "Repository contents changed while building the mirror copy."
            )

        if context.mirror_repo.parent.exists():
            context.mirror_repo.parent.mkdir(parents=True, exist_ok=True)
        os.replace(repo_build, context.mirror_repo)
        shutil.rmtree(build_root, ignore_errors=True)
        manifest = {
            "schema": MIRROR_SCHEMA_VERSION,
            "digest": context.mirror_digest,
            "source_repo": str(context.repo_root),
            "git_visible_non_ignored_files": len(paths),
            "mirrored_files": copied_files,
            "package": PACKAGE_REQUIREMENT,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def ensure_project_initialized(context: CocoIndexContext) -> None:
    """Initialize CocoIndex settings in the mirror, never in the live checkout."""
    settings_file = context.mirror_repo / ".cocoindex_code" / "settings.yml"
    global_settings_file = context.settings_dir / "global_settings.yml"
    if settings_file.exists() and global_settings_file.exists():
        return
    if not global_settings_file.exists():
        with FileLock(lock_path(context.artifact_root, "global-settings")):
            if not global_settings_file.exists():
                checked_command(
                    [str(context.ccc_bin), "init", "--force"],
                    cwd=context.mirror_repo,
                    env=ccc_env(context),
                    timeout=timeout_seconds("init"),
                )
                return
    with FileLock(lock_path(context.artifact_root, f"init-{context.mirror_digest}")):
        if settings_file.exists() and global_settings_file.exists():
            return
        checked_command(
            [str(context.ccc_bin), "init", "--force"],
            cwd=context.mirror_repo,
            env=ccc_env(context),
            timeout=timeout_seconds("init"),
        )


def ensure_project_settings_match_mirror(context: CocoIndexContext) -> bool:
    """Configure the mirror project to index every mirrored text file type."""
    prepend_venv_site_package_paths(context)
    settings_module = importlib.import_module("cocoindex_code.settings")
    project_settings = settings_module.load_project_settings(context.mirror_repo)
    changed = False

    include_patterns = list(MIRROR_INCLUDE_PATTERNS)
    exclude_patterns = list(MIRROR_EXCLUDE_PATTERNS)
    if project_settings.include_patterns != include_patterns:
        project_settings.include_patterns = include_patterns
        changed = True
    if project_settings.exclude_patterns != exclude_patterns:
        project_settings.exclude_patterns = exclude_patterns
        changed = True

    if changed:
        settings_module.save_project_settings(context.mirror_repo, project_settings)
    return changed


def ensure_ready(
    context: CocoIndexContext,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> None:
    """Install and prepare the external mirror."""
    ensure_installed(context)
    ensure_mirror(context, excluded_paths)
    ensure_project_initialized(context)
    ensure_project_settings_match_mirror(context)


def emit_cold_index_notice_if_needed(context: CocoIndexContext) -> None:
    """Tell the calling agent when the next index/search is expected to be cold."""
    if not target_sqlite_db(context).exists():
        print(COLD_INDEX_NOTICE, file=sys.stderr)


def repo_relative_path_if_inside(repo_root: Path, path: Path) -> PurePosixPath | None:
    """Return a safe repo-relative path when *path* is inside *repo_root*."""
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(repo_root)
    except ValueError:
        return None
    return validate_repo_relative_path(relative.as_posix())


def run_ccc(
    context: CocoIndexContext,
    args: list[str],
    timeout: int | None = None,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> subprocess.CompletedProcess[str]:
    """Run the pinned ccc executable inside the external mirror."""
    ensure_ready(context, excluded_paths)
    ensure_daemon_ready(context)
    return checked_command(
        [str(context.ccc_bin), *args],
        cwd=context.mirror_repo,
        env=ccc_supervised_env(context),
        timeout=timeout,
    )


def require_existing_search_artifacts(context: CocoIndexContext) -> None:
    """Require every artifact needed for search without creating any of them."""
    missing: list[str] = []
    if not context.ccc_bin.exists():
        missing.append(str(context.ccc_bin))
    if not context.mirror_repo.exists():
        missing.append(str(context.mirror_repo))
    if not target_sqlite_db(context).exists():
        raise IndexRequiredError(INDEX_REQUIRED_MESSAGE)
    if missing:
        raise IndexRequiredError(
            "CocoIndex search artifacts are incomplete; missing " + ", ".join(missing)
        )


def run_ccc_existing(
    context: CocoIndexContext, args: list[str], timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ccc only against already-created artifacts."""
    require_existing_search_artifacts(context)
    ensure_daemon_ready(context)
    return checked_command(
        [str(context.ccc_bin), *args],
        cwd=context.mirror_repo,
        env=ccc_supervised_env(context),
        timeout=timeout,
    )


def target_sqlite_db(context: CocoIndexContext) -> Path:
    """Return the expected external vector database path."""
    return context.db_dir / "target_sqlite.db"


def run_index(
    context: CocoIndexContext,
    *,
    allow_dirty: bool,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> str:
    """Run an explicit disk-heavy CocoIndex index operation."""
    require_clean_index_target(context.repo_root, allow_dirty=allow_dirty)
    require_disk_budget(context, "index")
    emit_cold_index_notice_if_needed(context)
    output = run_ccc(
        context,
        ["index"],
        timeout=timeout_seconds("index"),
        excluded_paths=excluded_paths,
    )
    write_active_index_metadata(context)
    return output.stdout


def unique(seq: list[str]) -> list[str]:
    """Return list items with stable first-seen uniqueness."""
    seen: set[str] = set()
    output: list[str] = []
    for item in seq:
        normalized = item[2:] if item.startswith("./") else item
        if normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def hit_rank(files: list[str], expected: list[str]) -> int | None:
    """Return the first 1-based rank that hits the expected file set."""
    expected_set = set(expected)
    for index, path in enumerate(files, 1):
        if path in expected_set:
            return index
    return None


def parse_file_hits(pattern: str, text: str) -> list[str]:
    """Parse file names from rg or ccc output."""
    import re

    return unique(re.findall(pattern, text, flags=re.MULTILINE))


def load_benchmark_cases(path: Path) -> list[BenchmarkCase]:
    """Load and validate benchmark cases from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Benchmark cases file must contain a non-empty JSON list.")
    cases: list[BenchmarkCase] = []
    for index, item in enumerate(payload, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Benchmark case {index} must be a JSON object.")
        missing = {"name", "query", "rg", "expected"} - set(item)
        if missing:
            raise RuntimeError(
                f"Benchmark case {index} is missing fields: {', '.join(sorted(missing))}"
            )
        if not all(
            isinstance(item[field], str) and item[field]
            for field in ("name", "query", "rg")
        ):
            raise RuntimeError(
                f"Benchmark case {index} name, query, and rg must be strings."
            )
        expected = item["expected"]
        if (
            not isinstance(expected, list)
            or not expected
            or not all(isinstance(value, str) and value for value in expected)
        ):
            raise RuntimeError(
                f"Benchmark case {index} expected must be a non-empty string list."
            )
        cases.append(
            BenchmarkCase(
                name=item["name"],
                query=item["query"],
                rg=item["rg"],
                expected=tuple(expected),
            )
        )
    return cases


def rg_exclude_args(excluded_paths: frozenset[PurePosixPath]) -> list[str]:
    """Return rg glob flags for benchmark exclusions."""
    return [
        flag
        for path in sorted(excluded_paths, key=str)
        for flag in ("-g", f"!{path.as_posix()}")
    ]


def run_rg_baseline(
    context: CocoIndexContext,
    rg_bin: str,
    case: BenchmarkCase,
    exclude_args: list[str],
) -> tuple[subprocess.CompletedProcess[str], float, list[str]]:
    """Run broad rg for one benchmark case."""
    start = time.perf_counter()
    result = run_command(
        [
            rg_bin,
            "-n",
            "-i",
            "--no-heading",
            *exclude_args,
            case.rg,
            ".",
        ],
        cwd=context.repo_root,
        timeout=timeout_seconds("rg"),
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms, parse_file_hits(RG_FILE_RE, result.stdout)


def run_coco_search(
    context: CocoIndexContext,
    case: BenchmarkCase,
) -> tuple[subprocess.CompletedProcess[str], float, list[str]]:
    """Run CocoIndex semantic routing for one benchmark case."""
    start = time.perf_counter()
    result = run_command(
        [str(context.ccc_bin), "search", "--limit", "5", case.query],
        cwd=context.mirror_repo,
        env=ccc_env(context),
        timeout=timeout_seconds("search"),
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"CocoIndex search failed for case {case.name}",
                    result.stdout,
                    result.stderr,
                ]
            )
        )
    return result, elapsed_ms, parse_file_hits(SEARCH_FILE_RE, result.stdout)


def empty_focused_rg_result() -> subprocess.CompletedProcess[str]:
    """Return the benchmark record for a focused rg miss."""
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")


def run_focused_rg(
    context: CocoIndexContext,
    rg_bin: str,
    case: BenchmarkCase,
    coco_files: list[str],
) -> tuple[subprocess.CompletedProcess[str], float, list[str]]:
    """Run rg only on CocoIndex candidate files."""
    start = time.perf_counter()
    existing_coco_files = [
        path for path in coco_files if (context.repo_root / path).is_file()
    ]
    if existing_coco_files:
        result = run_command(
            [
                rg_bin,
                "-n",
                "-i",
                "--no-heading",
                case.rg,
                *existing_coco_files,
            ],
            cwd=context.repo_root,
            timeout=timeout_seconds("rg"),
        )
    else:
        result = empty_focused_rg_result()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms, parse_file_hits(RG_FILE_RE, result.stdout)


def benchmark_case(
    context: CocoIndexContext,
    rg_bin: str,
    case: BenchmarkCase,
    exclude_args: list[str],
) -> BenchmarkResult:
    """Run all benchmark commands for one case."""
    rg_result, rg_ms, rg_files = run_rg_baseline(context, rg_bin, case, exclude_args)
    coco_result, coco_ms, coco_files = run_coco_search(context, case)
    focused_rg_result, focused_rg_ms, focused_rg_files = run_focused_rg(
        context, rg_bin, case, coco_files
    )
    return BenchmarkResult(
        case=case.name,
        rg_ms=round(rg_ms, 1),
        rg_returncode=rg_result.returncode,
        rg_chars=len(rg_result.stdout),
        rg_line_count=rg_result.stdout.count("\n"),
        rg_unique_files=len(rg_files),
        rg_first_files=rg_files[:5],
        rg_expected_rank=hit_rank(rg_files, list(case.expected)),
        coco_ms=round(coco_ms, 1),
        coco_chars=len(coco_result.stdout),
        coco_line_count=coco_result.stdout.count("\n"),
        coco_unique_files=len(coco_files),
        coco_first_files=coco_files[:5],
        coco_expected_rank=hit_rank(coco_files, list(case.expected)),
        focused_rg_ms=round(focused_rg_ms, 1),
        focused_rg_returncode=focused_rg_result.returncode,
        focused_rg_chars=len(focused_rg_result.stdout),
        focused_rg_line_count=focused_rg_result.stdout.count("\n"),
        focused_rg_unique_files=len(focused_rg_files),
        hybrid_chars=len(coco_result.stdout) + len(focused_rg_result.stdout),
    )


def benchmark_summary(results: list[BenchmarkResult]) -> dict[str, object]:
    """Summarize benchmark results without re-parsing JSON payload objects."""
    return {
        "cases": len(results),
        "rg_top5_hits": sum(
            result.rg_expected_rank is not None and result.rg_expected_rank <= 5
            for result in results
        ),
        "coco_top5_hits": sum(
            result.coco_expected_rank is not None and result.coco_expected_rank <= 5
            for result in results
        ),
        "rg_total_chars": sum(result.rg_chars for result in results),
        "coco_total_chars": sum(result.coco_chars for result in results),
        "focused_rg_total_chars": sum(result.focused_rg_chars for result in results),
        "hybrid_total_chars": sum(result.hybrid_chars for result in results),
        "rg_avg_ms": round(sum(result.rg_ms for result in results) / len(results), 1),
        "coco_avg_ms": round(
            sum(result.coco_ms for result in results) / len(results), 1
        ),
        "focused_rg_avg_ms": round(
            sum(result.focused_rg_ms for result in results) / len(results), 1
        ),
        "rg_total_unique_file_mentions": sum(
            result.rg_unique_files for result in results
        ),
        "coco_total_unique_file_mentions": sum(
            result.coco_unique_files for result in results
        ),
    }


def run_benchmark(
    context: CocoIndexContext,
    cases: list[BenchmarkCase],
    output_path: Path | None,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
    *,
    allow_dirty: bool = False,
) -> dict[str, object]:
    """Run the reproducible hybrid search benchmark."""
    require_clean_index_target(context.repo_root, allow_dirty=allow_dirty)
    require_disk_budget(context, "benchmark")
    ensure_installed(context)
    ensure_mirror(context, excluded_paths)
    ensure_project_initialized(context)
    index_start = time.perf_counter()
    run_index(context, allow_dirty=allow_dirty, excluded_paths=excluded_paths)
    index_elapsed = time.perf_counter() - index_start

    rg_bin = resolve_required_executable("rg")
    results = [
        benchmark_case(context, rg_bin, case, rg_exclude_args(excluded_paths))
        for case in cases
    ]

    payload = {
        "benchmark_schema": 1,
        "package": PACKAGE_REQUIREMENT,
        "repo_head": checked_git_command(
            context.repo_root,
            ["rev-parse", "HEAD"],
        ).stdout.strip(),
        "mirror_digest": context.mirror_digest,
        "benchmark_excluded_paths": [
            path.as_posix() for path in sorted(excluded_paths, key=str)
        ],
        "index_elapsed_seconds": round(index_elapsed, 2),
        "index_db_bytes": target_sqlite_db(context).stat().st_size,
        "results": [result.as_payload() for result in results],
        "summary": benchmark_summary(results),
    }
    if output_path is not None:
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def command_install(_args: argparse.Namespace) -> None:
    context = resolve_mcp_handshake_context()
    ensure_installed(context)
    print(f"installed {PACKAGE_REQUIREMENT} at {context.venv_dir}")


def command_prepare(args: argparse.Namespace) -> None:
    allow_dirty = getattr(args, "allow_dirty_mirror", False)
    repo_root = resolve_repo_root()
    require_clean_index_target(repo_root, allow_dirty=allow_dirty)
    context = resolve_context(repo_root=repo_root)
    ensure_ready(context)
    print(
        json.dumps(
            {"mirror_repo": str(context.mirror_repo), "digest": context.mirror_digest},
            sort_keys=True,
        )
    )


def command_index(args: argparse.Namespace) -> None:
    allow_dirty = getattr(args, "allow_dirty_index", False)
    repo_root = resolve_repo_root()
    require_clean_index_target(repo_root, allow_dirty=allow_dirty)
    context = resolve_context(repo_root=repo_root)
    output = run_index(context, allow_dirty=allow_dirty)
    print(output, end="")


def command_search(args: argparse.Namespace) -> None:
    allow_dirty = getattr(args, "allow_dirty_index", False)
    if getattr(args, "refresh", False) or getattr(args, "index_if_missing", False):
        repo_root = resolve_repo_root()
        require_clean_index_target(repo_root, allow_dirty=allow_dirty)
        context = resolve_context(repo_root=repo_root)
    else:
        context = resolve_active_index_context()
    output = run_search(
        context,
        query=args.query,
        limit=args.limit,
        path=args.path,
        langs=args.lang,
        refresh=args.refresh,
        allow_index=getattr(args, "index_if_missing", False),
        allow_dirty=allow_dirty,
    )
    print(output, end="")


def run_search(
    context: CocoIndexContext,
    *,
    query: list[str],
    limit: int,
    path: str | None,
    langs: list[str],
    refresh: bool,
    allow_index: bool,
    allow_dirty: bool = False,
) -> str:
    """Run a CocoIndex Code search and return the rendered search output."""
    if refresh:
        run_index(context, allow_dirty=allow_dirty)
    elif not target_sqlite_db(context).exists():
        if not allow_index:
            raise IndexRequiredError(INDEX_REQUIRED_MESSAGE)
        run_index(context, allow_dirty=allow_dirty)
    ccc_args = ["search", "--limit", str(limit)]
    if path:
        ccc_args.extend(["--path", path])
    for lang in langs:
        ccc_args.extend(["--lang", lang])
    ccc_args.extend(query)
    output = run_ccc_existing(context, ccc_args, timeout=timeout_seconds("search"))
    return output.stdout


def command_status(_args: argparse.Namespace) -> None:
    context = resolve_active_index_context()
    output = run_ccc_existing(context, ["status"], timeout=timeout_seconds("status"))
    print(output.stdout, end="")


def mcp_search_tool_definition() -> dict[str, object]:
    """Return the lightweight MCP search tool definition."""
    return {
        "name": MCP_SEARCH_TOOL_NAME,
        "description": (
            "Search the target Git repository with the pinned CocoIndex Code "
            "semantic index. The MCP tool never installs, mirrors, refreshes, "
            "or builds an index; run the CLI index command explicitly first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 5,
                    "description": "Maximum number of search results.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional repository-relative glob filter.",
                },
                "lang": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional CocoIndex language filters.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def mcp_initialize_result(params: object) -> dict[str, object]:
    """Return an MCP initialize result without touching CocoIndex runtime state."""
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    protocol_version = (
        requested if requested in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[-1]
    )
    return {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": MCP_SERVER_NAME, "version": PACKAGE_VERSION},
    }


def mcp_positive_int(value: object, field: str, default: int) -> int:
    """Validate a positive JSON integer parameter."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonRpcError(-32602, f"{field} must be a positive integer.")
    return value


def mcp_optional_string(value: object, field: str) -> str | None:
    """Validate an optional JSON string parameter."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise JsonRpcError(-32602, f"{field} must be a non-empty string.")
    return value


def mcp_string_list(value: object, field: str) -> list[str]:
    """Validate an optional JSON string-list parameter."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise JsonRpcError(-32602, f"{field} must be a list of non-empty strings.")
    return value


def mcp_search_arguments(arguments: object) -> dict[str, object]:
    """Validate MCP search tool arguments."""
    if not isinstance(arguments, dict):
        raise JsonRpcError(-32602, "search arguments must be an object.")
    query = arguments.get("query")
    if not isinstance(query, str) or not query:
        raise JsonRpcError(-32602, "query must be a non-empty string.")
    if "refresh_index" in arguments:
        raise JsonRpcError(
            -32602,
            "refresh_index is not supported by MCP; run the CLI index command explicitly.",
        )
    return {
        "query": query,
        "limit": mcp_positive_int(arguments.get("limit"), "limit", 5),
        "path": mcp_optional_string(arguments.get("path"), "path"),
        "langs": mcp_string_list(arguments.get("lang"), "lang"),
    }


def run_mcp_search_tool(arguments: object) -> str:
    """Run the MCP search tool without building or refreshing an index."""
    parsed = mcp_search_arguments(arguments)
    context: CocoIndexContext | None = None
    try:
        context = resolve_active_index_context()
        return run_search(
            context,
            query=[cast(str, parsed["query"])],
            limit=cast(int, parsed["limit"]),
            path=cast(str | None, parsed["path"]),
            langs=cast(list[str], parsed["langs"]),
            refresh=False,
            allow_index=False,
        )
    except RuntimeError as exc:
        raise RuntimeError(sanitize_mcp_error_text(str(exc), context)) from exc


def sanitize_mcp_error_text(
    message: str,
    context: CocoIndexContext | None = None,
) -> str:
    """Redact local host paths from MCP-visible error text."""
    replacements: dict[str, str] = {}

    def add_path(path: Path, label: str) -> None:
        try:
            paths = {str(path.expanduser()), str(path.expanduser().resolve())}
        except OSError:
            paths = {str(path)}
        for candidate in paths:
            if candidate and candidate != "/":
                replacements[candidate] = label

    if context is not None:
        add_path(context.artifact_root, f"${ARTIFACT_ROOT_ENV}")
        add_path(context.repo_root, f"${REPO_ROOT_ENV}")
    add_path(Path.home(), "$HOME")
    try:
        add_path(default_artifact_root(), f"${ARTIFACT_ROOT_ENV}")
    except RuntimeError:
        LOGGER.debug("Could not resolve CocoIndex artifact root for redaction.")
    try:
        add_path(resolve_repo_root(), f"${REPO_ROOT_ENV}")
    except RuntimeError:
        LOGGER.debug("Could not resolve repository root for redaction.")

    redacted = message
    for path, label in sorted(
        replacements.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        redacted = redacted.replace(path, label)
    return redacted


def write_jsonrpc_message(output_stream: TextIO, payload: dict[str, object]) -> None:
    """Write one newline-delimited JSON-RPC payload to stdout."""
    output_stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    output_stream.flush()


def write_jsonrpc_result(
    output_stream: TextIO, request_id: object, result: dict[str, object]
) -> None:
    """Write one successful JSON-RPC response."""
    write_jsonrpc_message(
        output_stream,
        {"jsonrpc": MCP_JSONRPC_VERSION, "id": request_id, "result": result},
    )


def write_jsonrpc_error(
    output_stream: TextIO, request_id: object, code: int, message: str
) -> None:
    """Write one JSON-RPC error response."""
    write_jsonrpc_message(
        output_stream,
        {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        },
    )


def mcp_tool_call_result(params: object) -> dict[str, object]:
    """Handle one MCP tools/call request."""
    if not isinstance(params, dict):
        raise JsonRpcError(-32602, "tools/call params must be an object.")
    name = params.get("name")
    if name != MCP_SEARCH_TOOL_NAME:
        raise JsonRpcError(-32602, "Unknown MCP tool.")
    try:
        text = run_mcp_search_tool(params.get("arguments", {}))
    except JsonRpcError:
        raise
    except RuntimeError as exc:
        return {
            "content": [{"type": "text", "text": f"CocoIndex search failed: {exc}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle_mcp_request(message: dict[str, object]) -> dict[str, object] | None:
    """Return an MCP result for a JSON-RPC request or None for notifications."""
    request_id = message.get("id")
    if request_id is None:
        return None
    method = message.get("method")
    if method == "initialize":
        return mcp_initialize_result(message.get("params", {}))
    if method == "tools/list":
        return {"tools": [mcp_search_tool_definition()]}
    if method == "tools/call":
        return mcp_tool_call_result(message.get("params", {}))
    if method == "ping":
        return {}
    raise JsonRpcError(-32601, f"Method not found: {method!r}.")


def run_lightweight_mcp_server(
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> None:
    """Run a fast-start stdio MCP server without pre-indexing the repository."""
    for raw_line in input_stream:
        if not raw_line.strip():
            continue
        request_id: object = None
        has_request_id = False
        try:
            message = json.loads(raw_line)
            if not isinstance(message, dict):
                raise JsonRpcError(-32600, "JSON-RPC message must be an object.")
            has_request_id = "id" in message
            request_id = message.get("id")
            result = handle_mcp_request(message)
            if has_request_id and result is not None:
                write_jsonrpc_result(output_stream, request_id, result)
        except json.JSONDecodeError:
            write_jsonrpc_error(output_stream, request_id, -32700, "Parse error.")
        except JsonRpcError as exc:
            if has_request_id:
                write_jsonrpc_error(output_stream, request_id, exc.code, exc.message)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if has_request_id:
                write_jsonrpc_error(output_stream, request_id, -32000, str(exc))


def command_mcp(_args: argparse.Namespace) -> None:
    run_lightweight_mcp_server()


def venv_site_package_paths(context: CocoIndexContext) -> list[Path]:
    """Return import paths for the pinned venv packages."""
    site_packages = sorted((context.venv_dir / "lib").glob("python*/site-packages"))
    if not site_packages:
        raise RuntimeError(f"Could not find site-packages under {context.venv_dir}")
    return site_packages


def prepend_venv_site_package_paths(context: CocoIndexContext) -> None:
    """Make pinned venv packages importable without duplicating sys.path."""
    for site_package_path in reversed(venv_site_package_paths(context)):
        site_path = str(site_package_path)
        if site_path not in sys.path:
            sys.path.insert(0, site_path)


def daemon_log_path(context: CocoIndexContext) -> Path:
    """Return this wrapper's CocoIndex daemon log path."""
    return context.runtime_dir / "daemon.log"


def read_daemon_log(context: CocoIndexContext) -> str:
    """Return the daemon log for diagnostics, if present."""
    try:
        return daemon_log_path(context).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def daemon_handshake_succeeds(context: CocoIndexContext) -> bool:
    """Return whether the current runtime daemon accepts a version handshake."""
    prepend_venv_site_package_paths(context)
    with patched_process_env(ccc_env(context)):
        cocoindex_module = importlib.import_module("cocoindex_code")
        client_module = importlib.import_module("cocoindex_code.client")
        try:
            socket_path = cast(Any, client_module).daemon_socket_path()
            if sys.platform != "win32" and not os.path.exists(socket_path):
                return False
            conn = cast(Any, client_module).Client(
                socket_path,
                family=cast(Any, client_module).connection_family(),
            )
            try:
                request = cast(Any, client_module).HandshakeRequest(
                    version=cast(Any, cocoindex_module).__version__
                )
                conn.send_bytes(cast(Any, client_module).encode_request(request))
                response = cast(Any, client_module).decode_response(conn.recv_bytes())
            finally:
                conn.close()
        except (EOFError, OSError, RuntimeError):
            return False
    return (
        isinstance(response, cast(Any, client_module).HandshakeResponse)
        and response.ok
        and response.daemon_version == cast(Any, cocoindex_module).__version__
    )


def start_daemon_process(context: CocoIndexContext) -> subprocess.Popen[bytes]:
    """Start the pinned CocoIndex daemon for this mirror."""
    context.runtime_dir.mkdir(parents=True, exist_ok=True)
    log_handle = daemon_log_path(context).open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            [str(context.ccc_bin), "run-daemon"],
            cwd=context.mirror_repo,
            env=ccc_env(context),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start CocoIndex daemon: {exc}") from exc
    finally:
        log_handle.close()


def wait_for_daemon_handshake(
    context: CocoIndexContext, proc: subprocess.Popen[bytes]
) -> None:
    """Wait until the daemon completes a real client handshake."""
    deadline = time.monotonic() + timeout_seconds("mcp_smoke")
    while time.monotonic() < deadline:
        if daemon_handshake_succeeds(context):
            return
        if proc.poll() is not None:
            log = read_daemon_log(context)
            message = "CocoIndex daemon exited before it accepted a handshake."
            if log:
                message += f"\n\nDaemon log:\n{log}"
            raise RuntimeError(message)
        time.sleep(0.2)

    log = read_daemon_log(context)
    message = "CocoIndex daemon did not accept a handshake in time."
    if log:
        message += f"\n\nDaemon log:\n{log}"
    raise RuntimeError(message)


def cleanup_stale_daemon_files(context: CocoIndexContext) -> None:
    """Remove stale same-runtime socket files after handshake failure."""
    for path in (
        context.runtime_dir / "daemon.sock",
        context.runtime_dir / "daemon.pid",
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            LOGGER.debug(
                "Could not remove stale CocoIndex daemon runtime file.",
                exc_info=True,
            )


def ensure_daemon_ready(context: CocoIndexContext) -> None:
    """Start exactly one ready daemon for this repository mirror."""
    with FileLock(lock_path(context.artifact_root, f"daemon-{context.mirror_digest}")):
        if daemon_handshake_succeeds(context):
            return
        cleanup_stale_daemon_files(context)
        proc = start_daemon_process(context)
        wait_for_daemon_handshake(context, proc)


def mcp_config_payload(
    context: CocoIndexContext, *, pin_repo: bool
) -> dict[str, object]:
    """Return a stdio MCP configuration contract for any compatible agent."""
    env = {ARTIFACT_ROOT_ENV: str(context.artifact_root)}
    if pin_repo:
        env[REPO_ROOT_ENV] = str(context.repo_root)
    payload: dict[str, object] = {
        "name": MCP_SERVER_NAME,
        "transport": "stdio",
        "command": MCP_PYTHON_COMMAND,
        "args": [wrapper_script_arg(pin_repo=pin_repo), "mcp"],
        "env": env,
        "startup_timeout_sec": MCP_STARTUP_TIMEOUT_SECONDS,
        "tool_timeout_sec": MCP_TOOL_TIMEOUT_SECONDS,
        "working_directory_contract": (
            f"Launch from the target Git repository root or set {REPO_ROOT_ENV} "
            "to that root. The shared install stays under "
            f"{ARTIFACT_ROOT_ENV} or the XDG data default; each repository gets "
            "its own content-digest mirror, database, and runtime directory."
        ),
    }
    return payload


def command_mcp_config(args: argparse.Namespace) -> None:
    context = resolve_mcp_handshake_context()
    print(json.dumps(mcp_config_payload(context, pin_repo=args.pin_repo), indent=2))


def codex_config_path() -> Path:
    """Return the Codex config path for the active host account."""
    codex_home = os.environ.get("CODEX_HOME")
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return root / "config.toml"


def expected_codex_mcp_server(context: CocoIndexContext) -> dict[str, object]:
    """Return the expected Codex MCP server table for this wrapper."""
    return {
        "command": MCP_PYTHON_COMMAND,
        "args": [wrapper_script_arg(pin_repo=False), "mcp"],
        "env": {ARTIFACT_ROOT_ENV: str(context.artifact_root)},
        "startup_timeout_sec": MCP_STARTUP_TIMEOUT_SECONDS,
        "tool_timeout_sec": MCP_TOOL_TIMEOUT_SECONDS,
    }


def load_codex_config(path: Path) -> dict[str, Any]:
    """Load a Codex TOML config file without printing its contents."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Could not parse Codex config at {path}: {exc}") from exc


def codex_mcp_server_matches_expected(
    config: dict[str, Any], expected: dict[str, object]
) -> bool:
    """Return whether the configured Codex server matches this wrapper."""
    server = config.get("mcp_servers", {}).get(MCP_SERVER_NAME)
    if not isinstance(server, dict):
        return False
    env = server.get("env")
    expected_env = expected["env"]
    if not isinstance(env, dict) or not isinstance(expected_env, dict):
        return False
    return (
        server.get("command") == expected["command"]
        and server.get("args") == expected["args"]
        and "cwd" not in server
        and env.get(ARTIFACT_ROOT_ENV) == expected_env[ARTIFACT_ROOT_ENV]
        and server.get("startup_timeout_sec") == expected["startup_timeout_sec"]
        and server.get("tool_timeout_sec") == expected["tool_timeout_sec"]
    )


def format_toml_scalar(value: int | float | bool | str) -> str:
    """Format the scalar values this tool writes to Codex config."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value)


def format_toml_assignment(key: str, value: int | float | bool | str) -> str:
    """Format one TOML assignment line."""
    return f"{key} = {format_toml_scalar(value)}\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace a text file in its own directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def find_toml_table_bounds(lines: list[str], table_name: str) -> tuple[int, int] | None:
    """Return start/end indexes for a TOML table."""
    header = f"[{table_name}]"
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == header),
        None,
    )
    if start is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    return start, end


def matching_toml_key(line: str, keys: tuple[str, ...]) -> str | None:
    """Return the configured scalar key assigned by a TOML line."""
    stripped = line.lstrip()
    return next((key for key in keys if stripped.startswith(f"{key} =")), None)


def update_toml_table_lines(
    lines: list[str], values: Mapping[str, int | float | bool | str]
) -> list[str]:
    """Return TOML table body lines with scalar values upserted."""
    keys = tuple(values)
    rendered = {
        key: format_toml_assignment(key, value) for key, value in values.items()
    }
    seen: set[str] = set()
    updated: list[str] = []
    for line in lines:
        key = matching_toml_key(line, keys)
        if key is None:
            updated.append(line)
            continue
        updated.append(rendered[key])
        seen.add(key)
    updated.extend(rendered[key] for key in keys if key not in seen)
    return updated


def append_toml_table(
    text: str, table_name: str, values: Mapping[str, int | float | bool | str]
) -> str:
    """Append a TOML table containing scalar assignments."""
    prefix = "" if not text or text.endswith("\n") else "\n"
    body = "".join(format_toml_assignment(key, value) for key, value in values.items())
    return f"{text}{prefix}[{table_name}]\n{body}"


def upsert_toml_table_scalars(
    text: str, table_name: str, values: Mapping[str, int | float | bool | str]
) -> str:
    """Set scalar keys in one TOML table while preserving other content."""
    lines = text.splitlines(keepends=True)
    newline = "\n" if text.endswith("\n") or not text else ""
    bounds = find_toml_table_bounds(lines, table_name)
    if bounds is None:
        return append_toml_table(text, table_name, values)

    start, end = bounds
    updated = (
        lines[: start + 1]
        + update_toml_table_lines(lines[start + 1 : end], values)
        + lines[end:]
    )
    output = "".join(updated)
    return output if output.endswith("\n") else output + newline


def ensure_codex_mcp_timeouts(config_path: Path) -> None:
    """Ensure Codex has generous timeouts for the CocoIndex MCP server."""
    values = {
        "startup_timeout_sec": MCP_STARTUP_TIMEOUT_SECONDS,
        "tool_timeout_sec": MCP_TOOL_TIMEOUT_SECONDS,
    }
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated = upsert_toml_table_scalars(
        original, f"mcp_servers.{MCP_SERVER_NAME}", values
    )
    if updated != original:
        atomic_write_text(config_path, updated)


def command_mcp_install(_args: argparse.Namespace) -> None:
    context = resolve_mcp_handshake_context()
    codex = resolve_required_executable("codex")
    config_path = codex_config_path()
    expected = expected_codex_mcp_server(context)
    existing = run_command(
        [codex, "mcp", "get", MCP_SERVER_NAME], cwd=context.repo_root
    )
    if existing.returncode == 0:
        config = load_codex_config(config_path)
        if codex_mcp_server_matches_expected(config, expected):
            print(f"MCP server already configured: {MCP_SERVER_NAME}")
            return
        checked_command(
            [codex, "mcp", "remove", MCP_SERVER_NAME],
            cwd=context.repo_root,
        )
    else:
        combined_output = f"{existing.stdout}\n{existing.stderr}"
        if f"No MCP server named '{MCP_SERVER_NAME}' found" not in combined_output:
            raise RuntimeError(combined_output.strip())
    checked_command(
        [
            codex,
            "mcp",
            "add",
            "--env",
            f"{ARTIFACT_ROOT_ENV}={context.artifact_root}",
            MCP_SERVER_NAME,
            "--",
            MCP_PYTHON_COMMAND,
            wrapper_script_arg(pin_repo=False),
            "mcp",
        ],
        cwd=context.repo_root,
    )
    ensure_codex_mcp_timeouts(config_path)
    print(f"MCP server configured: {MCP_SERVER_NAME}")


def run_mcp_stdio_smoke(
    context: CocoIndexContext,
    *,
    include_search: bool,
) -> dict[str, object]:
    """Run a real MCP initialize/list_tools probe against this wrapper."""
    prepend_venv_site_package_paths(context)
    anyio_module = importlib.import_module("anyio")
    mcp_module = importlib.import_module("mcp")
    stdio_module = importlib.import_module("mcp.client.stdio")
    client_session = cast(Any, mcp_module).ClientSession
    server_parameters = cast(Any, mcp_module).StdioServerParameters
    stdio_client = cast(Any, stdio_module).stdio_client

    async def probe() -> dict[str, object]:
        params = server_parameters(
            command=sys.executable,
            args=[str(Path(__file__).resolve()), "mcp"],
            env={ARTIFACT_ROOT_ENV: str(context.artifact_root)},
            cwd=str(context.repo_root),
        )
        with cast(Any, anyio_module).fail_after(timeout_seconds("mcp_smoke")):
            async with (
                stdio_client(params) as (read_stream, write_stream),
                client_session(read_stream, write_stream) as session,
            ):
                initialized = await session.initialize()
                tools = await session.list_tools()
                search_result_type = None
                if include_search:
                    search = await session.call_tool(
                        "search",
                        {"query": "MCP smoke search", "limit": 1},
                    )
                    search_result_type = type(search).__name__
        server_info = initialized.serverInfo
        result = {
            "server_name": server_info.name,
            "server_version": server_info.version,
            "tools": sorted(tool.name for tool in tools.tools),
        }
        if include_search:
            result["search_tool_result_type"] = search_result_type
        return result

    return cast(dict[str, object], cast(Any, anyio_module).run(probe))


def parse_mcp_response_lines(stdout: str) -> dict[int, dict[str, Any]]:
    """Parse JSON-RPC responses by integer id from stdio output."""
    responses: dict[int, dict[str, Any]] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MCP server emitted non-JSON stdout: {line!r}") from exc
        response_id = payload.get("id")
        if isinstance(response_id, int):
            responses[response_id] = payload
    return responses


def run_mcp_jsonrpc_protocol_probe_once(
    context: CocoIndexContext, protocol_version: str
) -> dict[str, object]:
    """Probe newline-delimited MCP JSON-RPC without retries."""
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "cocoindex-agent-search-smoke",
                    "version": "1",
                },
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    completed = run_command_with_input(
        [sys.executable, str(Path(__file__).resolve()), "mcp"],
        cwd=context.repo_root,
        env={ARTIFACT_ROOT_ENV: str(context.artifact_root)},
        input_text="".join(json.dumps(message) + "\n" for message in messages),
        timeout=timeout_seconds("mcp_smoke"),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"MCP protocol probe failed with exit {completed.returncode}",
                    "STDOUT:",
                    completed.stdout,
                    "STDERR:",
                    completed.stderr,
                ]
            )
        )
    responses = parse_mcp_response_lines(completed.stdout)
    initialize = responses.get(1, {})
    tools_list = responses.get(2, {})
    initialize_result = initialize.get("result", {})
    if not isinstance(initialize_result, dict):
        raise RuntimeError(f"MCP initialize did not return a result: {initialize}")
    negotiated_protocol = initialize_result.get("protocolVersion")
    if negotiated_protocol not in MCP_PROTOCOL_VERSIONS:
        raise RuntimeError(
            f"MCP initialize returned unsupported protocolVersion {negotiated_protocol!r}."
        )
    tools_result = tools_list.get("result", {})
    if not isinstance(tools_result, dict):
        raise RuntimeError(f"MCP tools/list did not return a result: {tools_list}")
    tool_names = sorted(
        tool["name"]
        for tool in tools_result.get("tools", [])
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    )
    if "search" not in tool_names:
        raise McpSearchToolUnavailable(
            f"MCP tools/list did not include search: {tool_names}"
        )
    return {
        "protocol_version": protocol_version,
        "negotiated_protocol_version": negotiated_protocol,
        "tools": tool_names,
    }


def run_mcp_jsonrpc_protocol_probe(
    context: CocoIndexContext, protocol_version: str
) -> dict[str, object]:
    """Probe raw MCP JSON-RPC, retrying only transient empty tool lists."""
    last_error: McpSearchToolUnavailable | None = None
    for attempt in range(MCP_PROTOCOL_PROBE_ATTEMPTS):
        try:
            return run_mcp_jsonrpc_protocol_probe_once(context, protocol_version)
        except McpSearchToolUnavailable as exc:
            last_error = exc
            if attempt + 1 < MCP_PROTOCOL_PROBE_ATTEMPTS:
                time.sleep(MCP_PROTOCOL_PROBE_RETRY_DELAY_SECONDS)

    if last_error is not None:
        raise last_error
    raise RuntimeError("MCP raw protocol probe did not run.")


def run_mcp_jsonrpc_smoke(context: CocoIndexContext) -> list[dict[str, object]]:
    """Probe supported MCP protocol versions using raw stdio JSON-RPC."""
    return [
        run_mcp_jsonrpc_protocol_probe(context, protocol_version)
        for protocol_version in MCP_PROTOCOL_VERSIONS
    ]


def command_mcp_smoke(args: argparse.Namespace) -> None:
    payload: dict[str, object] = {}
    handshake_context = resolve_mcp_handshake_context()
    payload["stdio_probe"] = run_mcp_stdio_smoke(
        handshake_context,
        include_search=False,
    )
    payload["jsonrpc_protocol_probes"] = run_mcp_jsonrpc_smoke(handshake_context)
    if args.include_search:
        search_context = resolve_active_index_context()
        payload["stdio_search_probe"] = run_mcp_stdio_smoke(
            search_context,
            include_search=True,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_benchmark(args: argparse.Namespace) -> None:
    repo_root = resolve_repo_root()
    allow_dirty = args.allow_dirty_index
    require_clean_index_target(repo_root, allow_dirty=allow_dirty)
    excluded_paths = frozenset(
        path
        for path in [repo_relative_path_if_inside(repo_root, args.cases)]
        if path is not None
    )
    context = resolve_context(excluded_paths, repo_root=repo_root)
    payload = run_benchmark(
        context,
        load_benchmark_cases(args.cases),
        args.output,
        excluded_paths,
        allow_dirty=allow_dirty,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install and run the pinned host-side CocoIndex Code workflow against "
            "an external Git-visible non-ignored file mirror of this repository."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install", help="Install the pinned full host package."
    )
    install.set_defaults(func=command_install)

    prepare = subparsers.add_parser(
        "prepare", help="Create the external Git-visible non-ignored file mirror."
    )
    prepare.add_argument(
        "--allow-dirty-mirror",
        action="store_true",
        help="Allow mirroring the current dirty worktree digest.",
    )
    prepare.set_defaults(func=command_prepare)

    index = subparsers.add_parser("index", help="Build or refresh the semantic index.")
    index.add_argument(
        "--allow-dirty-index",
        action="store_true",
        help="Allow indexing the current dirty worktree digest.",
    )
    index.set_defaults(func=command_index)

    search = subparsers.add_parser("search", help="Search the semantic index.")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--path", help="Optional CocoIndex file path glob.")
    search.add_argument("--lang", action="append", default=[])
    search.add_argument(
        "--index-if-missing",
        action="store_true",
        help="Build the semantic index if it is missing for this repository digest.",
    )
    search.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly refresh the semantic index before searching.",
    )
    search.add_argument(
        "--allow-dirty-index",
        action="store_true",
        help="Allow indexing the current dirty worktree digest.",
    )
    search.add_argument("query", nargs="+")
    search.set_defaults(func=command_search)

    status = subparsers.add_parser("status", help="Show CocoIndex project status.")
    status.set_defaults(func=command_status)

    mcp = subparsers.add_parser("mcp", help="Run the CocoIndex Code MCP server.")
    mcp.set_defaults(func=command_mcp)

    mcp_config = subparsers.add_parser(
        "mcp-config",
        help="Print a generic stdio MCP configuration for any compatible agent.",
    )
    mcp_config.add_argument(
        "--pin-repo",
        action="store_true",
        help=(
            f"Include {REPO_ROOT_ENV} for clients that cannot launch from the "
            "target repository working directory."
        ),
    )
    mcp_config.set_defaults(func=command_mcp_config)

    mcp_install = subparsers.add_parser(
        "mcp-install",
        help="Idempotently register the Codex MCP server as cocoindex-code.",
    )
    mcp_install.set_defaults(func=command_mcp_install)

    mcp_smoke = subparsers.add_parser(
        "mcp-smoke",
        help="Launch this MCP server and verify initialize/list_tools.",
    )
    mcp_smoke.add_argument(
        "--include-search",
        action="store_true",
        help=(
            "Also call the MCP search tool against the existing semantic index. "
            "This refuses to build or refresh the index."
        ),
    )
    mcp_smoke.set_defaults(func=command_mcp_smoke)

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Run the reproducible rg-vs-CocoIndex routing benchmark.",
    )
    benchmark.add_argument("--cases", type=Path, required=True)
    benchmark.add_argument("--output", type=Path)
    benchmark.add_argument(
        "--allow-dirty-index",
        action="store_true",
        help="Allow benchmarking the current dirty worktree digest.",
    )
    benchmark.set_defaults(func=command_benchmark)

    return parser


def main() -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
