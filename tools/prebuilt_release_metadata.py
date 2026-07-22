#!/usr/bin/env python3
"""Resolve release metadata for the prebuilt carrier workflow."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[a-z-][0-9a-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[a-z-][0-9a-z-]*))*))?$"
)
DOCKER_HUB_REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*/[a-z0-9]+(?:[._-][a-z0-9]+)*$"
)
CHANGELOG_RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>[^\]]+)\] - (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$"
)
CHANGELOG_SUBSECTION_PATTERN = re.compile(r"^### (?P<name>[A-Za-z][A-Za-z ]*)$")
CHANGELOG_REFERENCE_PATTERN = re.compile(
    r"^\[(?P<label>[^\]]+)\]: (?P<url>https://\S+)$"
)
PLACEHOLDER_PATTERN = re.compile(r"\b(?:TO" r"DO|TBD|WIP)\b", re.IGNORECASE)
PUBLIC_URL_PATTERN = re.compile(r"https?://[^\s<>()`]+", re.IGNORECASE)
ACCOUNT_TARGET_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z_][A-Za-z0-9._%+-]*@"
    r"[A-Za-z0-9][A-Za-z0-9.-]*"
)
IPV4_CANDIDATE_PATTERN = re.compile(
    r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])"
)
IPV6_CANDIDATE_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}"
    r"[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)
LOCAL_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]"
    r"|/(?:home|users)/[^/\s`]+|/root(?:[/\s`]|$))",
    re.IGNORECASE,
)
INTERNAL_HOST_PATTERN = re.compile(
    r"\b(?:localhost|[A-Za-z0-9-]+\.(?:local|lan|internal|home|corp))\b",
    re.IGNORECASE,
)
CREDENTIAL_URL_PATTERN = re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:password|passwd|passphrase|secret|api[ _-]?key|access[ _-]?token|"
    r"auth[ _-]?token|private[ _-]?key)\b\s*(?:=|:)\s*[^\s`]+",
    re.IGNORECASE,
)
HIGH_CONFIDENCE_SECRET_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:github_pat_|gh[pousr]_|dckr_pat_|dsp_|glpat-|"
    r"xox[baprs]-|sk_(?:live|test)_|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})"
)
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
SECURITY_IMPLEMENTATION_DETAIL_PATTERN = re.compile(
    r"\b(?:attack(?:er| vector)?|bypass|CVE-[0-9]|endpoint|exploit|GHSA-|"
    r"payload|proof[ -]of[ -]concept|reproduc(?:e|tion)|request body|"
    r"request header|route|vulnerabilit(?:y|ies))\b",
    re.IGNORECASE,
)
STANDARD_CHANGELOG_SECTIONS = frozenset(
    {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
)
REQUIRED_RELEASE_SECTIONS = frozenset({"Upgrade Notes", "Verification"})
ALLOWED_CHANGELOG_SECTIONS = STANDARD_CHANGELOG_SECTIONS | REQUIRED_RELEASE_SECTIONS
MINIMUM_CHANGELOG_BODY_CHARACTERS = 200
MAXIMUM_CHANGELOG_BODY_WORDS = 350


@dataclass(frozen=True)
class SemVer:
    """Parsed docker-compatible SemVer release value."""

    major: int
    minor: int
    patch: int
    prerelease: str | None


@dataclass(frozen=True)
class ReleaseChangelog:
    """Validated changelog content for one release."""

    version: str
    release_date: dt.date
    body: str
    comparison_url: str


def parse_release_version(value: str) -> SemVer:
    """Parse a docker-compatible release version.

    Inputs: `value`. Output: `SemVer`; raises `ValueError` for invalid tags.
    """
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            "Release version must be docker-compatible SemVer without a v "
            "prefix or +build metadata, for example 1.0.0-main.1."
        )
    return SemVer(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=match.group(4),
    )


def is_valid_release_version(value: str) -> bool:
    """Return whether a release value is safe for the release workflow.

    Inputs: `value`. Output: `bool`.
    """
    try:
        validate_release_version(value)
    except ValueError:
        return False
    return True


def validate_release_version(value: str) -> str:
    """Validate a release version string.

    Inputs: `value`. Output: normalized `str`; raises `ValueError` on failure.
    """
    if value == "latest" or value.endswith(":latest"):
        raise ValueError("Release version must not be latest.")
    parse_release_version(value)
    return value


def validate_docker_repository(value: str) -> str:
    """Validate a docker hub namespace and repository.

    Inputs: `value`. Output: repository `str`; raises `ValueError` on failure.
    """
    if DOCKER_HUB_REPOSITORY_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "docker repository must be a lower-case docker hub namespace/repository."
        )
    return value


def validate_public_release_text(text: str, context: str) -> None:
    """Reject sensitive or exploit-enabling content from public release text.

    Inputs: public `text` and a non-sensitive `context` label. Output: none;
    raises `ValueError` without echoing any matched content.
    """
    checks = (
        (HIGH_CONFIDENCE_SECRET_PATTERN, "a credential-shaped value"),
        (PRIVATE_KEY_PATTERN, "private-key material"),
        (CREDENTIAL_ASSIGNMENT_PATTERN, "an inline credential assignment"),
        (CREDENTIAL_URL_PATTERN, "credentials embedded in a URL"),
        (ACCOUNT_TARGET_PATTERN, "an email address or account-qualified host"),
        (LOCAL_PATH_PATTERN, "a user-specific or local-system path"),
        (INTERNAL_HOST_PATTERN, "a local or private hostname"),
        (
            SECURITY_IMPLEMENTATION_DETAIL_PATTERN,
            "implementation-level security detail",
        ),
    )
    for pattern, label in checks:
        if pattern.search(text) is not None:
            raise ValueError(f"{context} contains {label}; public release blocked.")

    for pattern in (IPV4_CANDIDATE_PATTERN, IPV6_CANDIDATE_PATTERN):
        for match in pattern.finditer(text):
            try:
                ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            raise ValueError(
                f"{context} contains an IP address; public release blocked."
            )

    for match in PUBLIC_URL_PATTERN.finditer(text):
        try:
            parsed = urllib.parse.urlsplit(match.group(0).rstrip(".,;:"))
        except ValueError as exc:
            raise ValueError(f"{context} contains an invalid public URL.") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                f"{context} contains credentials embedded in a URL; "
                "public release blocked."
            )
        hostname = parsed.hostname
        if not hostname:
            raise ValueError(f"{context} contains an invalid public URL.")


def _parse_changelog_sections(body: str, release_version: str) -> dict[str, list[str]]:
    """Parse and validate canonical Keep a Changelog subsections.

    Inputs: release `body`, `release_version`. Output: section-to-lines mapping.
    """
    lines = body.splitlines()
    sections: dict[str, list[str]] = {}
    current_name: str | None = None
    for line in lines:
        if line.startswith("### "):
            match = CHANGELOG_SUBSECTION_PATTERN.fullmatch(line)
            if match is None:
                raise ValueError(
                    f"CHANGELOG.md section for {release_version} has an invalid "
                    "subsection heading."
                )
            current_name = match.group("name")
            if current_name not in ALLOWED_CHANGELOG_SECTIONS:
                raise ValueError(
                    f"CHANGELOG.md section for {release_version} uses unsupported "
                    f"subsection {current_name!r}."
                )
            if current_name in sections:
                raise ValueError(
                    f"CHANGELOG.md section for {release_version} duplicates "
                    f"subsection {current_name!r}."
                )
            sections[current_name] = []
        elif current_name is not None:
            sections[current_name].append(line)

    if not STANDARD_CHANGELOG_SECTIONS.intersection(sections):
        raise ValueError(
            f"CHANGELOG.md section for {release_version} needs at least one "
            "Keep a Changelog change category."
        )
    missing_sections = sorted(REQUIRED_RELEASE_SECTIONS.difference(sections))
    if missing_sections:
        raise ValueError(
            f"CHANGELOG.md section for {release_version} is missing required "
            f"subsection(s): {', '.join(missing_sections)}."
        )
    for name, section_lines in sections.items():
        if not any(line.startswith("- ") for line in section_lines):
            raise ValueError(
                f"CHANGELOG.md subsection {name!r} for {release_version} "
                "needs at least one bullet point."
            )
    return sections


def extract_release_changelog(text: str, release_version: str) -> ReleaseChangelog:
    """Extract and validate one exact version section from changelog text.

    Inputs: changelog `text`, `release_version`. Output: `ReleaseChangelog`.
    Raises: `ValueError` when the section is missing, duplicated, or incomplete.
    """
    validate_release_version(release_version)
    lines = text.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = CHANGELOG_RELEASE_HEADING_PATTERN.fullmatch(line)
        if match is not None and match.group("version") == release_version:
            matches.append((index, match))

    if len(matches) != 1:
        raise ValueError(
            f"CHANGELOG.md must contain exactly one '## [{release_version}] - "
            "YYYY-MM-DD' section."
        )

    start_index, heading = matches[0]
    try:
        release_date = dt.date.fromisoformat(heading.group("date"))
    except ValueError as exc:
        raise ValueError(
            f"CHANGELOG.md has an invalid date for {release_version}."
        ) from exc

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("## ") or CHANGELOG_REFERENCE_PATTERN.fullmatch(
            lines[index]
        ):
            end_index = index
            break
    body = "\n".join(lines[start_index + 1 : end_index]).strip()
    validate_release_changelog_body(body, release_version)

    reference_matches = [
        match
        for line in lines
        if (match := CHANGELOG_REFERENCE_PATTERN.fullmatch(line)) is not None
        and match.group("label") == release_version
    ]
    if len(reference_matches) != 1:
        raise ValueError(
            f"CHANGELOG.md must contain exactly one comparison link definition "
            f"for {release_version}."
        )
    comparison_url = reference_matches[0].group("url")
    validate_public_release_text(comparison_url, "CHANGELOG.md comparison link")
    parsed_comparison = urllib.parse.urlsplit(comparison_url)
    decoded_path = urllib.parse.unquote(parsed_comparison.path)
    if "/compare/" not in decoded_path or not decoded_path.endswith(
        f"...{release_version}"
    ):
        raise ValueError(
            f"CHANGELOG.md comparison link for {release_version} must end with "
            f"a previous-tag-to-{release_version} comparison."
        )
    return ReleaseChangelog(
        release_version,
        release_date,
        body,
        comparison_url,
    )


def validate_release_changelog_body(body: str, release_version: str) -> None:
    """Validate that release notes are substantive and human-readable.

    Inputs: section `body`, `release_version`. Output: none; raises `ValueError`.
    """
    if len(body) < MINIMUM_CHANGELOG_BODY_CHARACTERS:
        raise ValueError(f"CHANGELOG.md section for {release_version} is too short.")
    if len(body.split()) > MAXIMUM_CHANGELOG_BODY_WORDS:
        raise ValueError(
            f"CHANGELOG.md section for {release_version} exceeds the "
            f"{MAXIMUM_CHANGELOG_BODY_WORDS}-word public release-note limit."
        )
    if PLACEHOLDER_PATTERN.search(body) is not None:
        raise ValueError(
            f"CHANGELOG.md section for {release_version} contains placeholder text."
        )
    validate_public_release_text(body, f"CHANGELOG.md section for {release_version}")
    sections = _parse_changelog_sections(body, release_version)
    security_text = "\n".join(sections.get("Security", ()))
    if "`" in security_text:
        raise ValueError(
            f"CHANGELOG.md Security notes for {release_version} contain "
            "implementation or vulnerability detail; use an operator-safe summary."
        )


def render_release_notes(text: str, release_version: str) -> str:
    """Render validated changelog content as standalone release notes.

    Inputs: changelog `text`, `release_version`. Output: Markdown `str`.
    """
    changelog = extract_release_changelog(text, release_version)
    rendered = (
        f"# OMERO Docker Extended {changelog.version}\n\n"
        f"_Released {changelog.release_date.isoformat()}._\n\n"
        f"{changelog.body}\n\n"
        f"**Full comparison:** [{changelog.version}]"
        f"({changelog.comparison_url})\n"
    )
    validate_public_release_text(rendered, "rendered release notes")
    return rendered


def resolve_release_metadata(
    *,
    requested_version: str,
    requested_docker_repository: str,
    default_docker_repository: str,
) -> tuple[str, str, str]:
    """Resolve release metadata for GitHub and docker.

    Inputs: explicit requested values and defaults. Output: release, repo, and
    carrier image reference.
    """
    requested_version = requested_version.strip()
    if not requested_version:
        raise ValueError(
            "An explicit release version is required; never infer or auto-increment it."
        )
    release_version = validate_release_version(requested_version)
    docker_repository = validate_docker_repository(
        requested_docker_repository.strip() or default_docker_repository
    )
    return release_version, docker_repository, f"{docker_repository}:{release_version}"


def write_github_env(path: Path, values: dict[str, str]) -> None:
    """Write resolved metadata to a GitHub Actions env file.

    Inputs: `path`, `values`. Output: appends key-value lines to the file.
    """
    with path.open("a", encoding="utf-8") as env_file:
        for key, value in values.items():
            env_file.write(f"{key}={value}\n")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse release metadata command-line options.

    Inputs: `argv`. Output: parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(
        description="Resolve prebuilt carrier release metadata."
    )
    parser.add_argument("--validate-release-version", default=None)
    parser.add_argument("--validate-public-release-notes", type=Path, default=None)
    parser.add_argument("--requested-version", default="")
    parser.add_argument("--requested-docker-repository", default="")
    parser.add_argument("--default-docker-repository", default="")
    parser.add_argument("--changelog", type=Path, default=None)
    parser.add_argument("--release-notes-output", type=Path, default=None)
    parser.add_argument("--github-env", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run release metadata resolution.

    Inputs: optional `argv`. Output: process exit code.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.validate_release_version is not None:
            validate_release_version(args.validate_release_version)
            return 0
        if args.validate_public_release_notes is not None:
            validate_public_release_text(
                args.validate_public_release_notes.read_text(encoding="utf-8"),
                "release notes",
            )
            return 0
        if not args.default_docker_repository:
            raise ValueError("--default-docker-repository is required.")
        if args.changelog is None or args.release_notes_output is None:
            raise ValueError(
                "--changelog and --release-notes-output are required for a release."
            )
        release_version, docker_repository, carrier_image = resolve_release_metadata(
            requested_version=args.requested_version,
            requested_docker_repository=args.requested_docker_repository,
            default_docker_repository=args.default_docker_repository,
        )
        release_notes = render_release_notes(
            args.changelog.read_text(encoding="utf-8"), release_version
        )
        args.release_notes_output.parent.mkdir(parents=True, exist_ok=True)
        args.release_notes_output.write_text(release_notes, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    values = {
        "RELEASE_VERSION": release_version,
        "DOCKER_REPOSITORY": docker_repository,
        "CARRIER_IMAGE": carrier_image,
    }

    github_env = args.github_env or (
        Path(os.environ["GITHUB_ENV"]) if "GITHUB_ENV" in os.environ else None
    )
    if github_env is not None:
        write_github_env(github_env, values)

    print(f"Release version: {release_version}")
    print(f"Carrier image: {carrier_image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
