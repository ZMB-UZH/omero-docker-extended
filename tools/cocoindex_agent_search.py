#!/usr/bin/env python3
"""Host-side CocoIndex Code workflow for AI-agent semantic routing."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


PACKAGE_NAME = "cocoindex-code"
PACKAGE_VERSION = "0.2.31"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}[full]=={PACKAGE_VERSION}"
PACKAGE_WHEEL_SHA256 = (
    "bcaf341035901bf8d66491ce1a72d97d60e1ce6147d1187f1a2ee9377b189cf7"
)
PACKAGE_SDIST_SHA256 = (
    "19bf4cbb7c94801b1108ae742fccefc73b103b99ba4668868dbba10e3fb68b02"
)
MCP_SERVER_NAME = "cocoindex-code"
ARTIFACT_ROOT_ENV = "AGENT_COCOINDEX_HOME"
REPO_ROOT_ENV = "AGENT_COCOINDEX_REPO"
TIMEOUT_ENV_PREFIX = "AGENT_COCOINDEX_TIMEOUT_"
MIRROR_SCHEMA_VERSION = "1"
DENIED_MIRROR_BASENAMES = frozenset({".env"})
DENIED_MIRROR_SUFFIXES = (".env",)
DENIED_MIRROR_PARTS = frozenset({".codex", ".cocoindex_code"})
DEFAULT_TIMEOUTS_SECONDS = {
    "install": 7200,
    "verify_install": 300,
    "init": 1800,
    "index": 14400,
    "search": 600,
    "status": 600,
    "rg": 600,
}

SEARCH_FILE_RE = r"^File: (.*?):\d+(?:-\d+)? "
RG_FILE_RE = r"^(?:\./)?([^:\n]+):\d+:"


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


def resolve_repo_root() -> Path:
    """Resolve the repository root from env or the current Git checkout."""
    override = os.environ.get(REPO_ROOT_ENV)
    if override:
        candidate = Path(override).expanduser().resolve()
        completed = checked_command(
            [resolve_required_executable("git"), "rev-parse", "--show-toplevel"],
            cwd=candidate,
        )
        resolved = Path(completed.stdout.strip()).resolve()
        if resolved != candidate:
            raise RuntimeError(
                f"{REPO_ROOT_ENV} must point at the Git repository root: {candidate}"
            )
        return resolved
    completed = checked_command(
        [resolve_required_executable("git"), "rev-parse", "--show-toplevel"],
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
    completed = checked_command(
        [
            resolve_required_executable("git"),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo_root,
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


def file_digest_and_mirror_source(
    repo_root: Path, paths: list[PurePosixPath]
) -> tuple[str, dict[str, bytes]]:
    """Hash tracked file contents and keep bytes for a matching mirror copy."""
    digest = hashlib.sha256()
    digest.update(f"schema:{MIRROR_SCHEMA_VERSION}\0".encode())
    files: dict[str, bytes] = {}
    for relative_path in paths:
        path_text = relative_path.as_posix()
        source_path = repo_root / Path(relative_path)
        digest.update(path_text.encode())
        digest.update(b"\0")
        if not source_path.exists():
            digest.update(b"missing\0")
            continue
        if source_path.is_symlink():
            raise RuntimeError(f"Refusing to mirror tracked symlink: {path_text}")
        resolved = source_path.resolve()
        if not resolved.is_relative_to(repo_root):
            raise RuntimeError(f"Tracked path escapes repository root: {path_text}")
        payload = source_path.read_bytes()
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\0")
        files[path_text] = payload
    return digest.hexdigest()[:32], files


def lock_path(artifact_root: Path, name: str) -> Path:
    """Return a named lock path under the artifact root."""
    locks = artifact_root / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    return locks / f"{name}.lock"


class FileLock:
    """Process lock for install and mirror creation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> None:
        self.handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)

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


def resolve_context(
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> CocoIndexContext:
    """Resolve repo and artifact paths, including the current mirror digest."""
    repo_root = resolve_repo_root()
    artifact_root = default_artifact_root()
    paths = tracked_files(repo_root, excluded_paths)
    digest, _files = file_digest_and_mirror_source(repo_root, paths)
    return CocoIndexContext(
        repo_root=repo_root,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / digest / "repo",
        mirror_digest=digest,
    )


def ensure_installed(context: CocoIndexContext) -> None:
    """Install the pinned full host package into the versioned venv."""
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
    manifest_path = context.mirror_repo.parent / "manifest.json"
    if manifest_path.exists() and context.mirror_repo.exists():
        return

    paths = tracked_files(context.repo_root, excluded_paths)
    digest, files = file_digest_and_mirror_source(context.repo_root, paths)
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
        for path_text, payload in files.items():
            target = repo_build / path_text
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        if context.mirror_repo.parent.exists():
            context.mirror_repo.parent.mkdir(parents=True, exist_ok=True)
        os.replace(repo_build, context.mirror_repo)
        shutil.rmtree(build_root, ignore_errors=True)
        manifest = {
            "schema": MIRROR_SCHEMA_VERSION,
            "digest": context.mirror_digest,
            "source_repo": str(context.repo_root),
            "git_visible_non_ignored_files": len(paths),
            "mirrored_files": len(files),
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


def ensure_ready(context: CocoIndexContext) -> None:
    """Install and prepare the external mirror."""
    ensure_installed(context)
    ensure_mirror(context)
    ensure_project_initialized(context)


def repo_relative_path_if_inside(repo_root: Path, path: Path) -> PurePosixPath | None:
    """Return a safe repo-relative path when *path* is inside *repo_root*."""
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(repo_root)
    except ValueError:
        return None
    return validate_repo_relative_path(relative.as_posix())


def run_ccc(
    context: CocoIndexContext, args: list[str], timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the pinned ccc executable inside the external mirror."""
    ensure_ready(context)
    return checked_command(
        [str(context.ccc_bin), *args],
        cwd=context.mirror_repo,
        env=ccc_env(context),
        timeout=timeout,
    )


def target_sqlite_db(context: CocoIndexContext) -> Path:
    """Return the expected external vector database path."""
    return context.db_dir / "target_sqlite.db"


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


def load_benchmark_cases(path: Path) -> list[dict[str, object]]:
    """Load and validate benchmark cases from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Benchmark cases file must contain a non-empty JSON list.")
    cases: list[dict[str, object]] = []
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
        cases.append(item)
    return cases


def run_benchmark(
    context: CocoIndexContext,
    cases: list[dict[str, object]],
    output_path: Path | None,
    excluded_paths: frozenset[PurePosixPath] = frozenset(),
) -> dict[str, object]:
    """Run the reproducible hybrid search benchmark."""
    ensure_installed(context)
    ensure_mirror(context, excluded_paths)
    ensure_project_initialized(context)
    index_start = time.perf_counter()
    run_ccc(context, ["index"], timeout=timeout_seconds("index"))
    index_elapsed = time.perf_counter() - index_start

    rg_bin = resolve_required_executable("rg")
    results: list[dict[str, object]] = []
    rg_exclude_args = [
        flag
        for path in sorted(excluded_paths, key=str)
        for flag in ("-g", f"!{path.as_posix()}")
    ]
    for case in cases:
        expected = [str(value) for value in case["expected"]]  # type: ignore[index]
        rg_start = time.perf_counter()
        rg_result = run_command(
            [
                rg_bin,
                "-n",
                "-i",
                "--no-heading",
                *rg_exclude_args,
                str(case["rg"]),
                ".",
            ],
            cwd=context.repo_root,
            timeout=timeout_seconds("rg"),
        )
        rg_ms = (time.perf_counter() - rg_start) * 1000
        rg_files = parse_file_hits(RG_FILE_RE, rg_result.stdout)

        coco_start = time.perf_counter()
        coco_result = run_command(
            [str(context.ccc_bin), "search", "--limit", "5", str(case["query"])],
            cwd=context.mirror_repo,
            env=ccc_env(context),
            timeout=timeout_seconds("search"),
        )
        coco_ms = (time.perf_counter() - coco_start) * 1000
        if coco_result.returncode != 0:
            raise RuntimeError(
                "\n".join(
                    [
                        f"CocoIndex search failed for case {case['name']}",
                        coco_result.stdout,
                        coco_result.stderr,
                    ]
                )
            )
        coco_files = parse_file_hits(SEARCH_FILE_RE, coco_result.stdout)
        focused_rg_start = time.perf_counter()
        existing_coco_files = [
            path for path in coco_files if (context.repo_root / path).is_file()
        ]
        if existing_coco_files:
            focused_rg_result = run_command(
                [
                    rg_bin,
                    "-n",
                    "-i",
                    "--no-heading",
                    str(case["rg"]),
                    *existing_coco_files,
                ],
                cwd=context.repo_root,
                timeout=timeout_seconds("rg"),
            )
        else:
            focused_rg_result = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="",
            )
        focused_rg_ms = (time.perf_counter() - focused_rg_start) * 1000
        focused_rg_files = parse_file_hits(RG_FILE_RE, focused_rg_result.stdout)
        hybrid_chars = len(coco_result.stdout) + len(focused_rg_result.stdout)

        results.append(
            {
                "case": case["name"],
                "rg_ms": round(rg_ms, 1),
                "rg_returncode": rg_result.returncode,
                "rg_chars": len(rg_result.stdout),
                "rg_line_count": rg_result.stdout.count("\n"),
                "rg_unique_files": len(rg_files),
                "rg_first_files": rg_files[:5],
                "rg_expected_rank": hit_rank(rg_files, expected),
                "coco_ms": round(coco_ms, 1),
                "coco_chars": len(coco_result.stdout),
                "coco_line_count": coco_result.stdout.count("\n"),
                "coco_unique_files": len(coco_files),
                "coco_first_files": coco_files[:5],
                "coco_expected_rank": hit_rank(coco_files, expected),
                "focused_rg_ms": round(focused_rg_ms, 1),
                "focused_rg_returncode": focused_rg_result.returncode,
                "focused_rg_chars": len(focused_rg_result.stdout),
                "focused_rg_line_count": focused_rg_result.stdout.count("\n"),
                "focused_rg_unique_files": len(focused_rg_files),
                "hybrid_chars": hybrid_chars,
            }
        )

    payload = {
        "benchmark_schema": 1,
        "package": PACKAGE_REQUIREMENT,
        "package_wheel_sha256": PACKAGE_WHEEL_SHA256,
        "package_sdist_sha256": PACKAGE_SDIST_SHA256,
        "repo_head": checked_command(
            [resolve_required_executable("git"), "rev-parse", "HEAD"],
            cwd=context.repo_root,
        ).stdout.strip(),
        "mirror_digest": context.mirror_digest,
        "benchmark_excluded_paths": [
            path.as_posix() for path in sorted(excluded_paths, key=str)
        ],
        "index_elapsed_seconds": round(index_elapsed, 2),
        "index_db_bytes": target_sqlite_db(context).stat().st_size,
        "results": results,
        "summary": {
            "cases": len(results),
            "rg_top5_hits": sum(
                1
                for result in results
                if result["rg_expected_rank"] and result["rg_expected_rank"] <= 5
            ),
            "coco_top5_hits": sum(
                1
                for result in results
                if result["coco_expected_rank"] and result["coco_expected_rank"] <= 5
            ),
            "rg_total_chars": sum(int(result["rg_chars"]) for result in results),
            "coco_total_chars": sum(int(result["coco_chars"]) for result in results),
            "focused_rg_total_chars": sum(
                int(result["focused_rg_chars"]) for result in results
            ),
            "hybrid_total_chars": sum(
                int(result["hybrid_chars"]) for result in results
            ),
            "rg_avg_ms": round(
                sum(float(result["rg_ms"]) for result in results) / len(results), 1
            ),
            "coco_avg_ms": round(
                sum(float(result["coco_ms"]) for result in results) / len(results), 1
            ),
            "focused_rg_avg_ms": round(
                sum(float(result["focused_rg_ms"]) for result in results)
                / len(results),
                1,
            ),
            "rg_total_unique_file_mentions": sum(
                int(result["rg_unique_files"]) for result in results
            ),
            "coco_total_unique_file_mentions": sum(
                int(result["coco_unique_files"]) for result in results
            ),
        },
    }
    if output_path is not None:
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def command_install(_args: argparse.Namespace) -> None:
    context = resolve_context()
    ensure_installed(context)
    print(f"installed {PACKAGE_REQUIREMENT} at {context.venv_dir}")


def command_prepare(_args: argparse.Namespace) -> None:
    context = resolve_context()
    ensure_ready(context)
    print(
        json.dumps(
            {"mirror_repo": str(context.mirror_repo), "digest": context.mirror_digest},
            sort_keys=True,
        )
    )


def command_index(_args: argparse.Namespace) -> None:
    context = resolve_context()
    output = run_ccc(context, ["index"], timeout=timeout_seconds("index"))
    print(output.stdout, end="")


def command_search(args: argparse.Namespace) -> None:
    context = resolve_context()
    ensure_ready(context)
    if args.refresh or not target_sqlite_db(context).exists():
        run_ccc(context, ["index"], timeout=timeout_seconds("index"))
    ccc_args = ["search", "--limit", str(args.limit)]
    if args.path:
        ccc_args.extend(["--path", args.path])
    for lang in args.lang:
        ccc_args.extend(["--lang", lang])
    ccc_args.extend(args.query)
    output = run_ccc(context, ccc_args, timeout=timeout_seconds("search"))
    print(output.stdout, end="")


def command_status(_args: argparse.Namespace) -> None:
    context = resolve_context()
    ensure_ready(context)
    output = run_ccc(context, ["status"], timeout=timeout_seconds("status"))
    print(output.stdout, end="")


def command_mcp(_args: argparse.Namespace) -> None:
    context = resolve_context()
    ensure_ready(context)
    os.execve(str(context.ccc_bin), [str(context.ccc_bin), "mcp"], ccc_env(context))


def mcp_config_payload(
    context: CocoIndexContext, *, pin_repo: bool
) -> dict[str, object]:
    """Return a stdio MCP configuration contract for any compatible agent."""
    env = {ARTIFACT_ROOT_ENV: str(context.artifact_root)}
    if pin_repo:
        env[REPO_ROOT_ENV] = str(context.repo_root)
    return {
        "name": MCP_SERVER_NAME,
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(Path(__file__).resolve()), "mcp"],
        "env": env,
        "working_directory_contract": (
            f"Launch from the target Git repository root or set {REPO_ROOT_ENV} "
            "to that root. The shared install stays under "
            f"{ARTIFACT_ROOT_ENV} or the XDG data default; each repository gets "
            "its own content-digest mirror, database, and runtime directory."
        ),
    }


def command_mcp_config(args: argparse.Namespace) -> None:
    context = resolve_context()
    print(json.dumps(mcp_config_payload(context, pin_repo=args.pin_repo), indent=2))


def command_mcp_install(_args: argparse.Namespace) -> None:
    context = resolve_context()
    codex = resolve_required_executable("codex")
    existing = run_command(
        [codex, "mcp", "get", MCP_SERVER_NAME], cwd=context.repo_root
    )
    if existing.returncode == 0:
        print(f"MCP server already configured: {MCP_SERVER_NAME}")
        return
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
            sys.executable,
            str(Path(__file__).resolve()),
            "mcp",
        ],
        cwd=context.repo_root,
    )
    print(f"MCP server configured: {MCP_SERVER_NAME}")


def command_benchmark(args: argparse.Namespace) -> None:
    repo_root = resolve_repo_root()
    excluded_paths = frozenset(
        path
        for path in [repo_relative_path_if_inside(repo_root, args.cases)]
        if path is not None
    )
    context = resolve_context(excluded_paths)
    payload = run_benchmark(
        context,
        load_benchmark_cases(args.cases),
        args.output,
        excluded_paths,
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
    prepare.set_defaults(func=command_prepare)

    index = subparsers.add_parser("index", help="Build or refresh the semantic index.")
    index.set_defaults(func=command_index)

    search = subparsers.add_parser("search", help="Search the semantic index.")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--path", help="Optional CocoIndex file path glob.")
    search.add_argument("--lang", action="append", default=[])
    search.add_argument("--refresh", action="store_true")
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

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Run the reproducible rg-vs-CocoIndex routing benchmark.",
    )
    benchmark.add_argument("--cases", type=Path, required=True)
    benchmark.add_argument("--output", type=Path)
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
