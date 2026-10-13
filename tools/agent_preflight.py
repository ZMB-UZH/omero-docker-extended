"""Require actual agent-tool execution, independent of editor or Git identity."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("caveman", "cocoindex-code-search", "crawl4ai-research")
MAX_AGE_SECONDS = 12 * 60 * 60


def policy_digest() -> str:
    """Invalidate receipts when any governing policy or executable changes.

    Inputs: current policy and tool files. Output: their SHA-256 identity.
    """
    paths = [
        ROOT / "AGENTS.md",
        ROOT / "docs/reference/ai-agent-task-contracts.md",
        Path(__file__).resolve(),
        ROOT / "tools/cocoindex_agent_search.py",
        ROOT / "tools/crawl4ai_research.py",
        ROOT / ".github/requirements/crawl4ai.txt",
        ROOT / ".github/requirements/crawl4ai-build.txt",
        ROOT / "tools/source_advisory_guard.py",
    ]
    paths.extend(sorted((ROOT / ".github/requirements/crawl4ai-source").iterdir()))
    paths.extend(ROOT / ".agents/skills" / name / "SKILL.md" for name in SKILLS)
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def receipt_path() -> Path:
    """Keep tool-use receipts private and separate for each checkout.

    Inputs: checkout root and XDG state setting. Output: an external receipt path.
    """
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    if not state.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    state = state.resolve()
    if state.is_relative_to(ROOT):
        raise ValueError("Agent receipts must stay outside the checkout")
    key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:24]
    return state / "omero-agent-workflow" / key / "receipt.json"


def execute(script: str, arguments: list[str], timeout: int) -> str:
    """Call the real repository tool; do not accept agent-written attestations.

    Inputs: script, arguments and timeout seconds. Output: nonempty tool stdout.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / script), *arguments],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if not result.stdout.strip():
        raise RuntimeError(f"{script} returned no execution evidence")
    return result.stdout


def begin(query: str, urls: list[str]) -> None:
    """Emit the mandatory style policy and record successful real tool runs.

    Inputs: routing query and research URLs. Output: private execution receipt;
    a failed run leaves earlier success invalidated.
    """
    print(
        (ROOT / ".agents/skills/caveman/SKILL.md").read_text(encoding="utf-8"),
        flush=True,
    )
    target = receipt_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Invalidate an earlier success before starting: a failed attempt must block.
    record: dict[str, object] = {"schema": 1, "complete": False}
    write_receipt(target, record)
    output = execute(
        "cocoindex_agent_search.py",
        ["search", "--require-current", "--limit", "3", query],
        600,
    )
    print(output, end="", flush=True)
    sources = []
    for url in urls:
        page = json.loads(execute("crawl4ai_research.py", ["read", url], 120))
        if (
            not isinstance(page, dict)
            or page.get("tool") != "crawl4ai"
            or not page.get("markdown")
            or not page.get("sha256")
            or page.get("success") is not True
            or not page.get("native_sha256")
            or not page.get("native_receipt")
        ):
            raise RuntimeError("Crawl4AI returned invalid execution evidence")
        print(json.dumps(page, ensure_ascii=True), flush=True)
        sources.append(
            {
                "source_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "content_sha256": page["sha256"],
                "fetched_at": page["fetched_at"],
                "native_sha256": page["native_sha256"],
            }
        )
    record.update(
        complete=True,
        policy=policy_digest(),
        created_at=datetime.now(timezone.utc).isoformat(),
        cocoindex_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        research_sources=sources,
        research_required=bool(urls),
    )
    write_receipt(target, record)
    print(
        "Agent preflight passed: Caveman loaded; CocoIndex executed; "
        + (
            f"Crawl4AI read {len(sources)} source(s)."
            if urls
            else "no web research declared."
        )
    )


def write_receipt(target: Path, record: dict[str, object]) -> None:
    """Publish a complete receipt atomically with owner-only permissions.

    Inputs: receipt destination and JSON record. Output: flushed atomic replacement.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as handle:
        json.dump(record, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, target)


def check() -> None:
    """Reject missing, failed, expired, or obsolete policy execution receipts.

    Inputs: private receipt and current policy. Output: success or a blocking error.
    """
    record = json.loads(receipt_path().read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("schema") != 1
        or record.get("complete") is not True
    ):
        raise ValueError("Agent preflight has not completed")
    if record.get("policy") != policy_digest() or not record.get(
        "cocoindex_output_sha256"
    ):
        raise ValueError("Agent-tool policy changed; rerun preflight")
    created = datetime.fromisoformat(record["created_at"])
    age = (datetime.now(timezone.utc) - created).total_seconds()
    if not 0 <= age < MAX_AGE_SECONDS:
        raise ValueError("Agent preflight expired; rerun it for this task")
    if record.get("research_required") and not record.get("research_sources"):
        raise ValueError("Required Crawl4AI research did not complete")


def main(argv: list[str] | None = None) -> int:
    """Expose the shared begin/check commands to every supported agent harness.

    Inputs: command-line arguments. Output: zero on success, a nonzero gate status
    on failure, with hook-compatible rejection when requested.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("begin", "check", "policy"))
    parser.add_argument("--query")
    parser.add_argument("--research-url", action="append", default=[])
    parser.add_argument("--hook", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "policy":
            print(
                "Mandatory: before editing, run python3 tools/agent_preflight.py begin "
                "--query '<task>' and --research-url '<public-source>' for web research. "
                "Caveman, CocoIndex Code, and Crawl4AI are required; no silent substitution."
            )
        elif args.command == "begin":
            if not args.query or not args.query.strip():
                raise ValueError("A task-specific CocoIndex query is required")
            begin(args.query, args.research_url)
        else:
            check()
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"Agent preflight blocked: {type(exc).__name__}. "
            "Run the mandatory begin command; diagnose failed tools, do not skip them.",
            file=sys.stderr,
        )
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr[-4000:], file=sys.stderr)
        return 2 if args.hook else 1


if __name__ == "__main__":
    raise SystemExit(main())
