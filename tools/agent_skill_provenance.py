"""Helpers for repo-local agent skill provenance metadata."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from posixpath import commonpath
from urllib.parse import urlencode, urlsplit


UPSTREAM_SOURCES_DOC_PATH = Path("docs/reference/ai-agent-upstream-sources.md")
UPSTREAM_REPOSITORY_RE = re.compile(r"^- Upstream repository: `([^`]+)`$", re.MULTILINE)
UPSTREAM_TAG_RE = re.compile(r"^- Release tag: `([^`]+)`$", re.MULTILINE)
UPSTREAM_COMMIT_RE = re.compile(r"^- Release commit: `([^`]+)`$", re.MULTILINE)
VENDOR_PATH_RE = re.compile(r"^- Local vendor path: `([^`]+)`$", re.MULTILINE)
SKILL_TABLE_ROW_RE = re.compile(
    r"^\| `(?P<skill>[^`]+)` \| `(?P<path>third_party/[^`]+/SKILL\.md)` \|$",
    re.MULTILINE,
)
ALLOWED_FETCH_SCHEMES: frozenset[str] = frozenset({"https"})
ALLOWED_FETCH_HOSTS: frozenset[str] = frozenset({"raw.githubusercontent.com"})


@dataclass(frozen=True)
class AgentSkillUpstreamSources:
    """Pinned upstream source metadata for the repo-local skill overlays."""

    repo_slug: str
    tag: str
    commit: str
    vendor_path: str
    skill_vendor_paths: dict[str, str]

    @property
    def snapshot_dir_name(self) -> str:
        return Path(self.vendor_path.rstrip("/")).name

    @property
    def repo_name(self) -> str:
        return self.repo_slug.rsplit("/", 1)[-1]

    @property
    def vendor_root_path(self) -> Path:
        return Path(self.vendor_path.rstrip("/"))

    @property
    def upstream_relative_paths(self) -> dict[str, str]:
        relative_paths: dict[str, str] = {}
        for skill_name, vendor_path in self.skill_vendor_paths.items():
            relative_paths[skill_name] = str(
                Path(vendor_path).relative_to(self.vendor_root_path)
            )
        return relative_paths

    @property
    def upstream_skill_root(self) -> str:
        relative_paths = tuple(self.upstream_relative_paths.values())
        if not relative_paths:
            raise RuntimeError("No upstream skill paths were loaded.")
        return commonpath(relative_paths).rstrip("/")

    @property
    def badge_label(self) -> str:
        snapshot_name = self.snapshot_dir_name
        if snapshot_name.startswith("ecc-"):
            return f"ECC {snapshot_name.removeprefix('ecc-')} skills"
        return f"{snapshot_name} skills"

    @property
    def badge_title(self) -> str:
        return self.repo_name

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo_slug}"

    @property
    def skills_tree_url(self) -> str:
        return f"{self.repo_url}/tree/{self.tag}/{self.upstream_skill_root}"

    @property
    def badge_image_url(self) -> str:
        query = urlencode(
            {
                "label": self.badge_title,
                "message": self.badge_label,
                "color": "0F766E",
                "logo": "github",
            }
        )
        return f"https://img.shields.io/static/v1?{query}"

    def raw_skill_url(self, skill_name: str) -> str:
        relative_path = self.upstream_relative_paths[skill_name]
        return (
            "https://raw.githubusercontent.com/"
            f"{self.repo_slug}/{self.tag}/{relative_path}"
        )


def _extract_required_match(pattern: re.Pattern[str], text: str, label: str) -> str:
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(
            f"{UPSTREAM_SOURCES_DOC_PATH} is missing the required `{label}` field."
        )
    value = match.group(1).strip()
    if not value:
        raise RuntimeError(
            f"{UPSTREAM_SOURCES_DOC_PATH} contains an empty `{label}` field."
        )
    return value


def load_upstream_sources(repo_root: Path) -> AgentSkillUpstreamSources:
    """Parse the pinned upstream skill provenance document."""

    doc_text = (repo_root / UPSTREAM_SOURCES_DOC_PATH).read_text(encoding="utf-8")
    repo_slug = _extract_required_match(
        UPSTREAM_REPOSITORY_RE, doc_text, "Upstream repository"
    )
    tag = _extract_required_match(UPSTREAM_TAG_RE, doc_text, "Release tag")
    commit = _extract_required_match(UPSTREAM_COMMIT_RE, doc_text, "Release commit")
    vendor_path = _extract_required_match(VENDOR_PATH_RE, doc_text, "Local vendor path")
    skill_vendor_paths = {
        match.group("skill"): match.group("path")
        for match in SKILL_TABLE_ROW_RE.finditer(doc_text)
    }
    if not skill_vendor_paths:
        raise RuntimeError(
            f"{UPSTREAM_SOURCES_DOC_PATH} does not list any selected upstream skills."
        )

    return AgentSkillUpstreamSources(
        repo_slug=repo_slug,
        tag=tag,
        commit=commit,
        vendor_path=vendor_path,
        skill_vendor_paths=skill_vendor_paths,
    )


def resolve_required_executable(name: str) -> str:
    """Resolve an executable to an absolute path."""

    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"Required executable `{name}` is not available in PATH.")
    return resolved


def resolve_remote_tag_commit(repo_slug: str, tag: str, *, cwd: Path) -> str:
    """Resolve the exact commit currently referenced by a remote Git tag."""

    completed = subprocess.run(
        [
            resolve_required_executable("git"),
            "ls-remote",
            f"https://github.com/{repo_slug}.git",
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    refs: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        sha, ref = line.split(maxsplit=1)
        refs[ref] = sha

    resolved = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not resolved:
        raise RuntimeError(f"Could not resolve remote tag `{tag}` for {repo_slug}.")
    return resolved


def fetch_text(url: str, *, timeout: int = 20) -> str:
    """Fetch UTF-8 text from a URL."""

    parsed = urlsplit(url)
    if parsed.scheme not in ALLOWED_FETCH_SCHEMES:
        raise ValueError(f"Unsupported fetch scheme: {parsed.scheme!r}")
    if parsed.hostname not in ALLOWED_FETCH_HOSTS:
        raise ValueError(f"Unsupported fetch host: {parsed.hostname!r}")

    try:
        result = subprocess.run(
            [
                resolve_required_executable("curl"),
                "--silent",
                "--show-error",
                "--location",
                "--fail",
                "--header",
                "User-Agent: omero-agent-skill-audit",
                "--max-time",
                str(timeout),
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Upstream fetch failed: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "curl exited with a non-zero status."
        raise RuntimeError(f"Upstream fetch failed: {stderr}")
    return result.stdout
