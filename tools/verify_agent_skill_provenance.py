"""Live audit of vendored agent-skill provenance against the upstream release."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover - supports direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import agent_skill_provenance


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Inputs: none. Output: `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Verify the vendored agent-skill snapshot against the pinned upstream "
            "repository, tag, and raw skill files."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing docs/reference/ai-agent-upstream-sources.md.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Per-request timeout in seconds for upstream raw-file fetches.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the `tools.verify_agent_skill_provenance` command entrypoint.

    Inputs: `argv`. Output: `int`.
    """
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    sources = agent_skill_provenance.load_upstream_sources(repo_root)

    failures: list[str] = []

    remote_commit = agent_skill_provenance.resolve_remote_tag_commit(
        sources.repo_slug, sources.tag, cwd=repo_root
    )
    if remote_commit != sources.commit:
        failures.append(
            "Pinned release commit mismatch: "
            f"doc has {sources.commit}, upstream tag resolves to {remote_commit}."
        )
    else:
        print(
            f"OK release tag {sources.tag} resolves to documented commit {sources.commit}"
        )

    for skill_name in sorted(sources.skill_vendor_paths):
        vendor_path = repo_root / sources.skill_vendor_paths[skill_name]
        local_text = vendor_path.read_text(encoding="utf-8")
        upstream_text = agent_skill_provenance.fetch_text(
            sources.raw_skill_url(skill_name),
            timeout=args.timeout,
        )
        normalized_local_text = agent_skill_provenance.strip_local_scanner_annotations(
            local_text
        )
        if normalized_local_text != upstream_text:
            failures.append(
                f"Vendored upstream mismatch for {skill_name}: {vendor_path}"
            )
            continue
        if local_text == upstream_text:
            print(f"OK vendored upstream snapshot matches {skill_name}")
        else:
            print(
                "OK vendored upstream snapshot matches "
                f"{skill_name} after scanner annotations"
            )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print(
        "Verified vendored upstream snapshot, release tag, and selected skill files "
        "against the live upstream source."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
