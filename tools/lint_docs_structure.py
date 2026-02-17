"""Validate repository knowledge-base structure and cross-links."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


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
    "docs/design-docs/index.md",
    "docs/design-docs/core-beliefs.md",
    "docs/exec-plans/tech-debt-tracker.md",
    "docs/exec-plans/active/knowledge-base-bootstrap.md",
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
    "`design-docs/index.md`",
    "`exec-plans/tech-debt-tracker.md`",
    "`product-specs/index.md`",
)


def validate_required_paths(repo_root: Path) -> list[ValidationError]:
    """Validate that required docs and mapping files exist."""
    errors: list[ValidationError] = []
    for rel_path in REQUIRED_PATHS:
        candidate: Path = repo_root / rel_path
        if not candidate.exists():
            errors.append(ValidationError(f"Missing required path: {rel_path}"))
    return errors


def validate_index_links(repo_root: Path) -> list[ValidationError]:
    """Validate required links are present in docs index."""
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


def run_validations(repo_root: Path) -> Sequence[ValidationError]:
    """Run all validations and return aggregated errors."""
    errors: list[ValidationError] = []
    validators: Iterable = (validate_required_paths, validate_index_links)
    for validator in validators:
        errors.extend(validator(repo_root))
    return errors


def main() -> int:
    """Program entrypoint."""
    repo_root: Path = Path(__file__).resolve().parents[1]
    errors: Sequence[ValidationError] = run_validations(repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error.message}")
        return 1

    print("Documentation structure validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
