"""Isolated Linux Crawl4AI reader for agent research, not an OMERO service."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".github/requirements/crawl4ai.txt"
BUILD_LOCK = ROOT / ".github/requirements/crawl4ai-build.txt"
VERSION = "0.9.4"
NLTK_SOURCE_URL = (
    "https://github.com/nltk/nltk/archive/"
    "b417a98a9497b4a27067043e35e64c388e060686.tar.gz"
)
NLTK_SOURCE_SHA256 = "39612e4c4aebe7626f582d103ac87bd7c5ed256e6341114e61143a8b73c560ee"  # DevSkim: ignore DS173237 -- public upstream archive SHA-256, not a credential
ATTRIBUTION = (
    "This product includes software developed by UncleCode "
    "(https://x.com/unclecode) as part of the Crawl4AI project "
    "(https://github.com/unclecode/crawl4ai)."
)


def tool_home() -> Path:
    """Resolve external state without accepting a checkout or relative path.

    Inputs: XDG and explicit reader-home settings. Output: an external state root.
    """
    default = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    home = Path(os.environ.get("AGENT_CRAWL4AI_HOME", default / "omero-agent-research"))
    if not home.is_absolute():
        raise ValueError("Crawl4AI state requires an absolute external path")
    home = home.resolve()
    if (
        home == Path(home.anchor)
        or home.is_relative_to(ROOT)
        or ROOT.is_relative_to(home)
    ):
        raise ValueError("Crawl4AI state must be outside the checkout")
    return home


def runtime(home: Path) -> Path:
    """Bind each isolated environment to Python and the complete dependency lock.

    Inputs: external home, interpreter and lock bytes. Output: runtime directory.
    """
    digest = hashlib.sha256(
        LOCK.read_bytes() + b"\0" + BUILD_LOCK.read_bytes()
    ).hexdigest()[:20]
    return home / f"py{sys.version_info.major}.{sys.version_info.minor}-{digest}"


def child_environment(home: Path) -> dict[str, str]:
    """Do not forward API keys, cookies, proxy credentials, or deployment env.

    Inputs: external tool home. Output: an explicit minimal child environment.
    """
    return {
        "PATH": os.defpath,
        "HOME": str(home / "home"),
        "AGENT_CRAWL4AI_HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CRAWL4AI_BASE_DIRECTORY": str(home / "data"),
        "PLAYWRIGHT_BROWSERS_PATH": str(home / "browsers"),
        "PIP_CACHE_DIR": str(home / "pip-cache"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "DO_NOT_TRACK": "1",
    }


def run_process(command: list[str], home: Path, timeout: int) -> str:
    """Bound the entire process group, including browser children, on failure.

    Inputs: argv, external home and timeout seconds. Output: successful stdout;
    failures raise after diagnostics or process-group termination.
    """
    with subprocess.Popen(
        command,
        cwd=home,
        env=child_environment(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            output, error = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        if process.returncode:
            # The captured diagnostic is local-only, never repository evidence.
            print(error[-4000:], file=sys.stderr)
            raise RuntimeError(f"Research subprocess failed ({process.returncode})")
    return output


def setup(home: Path) -> None:
    """Explicitly provision pinned packages and Chromium outside the checkout.

    Inputs: external home and dependency lock. Output: a checked, ready runtime;
    an existing runtime is checked without reinstalling its packages.
    """
    import fcntl

    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    (home / "home").mkdir(exist_ok=True, mode=0o700)
    with (home / "setup.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = runtime(home)
        python = env / "bin/python"
        ready = env / "ready"
        if ready.exists():
            run_process([str(python), "-m", "pip", "check"], home, 60)
            return
        run_process([sys.executable, "-m", "venv", str(env)], home, 120)
        run_process(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "-r",
                str(BUILD_LOCK),
            ],
            home,
            1800,
        )
        run_process(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "--no-binary=nltk",
                "--no-build-isolation",
                "-r",
                str(LOCK),
            ],
            home,
            1800,
        )
        run_process([str(python), "-m", "pip", "check"], home, 60)
        run_process([str(python), "-m", "playwright", "install", "chromium"], home, 600)
        ready.write_text(VERSION + "\n", encoding="ascii")


def nltk_provenance() -> dict[str, str]:
    """Require the reviewed upstream source, not its identically versioned PyPI wheel.

    Inputs: installed NLTK distribution metadata. Output: verified archive identity;
    missing, malformed or mismatched provenance blocks research.
    """
    distribution = importlib.metadata.distribution("nltk")
    direct = json.loads(distribution.read_text("direct_url.json") or "null")
    if not isinstance(direct, dict) or direct.get("url") != NLTK_SOURCE_URL:
        raise RuntimeError("NLTK source provenance mismatch; run setup")
    archive = direct.get("archive_info")
    hashes = archive.get("hashes") if isinstance(archive, dict) else None
    if not isinstance(hashes, dict) or hashes.get("sha256") != NLTK_SOURCE_SHA256:
        raise RuntimeError("NLTK source digest mismatch; run setup")
    return {
        "version": distribution.version,
        "source_url": NLTK_SOURCE_URL,
        "sha256": NLTK_SOURCE_SHA256,
    }


def validate_url(url: str) -> str:
    """Admit explicit public HTTPS sources; never send secrets to discovery tools.

    Inputs: candidate URL and current DNS answers. Output: the unchanged URL or
    rejection of invalid syntax, credentials or non-public addresses.
    """
    if len(url) > 4096 or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("Invalid public source URL")
    parsed = urlsplit(url)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or "\\" in url
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError(
            "Use a public HTTPS URL without credentials, query, or fragment"
        )
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(row[4][0]).is_global for row in addresses
    ):
        raise ValueError("Research sources must resolve only to public addresses")
    return url


def write_capture(directory: Path, name: str, record: dict[str, object]) -> str:
    """Retain immutable owner-only evidence and return its exact byte digest.

    Inputs: private directory, filename and JSON record. Output: a new capture's
    SHA-256; existing evidence is never overwritten.
    """
    data = (json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n").encode()
    with (directory / name).open("xb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(data).hexdigest()


def capture_directory(home: Path, existing: str | None) -> Path:
    """Keep each invocation separate; workers may only reuse a private receipt.

    Inputs: external home and optional worker directory. Output: a new private
    directory or the validated owner-only directory supplied by its parent.
    """
    root = home / "receipts"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise ValueError("Research receipts must not use a symlink")
    if existing is None:
        return Path(tempfile.mkdtemp(prefix="read-", dir=root))
    directory = Path(existing)
    if (
        directory.is_symlink()
        or directory.resolve().parent != root.resolve()
        or not directory.is_dir()
        or directory.stat().st_uid != os.getuid()
        or directory.stat().st_mode & 0o077
    ):
        raise ValueError("Invalid private research receipt directory")
    return directory


def result_record(result: object, url: str, max_chars: int) -> dict[str, object]:
    """Fail closed on denied, empty, or failed extraction; label truncation.

    Inputs: native result, requested URL and character limit. Output: validated
    source metadata, bounded text and a digest of the complete extracted text.
    """
    status = getattr(result, "status_code", None)
    if (
        not getattr(result, "success", False)
        or not isinstance(status, int)
        or not 200 <= status < 300
    ):
        raise RuntimeError(
            f"Crawl4AI did not read the source successfully (HTTP {status})"
        )
    markdown = getattr(result, "markdown", None)
    content = getattr(markdown, "raw_markdown", "").strip()
    if not content:
        raise RuntimeError("Crawl4AI returned no source text")
    title = (getattr(result, "metadata", None) or {}).get("title", "")
    if str(title).strip().casefold() in {
        "just a moment...",
        "attention required! | cloudflare",
        "security verification",
        "verify you are human",
    }:
        raise RuntimeError("Crawl4AI reached a challenge, not the requested source")
    final_url = getattr(result, "redirected_url", None) or getattr(result, "url", url)
    if not isinstance(final_url, str):
        raise RuntimeError("Crawl4AI returned an invalid source identity")
    validate_url(final_url)
    return {
        "tool": "crawl4ai",
        "version": VERSION,
        "source_url": url,
        "final_url": final_url,
        "status": status,
        "success": getattr(result, "success", None),
        "error_message": getattr(result, "error_message", None),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "characters": len(content),
        "truncated": len(content) > max_chars,
        "markdown": content[:max_chars],
    }


async def read_source(
    url: str, max_chars: int, selector: str | None, receipt: Path
) -> dict[str, object]:
    """Use upstream extraction with TLS verification and robots policy enabled.

    Inputs: URL, output limit, selector and private receipt directory. Output:
    validated extraction metadata; native evidence survives rejected responses.
    """
    if importlib.metadata.version("crawl4ai") != VERSION:
        raise RuntimeError("Unexpected Crawl4AI runtime version; run setup")
    dependency = nltk_provenance()
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    validate_url(url)
    browser = BrowserConfig(
        headless=True,
        verbose=False,
        ignore_https_errors=False,
        accept_downloads=False,
        use_persistent_context=False,
        enable_stealth=False,
    )
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        check_robots_txt=True,
        page_timeout=45000,
        verbose=False,
        log_console=False,
        css_selector=selector,
        word_count_threshold=1,
        remove_overlay_elements=False,
    )
    async with AsyncWebCrawler(config=browser) as crawler:
        result = await crawler.arun(url=url, config=config)
    native = {
        "tool": "crawl4ai",
        "version": VERSION,
        "requested_url": url,
        "source_dependencies": {"nltk": dependency},
        "selector": selector,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "url": getattr(result, "url", None),
        "redirected_url": getattr(result, "redirected_url", None),
        "status_code": getattr(result, "status_code", None),
        "success": getattr(result, "success", None),
        "error_message": getattr(result, "error_message", None),
        "raw_markdown": getattr(
            getattr(result, "markdown", None), "raw_markdown", None
        ),
        "metadata": getattr(result, "metadata", None),
    }
    digest = write_capture(receipt, "native.json", native)
    record = result_record(result, url, max_chars)
    record.update(
        native_receipt=str(receipt / "native.json"),
        native_sha256=digest,
        source_dependencies={"nltk": dependency},
    )
    return record


def parser() -> argparse.ArgumentParser:
    """Keep the research surface explicit; no arbitrary configs or JS injection.

    Inputs: none. Output: the bounded reader command-line parser.
    """
    cli = argparse.ArgumentParser(description=__doc__, epilog=ATTRIBUTION)
    cli.add_argument("command", choices=("setup", "read", "worker"))
    cli.add_argument("url", nargs="?")
    cli.add_argument("--max-chars", type=int, default=12000)
    cli.add_argument("--selector")
    cli.add_argument("--receipt-dir", help=argparse.SUPPRESS)
    return cli


def main(argv: list[str] | None = None) -> int:
    """Provision explicitly or return a bounded, attributable source result.

    Inputs: command-line arguments. Output: zero with setup or research evidence,
    otherwise nonzero with retained failure diagnostics when storage is available.
    """
    args = parser().parse_args(argv)
    receipt = None
    try:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("Run this developer tool on Linux")
        if not 100 <= args.max_chars <= 100000:
            raise ValueError("max-chars must be between 100 and 100000")
        home = tool_home()
        if args.command == "setup":
            setup(home)
            print(f"Crawl4AI {VERSION} and Chromium ready")
            return 0
        if not args.url:
            raise ValueError("A public source URL is required")
        validate_url(args.url)
        if args.receipt_dir and args.command != "worker":
            raise ValueError("Only the isolated worker may reuse a receipt")
        receipt = capture_directory(home, args.receipt_dir)
        if not args.receipt_dir:
            write_capture(
                receipt,
                "request.json",
                {"url": args.url, "selector": args.selector, "version": VERSION},
            )
        if args.command == "worker":
            with contextlib.redirect_stdout(sys.stderr):
                result = asyncio.run(
                    read_source(args.url, args.max_chars, args.selector, receipt)
                )
            print(json.dumps(result, ensure_ascii=True))
            return 0
        env = runtime(home)
        if not (env / "ready").is_file():
            raise RuntimeError(
                "Crawl4AI is not provisioned; run tools/crawl4ai_research.py setup"
            )
        command = [
            str(env / "bin/python"),
            str(Path(__file__).resolve()),
            "worker",
            args.url,
            "--max-chars",
            str(args.max_chars),
            "--receipt-dir",
            str(receipt),
        ]
        if args.selector:
            command.extend(["--selector", args.selector])
        output = run_process(command, home, 90)
        record = json.loads(output)
        write_capture(receipt, "result.json", record)
        print(output.strip())
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        if receipt is not None:
            name = "worker-failure.json" if args.command == "worker" else "failure.json"
            try:
                write_capture(
                    receipt, name, {"exception": type(exc).__name__, "error": str(exc)}
                )
            except OSError as failure:
                print(f"Could not retain research failure: {failure}", file=sys.stderr)
            print(f"Research evidence: {receipt}", file=sys.stderr)
        print(f"Crawl4AI research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
