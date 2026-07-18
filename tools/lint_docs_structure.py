"""Validate repository knowledge-base structure and cross-links."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit

if __package__ in (None, ""):  # pragma: no cover - direct script execution path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.agent_context_policy import CONTEXT_SURFACE_CONTRACTS


@dataclass(frozen=True)
class ValidationError:
    """Represents a docs validation error."""

    message: str


REQUIRED_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/index.md",
    "docs/DESIGN.md",
    "docs/FRONTEND.md",
    "docs/PLANS.md",
    "docs/PRODUCT_SENSE.md",
    "docs/QUALITY_SCORE.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/reference/ai-agent-context-routing.md",
    "docs/reference/ai-agent-runtime-playbook.md",
    "docs/reference/ai-agent-skills.md",
    "docs/design-docs/index.md",
    "docs/design-docs/core-beliefs.md",
    "docs/exec-plans/tech-debt-tracker.md",
    "docs/exec-plans/completed/knowledge-base-bootstrap.md",
    "docs/exec-plans/completed/README.md",
    "docs/generated/db-schema.md",
    "docs/product-specs/index.md",
    "docs/product-specs/new-user-onboarding.md",
    "docs/references/design-system-reference-llms.txt",
    "docs/references/docker-compose-llms.txt",
)

REQUIRED_INDEX_LINKS: tuple[str, ...] = (
    "`DESIGN.md`",
    "`FRONTEND.md`",
    "`PLANS.md`",
    "`PRODUCT_SENSE.md`",
    "`QUALITY_SCORE.md`",
    "`RELIABILITY.md`",
    "`SECURITY.md`",
    "`reference/ai-agent-context-routing.md`",
    "`reference/ai-agent-skills.md`",
    "`design-docs/index.md`",
    "`exec-plans/tech-debt-tracker.md`",
    "`product-specs/index.md`",
)

FIRST_PARTY_MARKDOWN_GLOBS: tuple[str, ...] = (
    "*.md",
    ".agents/**/*.md",
    ".github/**/*.md",
    "docs/**/*.md",
)
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
INLINE_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
REFERENCE_LINK_RE = re.compile(
    r"^\s{0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|([^\s]+))", re.MULTILINE
)


def validate_required_paths(repo_root: Path) -> list[ValidationError]:
    """Validate the required paths.

    Inputs: `repo_root` (Path). Output: `list[ValidationError]`.
    """
    errors: list[ValidationError] = []
    for rel_path in REQUIRED_PATHS:
        candidate: Path = repo_root / rel_path
        if not candidate.exists():
            errors.append(ValidationError(f"Missing required path: {rel_path}"))
    return errors


def validate_index_links(repo_root: Path) -> list[ValidationError]:
    """Validate the index links.

    Inputs: `repo_root` (Path). Output: `list[ValidationError]`.
    """
    index_path: Path = repo_root / "docs/index.md"
    if not index_path.exists():
        return [ValidationError("Missing docs/index.md; cannot validate links")]

    index_text: str = index_path.read_text(encoding="utf-8")
    errors: list[ValidationError] = []
    for required_link in REQUIRED_INDEX_LINKS:
        if required_link not in index_text:
            errors.append(
                ValidationError(
                    f"docs/index.md missing required link token: {required_link}"
                )
            )
    return errors


def validate_context_surfaces(repo_root: Path) -> list[ValidationError]:
    """Validate the context surfaces.

    Inputs: `repo_root` (Path). Output: `list[ValidationError]`.
    """
    errors: list[ValidationError] = []
    for rel_path, contract in CONTEXT_SURFACE_CONTRACTS.items():
        path = repo_root / rel_path
        if not path.exists():
            errors.append(ValidationError(f"Missing context surface: {rel_path}"))
            continue
        text = path.read_text(encoding="utf-8")
        if contract.max_nonempty_lines is not None:
            nonempty_lines = [line for line in text.splitlines() if line.strip()]
            if len(nonempty_lines) > contract.max_nonempty_lines:
                errors.append(
                    ValidationError(
                        f"{rel_path} exceeds compactness budget: "
                        f"{len(nonempty_lines)} non-empty lines > {contract.max_nonempty_lines}"
                    )
                )
        for token in contract.required_tokens:
            if token not in text:
                errors.append(
                    ValidationError(
                        f"{rel_path} missing required routing token: {token}"
                    )
                )
    return errors


def _visible_markdown(text: str) -> str:
    """Return Markdown prose with fenced and inline code removed.

    Inputs: `text`. Output: visible Markdown prose as `str`.
    """
    visible_lines: list[str] = []
    inside_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            visible_lines.append(INLINE_CODE_RE.sub("", line))
    return "\n".join(visible_lines)


def _relative_link_destinations(text: str) -> list[str]:
    """Extract inline and reference-style link destinations from prose.

    Inputs: `text`. Output: ordered link destinations as `list[str]`.
    """
    visible = _visible_markdown(text)
    matches = (*INLINE_LINK_RE.finditer(visible), *REFERENCE_LINK_RE.finditer(visible))
    return [
        next(group for group in match.groups() if group is not None)
        for match in matches
    ]


def _resolved_relative_link(
    repo_root: Path, source_path: Path, destination: str
) -> Path | None:
    """Resolve a local Markdown destination or return None for non-file links.

    Inputs: `repo_root`, `source_path`, and `destination`. Output: resolved local
    `Path`, or None when the destination does not identify a local file.
    """
    if destination.startswith(("#", "/")):
        return None
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return (source_path.parent / unquote(parsed.path)).resolve()


def validate_relative_markdown_links(repo_root: Path) -> list[ValidationError]:
    """Validate relative links in every first-party Markdown document.

    Inputs: `repo_root`. Output: collected `ValidationError` entries.
    """
    repo_root = repo_root.resolve()
    markdown_paths = sorted(
        {
            path
            for pattern in FIRST_PARTY_MARKDOWN_GLOBS
            for path in repo_root.glob(pattern)
            if path.is_file()
        }
    )
    errors: list[ValidationError] = []
    for source_path in markdown_paths:
        text = source_path.read_text(encoding="utf-8")
        for destination in _relative_link_destinations(text):
            resolved = _resolved_relative_link(repo_root, source_path, destination)
            if resolved is None:
                continue
            source_display = source_path.relative_to(repo_root).as_posix()
            if not resolved.is_relative_to(repo_root):
                errors.append(
                    ValidationError(
                        f"{source_display} has repository-escaping link: {destination}"
                    )
                )
            elif not resolved.exists():
                errors.append(
                    ValidationError(
                        f"{source_display} has broken relative link: {destination}"
                    )
                )
    return errors


def run_validations(repo_root: Path) -> Sequence[ValidationError]:
    """All validations and return aggregated errors.

    Inputs: `repo_root`. Output: `Sequence[ValidationError]`.
    """
    errors: list[ValidationError] = []
    validators: Iterable = (
        validate_required_paths,
        validate_index_links,
        validate_context_surfaces,
        validate_relative_markdown_links,
    )
    for validator in validators:
        errors.extend(validator(repo_root))
    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for `tools.lint_docs_structure`.

    Inputs: `argv` (Sequence[str] | None) command-line arguments. Output:
    `argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Validate repository documentation structure and agent surfaces."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to validate.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `tools.lint_docs_structure` command entrypoint.

    Inputs: `argv`. Output: `int`.
    """
    args = parse_args(argv)
    repo_root = args.repo_root
    errors: Sequence[ValidationError] = run_validations(repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error.message}")
        return 1

    print("Documentation structure validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
