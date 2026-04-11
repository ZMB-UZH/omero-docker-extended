"""Generate the README badge row from canonical repository metadata."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    from tools import agent_skill_provenance
except ImportError:  # pragma: no cover - supports direct script execution
    import agent_skill_provenance

BADGE_BLOCK_BEGIN = "<!-- BEGIN GENERATED BADGES -->"
BADGE_BLOCK_END = "<!-- END GENERATED BADGES -->"
README_PATH = Path("README.md")
CANONICAL_METADATA_PATH = Path(".github/readme_badges.json")
CAVEMAN_BADGE_TITLE = "caveman"
CAVEMAN_BADGE_IMAGE_URL = (
    "https://img.shields.io/static/v1?label=&message=caveman&color=555"
    "&logo=github&logoColor=white"
)
CAVEMAN_BADGE_TARGET_URL = "https://github.com/JuliusBrussee/caveman"


@dataclass(frozen=True)
class RepoMetadata:
    """Repository details needed to render badge URLs."""

    host: str
    owner: str
    repo: str
    remote_name: str
    branch_name: str

    @property
    def github_path(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def branch_query_value(self) -> str:
        return quote(self.branch_name, safe="")


def _load_canonical_repo_metadata(repo_root: Path) -> RepoMetadata | None:
    metadata_path = repo_root / CANONICAL_METADATA_PATH
    if not metadata_path.exists():
        return None

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    required_fields = ("host", "owner", "repo", "branch_name")
    missing_fields = [
        field for field in required_fields if not str(payload.get(field, "")).strip()
    ]
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise RuntimeError(
            f"{CANONICAL_METADATA_PATH} is missing required field(s): {missing}"
        )

    remote_name = str(payload.get("remote_name", "canonical")).strip() or "canonical"
    return RepoMetadata(
        host=str(payload["host"]).strip(),
        owner=str(payload["owner"]).strip(),
        repo=str(payload["repo"]).strip(),
        remote_name=remote_name,
        branch_name=str(payload["branch_name"]).strip(),
    )


def _run_git(repo_root: Path, *args: str) -> str:
    safe_repo_root = str(repo_root.resolve())
    completed = subprocess.run(
        [
            agent_skill_provenance.resolve_required_executable("git"),
            "-c",
            f"safe.directory={safe_repo_root}",
            *args,
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _resolve_remote_name(repo_root: Path) -> str:
    try:
        upstream = _run_git(
            repo_root,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        )
    except subprocess.CalledProcessError:
        upstream = ""
    if upstream and "/" in upstream:
        return upstream.split("/", 1)[0]

    branch_name = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    try:
        configured_remote = _run_git(
            repo_root, "config", "--get", f"branch.{branch_name}.remote"
        )
    except subprocess.CalledProcessError:
        configured_remote = ""
    if configured_remote:
        return configured_remote

    remotes = [
        remote
        for remote in _run_git(repo_root, "remote").splitlines()
        if remote.strip()
    ]
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    raise RuntimeError(
        "Could not determine which Git remote should drive the README badges."
    )


def _resolve_branch_name(repo_root: Path, remote_name: str) -> str:
    head_ref = f"refs/remotes/{remote_name}/HEAD"
    try:
        symbolic_ref = _run_git(repo_root, "symbolic-ref", head_ref)
    except subprocess.CalledProcessError:
        symbolic_ref = ""
    if symbolic_ref.startswith(f"refs/remotes/{remote_name}/"):
        return symbolic_ref.rsplit("/", 1)[-1]

    remote_description = _run_git(repo_root, "remote", "show", remote_name)
    for line in remote_description.splitlines():
        stripped = line.strip()
        if stripped.startswith("HEAD branch: "):
            return stripped.removeprefix("HEAD branch: ").strip()

    return _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")


def _parse_remote_url(remote_url: str) -> tuple[str, str, str]:
    normalized_url = remote_url.strip()
    if "://" in normalized_url:
        parsed = urlparse(normalized_url)
        host = parsed.hostname or ""
        path = parsed.path
    else:
        if ":" not in normalized_url:
            raise RuntimeError(f"Unsupported Git remote URL: {remote_url}")
        remote_host, remote_path = normalized_url.split(":", 1)
        host = remote_host.rsplit("@", 1)[-1]
        path = f"/{remote_path}"

    path_parts = [part for part in path.strip("/").split("/") if part]
    if len(path_parts) < 2 or not host:
        raise RuntimeError(f"Unsupported Git remote URL: {remote_url}")

    owner = path_parts[-2]
    repo = path_parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise RuntimeError(f"Unsupported Git remote URL: {remote_url}")
    return host, owner, repo


def resolve_repo_metadata(repo_root: Path) -> RepoMetadata:
    canonical_metadata = _load_canonical_repo_metadata(repo_root)
    if canonical_metadata is not None:
        return canonical_metadata

    remote_name = _resolve_remote_name(repo_root)
    remote_url = _run_git(repo_root, "remote", "get-url", remote_name)
    host, owner, repo = _parse_remote_url(remote_url)
    branch_name = _resolve_branch_name(repo_root, remote_name)
    return RepoMetadata(
        host=host,
        owner=owner,
        repo=repo,
        remote_name=remote_name,
        branch_name=branch_name,
    )


def render_badge_block(
    metadata: RepoMetadata,
    upstream_sources: agent_skill_provenance.AgentSkillUpstreamSources,
) -> str:
    github_path = metadata.github_path
    branch = metadata.branch_query_value
    lines = [
        BADGE_BLOCK_BEGIN,
        f"[![License](https://img.shields.io/github/license/{github_path})](LICENSE)",
        f"[![tests](https://img.shields.io/github/actions/workflow/status/{github_path}/tests.yml?branch={branch}&label=tests)](https://github.com/{github_path}/actions/workflows/tests.yml)",
        f"[![security-code-scanning](https://img.shields.io/github/actions/workflow/status/{github_path}/security-code-scanning.yml?branch={branch}&label=security-code-scanning)](https://github.com/{github_path}/actions/workflows/security-code-scanning.yml)",
        f"[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/{github_path})](https://github.com/{github_path}/commits/{branch})",
        f"[![Codecov](https://img.shields.io/codecov/c/github/{github_path}?label=Codecov&logo=codecov)](https://codecov.io/gh/{github_path})",
        f"[![super-linter](https://img.shields.io/github/actions/workflow/status/{github_path}/super-linter.yml?branch={branch}&label=super-linter&logo=github)](https://github.com/{github_path}/actions/workflows/super-linter.yml)",
        f"[![Ruff](https://img.shields.io/github/actions/workflow/status/{github_path}/ruff.yml?branch={branch}&logo=ruff&label=Ruff)](https://github.com/{github_path}/actions/workflows/ruff.yml)",
        f"[![Vulture](https://img.shields.io/github/actions/workflow/status/{github_path}/vulture.yml?branch={branch}&logo=python&label=Vulture)](https://github.com/{github_path}/actions/workflows/vulture.yml)",
        f"[![{upstream_sources.badge_title}]({upstream_sources.badge_image_url})]({upstream_sources.repo_url})",
        f"[![{CAVEMAN_BADGE_TITLE}]({CAVEMAN_BADGE_IMAGE_URL})]({CAVEMAN_BADGE_TARGET_URL})",
        BADGE_BLOCK_END,
    ]
    return "\n".join(lines)


def extract_badge_block(readme_text: str) -> str:
    start = readme_text.find(BADGE_BLOCK_BEGIN)
    end = readme_text.find(BADGE_BLOCK_END)
    if start == -1 or end == -1:
        raise RuntimeError(
            "README.md is missing the generated badge markers. "
            "Run the tool with --write after inserting them once."
        )
    end += len(BADGE_BLOCK_END)
    return readme_text[start:end]


def update_readme_text(readme_text: str, badge_block: str) -> str:
    current_block = extract_badge_block(readme_text)
    return readme_text.replace(current_block, badge_block)


def update_readme(repo_root: Path, write: bool) -> int:
    readme_path = repo_root / README_PATH
    original_text = readme_path.read_text(encoding="utf-8")
    badge_block = render_badge_block(
        resolve_repo_metadata(repo_root),
        agent_skill_provenance.load_upstream_sources(repo_root),
    )
    updated_text = update_readme_text(original_text, badge_block)

    if updated_text == original_text:
        return 0

    if not write:
        sys.stderr.write(
            "README.md badge block is out of date. Run "
            "`python3 tools/update_readme_badges.py --write`.\n"
        )
        return 1

    readme_path.write_text(
        updated_text + ("" if updated_text.endswith("\n") else "\n"), encoding="utf-8"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the README badge row from canonical repository metadata."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Fail if README.md does not match the generated badge block.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Rewrite README.md with the generated badge block.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing README.md. Defaults to the current directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    return update_readme(repo_root=repo_root, write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
