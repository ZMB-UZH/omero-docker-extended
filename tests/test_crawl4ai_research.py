"""Offline reader boundaries plus actual process isolation and timeout tests."""

import asyncio
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from tools import crawl4ai_research as reader
from tools import source_advisory_guard


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Inputs: DNS patch fixture. Output: deterministic public answers without network I/O."""
    monkeypatch.setattr(
        reader.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.org/",  # DevSkim: ignore DS137138 -- rejected plaintext fixture; never connected
        "file:///etc/passwd",
        "https://user:secret@docs.example.org/",
        "https://docs.example.org:8443/",
        "https://docs.example.org/?token=value",
        "https://docs.example.org/#part",
        "https://docs.example.org\\internal/",
        "https://docs.example.org/\n",
        "https:///missing",
        "https://docs.example.org:invalid/",
        "https://docs.example.org/" + "a" * 4096,
    ],
)
def test_rejects_invalid_or_credential_bearing_sources(url):
    """Inputs: unsafe URL shapes. Output: validation refuses every candidate."""
    with pytest.raises(ValueError):
        reader.validate_url(url)


@pytest.mark.parametrize(
    "addresses",
    [
        [],
        ["127.0.0.1"],
        ["::1"],
        ["169.254.169.254"],
        ["10.0.0.1"],
        ["8.8.8.8", "192.168.0.1"],
    ],
)
def test_private_or_mixed_dns_is_rejected(addresses, monkeypatch):
    """Inputs: absent or non-public DNS answers. Output: no address mixture is accepted."""
    monkeypatch.setattr(
        reader.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
        ],
    )
    with pytest.raises(ValueError, match="public addresses"):
        reader.validate_url("https://docs.example.org/")


def test_valid_source_and_dns_failure():
    """Inputs: public URL or failed DNS lookup. Output: URL preservation or visible failure."""
    url = "https://docs.example.org/guide"
    assert reader.validate_url(url) == url
    with mock.patch.object(
        reader.socket, "getaddrinfo", side_effect=socket.gaierror("unavailable")
    ):
        with pytest.raises(socket.gaierror):
            reader.validate_url(url)


def test_external_home_validates_symlinks_and_relative_paths(tmp_path, monkeypatch):
    """Inputs: overlapping, relative and symlinked roots. Output: only external state is admitted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(reader, "ROOT", repo)
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", "relative")
    with pytest.raises(ValueError):
        reader.tool_home()
    for path in (repo, repo / "cache", repo.parent, Path("/")):
        monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(path))
        with pytest.raises(ValueError):
            reader.tool_home()
    link = tmp_path / "redirect"
    link.symlink_to(repo, target_is_directory=True)
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(link / "cache"))
    with pytest.raises(ValueError):
        reader.tool_home()
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path / "external"))
    assert reader.tool_home() == tmp_path / "external"


@pytest.mark.parametrize("lock_name", ["LOCK", "BUILD_LOCK"])
def test_lock_change_selects_a_different_environment(tmp_path, monkeypatch, lock_name):
    """Inputs: changed lock bytes. Output: the previous runtime cannot be reused."""
    lock = tmp_path / "requirements.txt"
    lock.write_text("first")
    monkeypatch.setattr(reader, lock_name, lock)
    before = reader.runtime(tmp_path)
    lock.write_text("second")
    assert reader.runtime(tmp_path) != before


def test_child_does_not_receive_credentials_or_personal_home(tmp_path, monkeypatch):
    """Inputs: parent secrets and a real child process. Output: secrets and personal home stay out."""
    monkeypatch.setenv("UNRELATED_API_KEY", "private-value")
    monkeypatch.setenv("HTTPS_PROXY", "private-proxy-value")
    env = reader.child_environment(tmp_path)
    assert "UNRELATED_API_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["HOME"] == str(tmp_path / "home")
    assert env["PYTHONNOUSERSITE"] == "1"
    assert (
        reader.run_process(
            [
                sys.executable,
                "-c",
                "import os; print(os.getenv('UNRELATED_API_KEY', 'absent'))",
            ],
            tmp_path,
            10,
        ).strip()
        == "absent"
    )


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {},
        {"url": "https://example.org/unreviewed.tar.gz"},
        {"url": reader.NLTK_SOURCE_URL, "archive_info": []},
        {"url": reader.NLTK_SOURCE_URL, "archive_info": {"hashes": []}},
        {
            "url": reader.NLTK_SOURCE_URL,
            "archive_info": {"hashes": {"sha256": "wrong"}},
        },
    ],
)
def test_nltk_rejects_unreviewed_installed_source(monkeypatch, record):
    """Inputs: missing or altered source metadata. Output: no accepted NLTK provenance."""
    distribution = SimpleNamespace(
        read_text=lambda name: json.dumps(record), version="3.10.3"
    )
    monkeypatch.setattr(
        reader.importlib.metadata, "distribution", lambda name: distribution
    )
    with pytest.raises(RuntimeError, match="NLTK source"):
        reader.nltk_provenance()


def test_nltk_requires_the_reviewed_archive_digest(monkeypatch):
    """Inputs: exact upstream archive metadata. Output: version and source digest retained."""
    record = {
        "url": reader.NLTK_SOURCE_URL,
        "archive_info": {"hashes": {"sha256": reader.NLTK_SOURCE_SHA256}},
    }
    distribution = SimpleNamespace(
        read_text=lambda name: json.dumps(record), version="3.10.3"
    )
    monkeypatch.setattr(
        reader.importlib.metadata, "distribution", lambda name: distribution
    )
    assert reader.nltk_provenance() == {
        "version": "3.10.3",
        "source_url": reader.NLTK_SOURCE_URL,
        "sha256": reader.NLTK_SOURCE_SHA256,
    }
    distribution.read_text = lambda name: "invalid JSON"
    with pytest.raises(ValueError):
        reader.nltk_provenance()


def test_nltk_lock_matches_runtime_provenance():
    """Inputs: compiled dependency lock. Output: source URL and hash match runtime checks."""
    locked = reader.LOCK.read_text()
    assert f"nltk @ {reader.NLTK_SOURCE_URL}" in locked
    assert f"--hash=sha256:{reader.NLTK_SOURCE_SHA256}" in locked
    build = reader.BUILD_LOCK.read_text()
    assert "\nsetuptools==84.0.0 \\" in build
    assert "--hash=sha256:" in build


def test_source_dependency_remains_in_scanner_inventory():
    """Inputs: source lock, SBOM and workflow. Output: exact provenance stays scannable."""
    inventory_path = ".github/requirements/crawl4ai-source/nltk.cdx.xml"
    source_advisory_guard.check_inventory(
        reader.ROOT / inventory_path,
        {
            "source_revision": reader.NLTK_SOURCE_URL.rsplit("/", 1)[1].removesuffix(
                ".tar.gz"
            ),
            "archive_url": reader.NLTK_SOURCE_URL,
            "archive_sha256": reader.NLTK_SOURCE_SHA256,
        },
    )
    workflow = (
        reader.ROOT / ".github/workflows/security-code-scanning.yml"
    ).read_text()
    assert f"--lockfile={inventory_path}" in workflow


def test_real_process_failure_and_timeout_are_not_success(tmp_path, capsys):
    """Inputs: failing and sleeping processes. Output: diagnostics and bounded failure, not success."""
    with pytest.raises(RuntimeError, match="failed"):
        reader.run_process(
            [
                sys.executable,
                "-c",
                "import sys; print('diagnostic', file=sys.stderr); sys.exit(7)",
            ],
            tmp_path,
            10,
        )
    assert "diagnostic" in capsys.readouterr().err
    with pytest.raises(subprocess.TimeoutExpired):
        reader.run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 1
        )


def page(**changes):
    """Inputs: selected native-result overrides. Output: a minimal crawler result fixture."""
    defaults = dict(
        success=True,
        error_message="",
        status_code=200,
        markdown=SimpleNamespace(raw_markdown="x" * 200),
        url="https://docs.example.org/guide",
        redirected_url=None,
        metadata={"title": "Title"},
    )
    defaults.update(changes)
    return SimpleNamespace(**defaults)


def test_truncation_is_explicit_and_digest_covers_full_content():
    """Inputs: identical content with different display limits. Output: stable full-text digests."""
    long = reader.result_record(page(), "https://docs.example.org/guide", 100)
    short = reader.result_record(page(), "https://docs.example.org/guide", 1000)
    assert long["truncated"] is True and short["truncated"] is False
    assert len(long["markdown"]) == 100 and long["characters"] == 200
    assert long["sha256"] == short["sha256"]
    assert long["title"] == "Title"


@pytest.mark.parametrize(
    "changes",
    [
        dict(success=False),
        dict(status_code=403),
        dict(status_code=429),
        dict(status_code=500),
        dict(status_code=None),
        dict(markdown=None),
        dict(markdown=SimpleNamespace(raw_markdown="  ")),
        dict(metadata={"title": "Just a moment..."}),
    ],
)
def test_failed_denied_empty_results_are_not_research(changes):
    """Inputs: denied, challenged or empty native results. Output: no accepted research record."""
    with pytest.raises(RuntimeError):
        reader.result_record(page(**changes), "https://docs.example.org/guide", 100)


def test_final_url_must_also_meet_source_policy():
    """Inputs: an HTTPS source redirected to HTTP. Output: the final identity is rejected."""
    with pytest.raises(ValueError):
        reader.result_record(
            page(
                redirected_url="http://docs.example.org/",  # DevSkim: ignore DS137138 -- rejected redirect fixture; never connected
            ),
            "https://docs.example.org/guide",
            100,
        )


def test_result_without_source_identity_is_rejected():
    """Inputs: result without a URL. Output: explicit source-identity failure."""
    with pytest.raises(RuntimeError, match="source identity"):
        reader.result_record(page(url=None), "https://docs.example.org/guide", 100)


@pytest.mark.parametrize("failure", [None, "denied", "empty", "challenge"])
def test_public_api_configuration_and_close_on_failure(tmp_path, monkeypatch, failure):
    """Inputs: instrumented crawler outcomes. Output: safe settings, closed browser and native evidence."""
    configs = {}
    closed = []
    dependency = {
        "source_url": reader.NLTK_SOURCE_URL,
        "sha256": reader.NLTK_SOURCE_SHA256,
    }
    monkeypatch.setattr(reader, "nltk_provenance", lambda: dependency)

    class Crawler:
        def __init__(self, config):
            """Inputs: browser settings. Output: settings retained for contract assertions."""
            configs["browser"] = vars(config)

        async def __aenter__(self):
            """Inputs: fixture crawler. Output: the active context instance."""
            return self

        async def __aexit__(self, *args):
            """Inputs: context exit details. Output: a recorded resource-close event."""
            closed.append(True)

        async def arun(self, url, config):
            """Inputs: source and run settings. Output: the selected native failure or success."""
            configs["crawler"] = vars(config)
            assert url == "https://docs.example.org/guide"
            if failure == "denied":
                return page(
                    success=False, status_code=403, error_message="robots denied"
                )
            if failure == "empty":
                return page(markdown=None)
            if failure == "challenge":
                return page(metadata={"title": "Verify you are human"})
            return page()

    monkeypatch.setitem(
        sys.modules,
        "crawl4ai",
        SimpleNamespace(
            AsyncWebCrawler=Crawler,
            BrowserConfig=SimpleNamespace,
            CrawlerRunConfig=SimpleNamespace,
            CacheMode=SimpleNamespace(BYPASS="fresh"),
        ),
    )
    monkeypatch.setattr(
        reader.importlib.metadata, "version", lambda name: reader.VERSION
    )
    operation = reader.read_source(
        "https://docs.example.org/guide", 100, "article", tmp_path
    )
    if failure:
        with pytest.raises(RuntimeError):
            asyncio.run(operation)
        saved = json.loads((tmp_path / "native.json").read_bytes())
        assert closed == [True]
        if failure == "denied":
            assert saved["success"] is False
            assert (
                saved["status_code"] == 403
                and saved["error_message"] == "robots denied"
            )
        elif failure == "empty":
            assert saved["raw_markdown"] is None
        else:
            assert saved["metadata"]["title"] == "Verify you are human"
        return
    result = asyncio.run(operation)
    assert result["truncated"] and closed == [True]
    assert configs["browser"]["ignore_https_errors"] is False
    assert configs["browser"]["enable_stealth"] is False
    assert configs["browser"]["use_persistent_context"] is False
    assert configs["browser"]["accept_downloads"] is False
    assert configs["crawler"]["check_robots_txt"] is True
    assert configs["crawler"]["cache_mode"] == "fresh"
    assert configs["crawler"]["css_selector"] == "article"
    native = tmp_path / "native.json"
    assert result["native_sha256"] == hashlib.sha256(native.read_bytes()).hexdigest()
    saved = json.loads(native.read_bytes())
    assert saved["success"] is True and saved["error_message"] == ""
    assert saved["source_dependencies"] == {"nltk": dependency}
    assert len(saved["raw_markdown"]) == 200
    assert native.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(reader.importlib.metadata, "version", lambda name: "old")
    with pytest.raises(RuntimeError, match="version"):
        asyncio.run(
            reader.read_source("https://docs.example.org/guide", 100, None, tmp_path)
        )


def test_setup_is_hash_pinned_idempotent_and_not_an_application_install(
    tmp_path, monkeypatch
):
    """Inputs: empty then ready runtime. Output: pinned provisioning once, dependency check on reuse."""
    env = tmp_path / "isolated-runtime"
    monkeypatch.setattr(reader, "runtime", lambda home: env)
    commands = []

    def run(command, home, timeout):
        """Inputs: setup subprocess request. Output: recorded argv and simulated runtime creation."""
        commands.append(command)
        assert home == tmp_path
        if "venv" in command:
            env.mkdir()
        return "ok"

    monkeypatch.setattr(reader, "run_process", run)
    reader.setup(tmp_path)
    build = next(cmd for cmd in commands if str(reader.BUILD_LOCK) in cmd)
    install = next(cmd for cmd in commands if str(reader.LOCK) in cmd)
    assert commands.index(build) < commands.index(install)
    assert "--require-hashes" in build and "--only-binary=:all:" in build
    assert "--no-build-isolation" in install and "--no-binary=nltk" in install
    assert "--only-binary=:all:" in install and str(reader.LOCK) in install
    assert any(cmd[-3:] == ["playwright", "install", "chromium"] for cmd in commands)
    assert (env / "ready").read_text().strip() == reader.VERSION
    commands.clear()
    reader.setup(tmp_path)
    assert commands == [[str(env / "bin/python"), "-m", "pip", "check"]]


def test_cli_requires_provisioning_and_bounded_input(tmp_path, monkeypatch):
    """Inputs: missing setup, URL, limits or Linux support. Output: every invalid request fails."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path / "external"))
    assert reader.main(["read"]) == 1
    assert reader.main(["read", "https://docs.example.org/", "--max-chars", "0"]) == 1
    assert reader.main(["read", "https://docs.example.org/"]) == 1
    monkeypatch.setattr(reader.sys, "platform", "unsupported")
    assert reader.main(["setup"]) == 1


def test_cli_worker_outputs_only_structured_evidence(tmp_path, monkeypatch, capsys):
    """Inputs: noisy crawler output. Output: stdout remains JSON and logs go to stderr."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path / "external"))

    async def source(url, count, selector, receipt):
        """Inputs: worker request. Output: extraction fixture plus simulated upstream logging."""
        print("upstream log")
        return {"tool": "crawl4ai", "markdown": "evidence"}

    monkeypatch.setattr(reader, "read_source", source)
    assert reader.main(["worker", "https://docs.example.org/"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["markdown"] == "evidence"
    assert "upstream log" in captured.err


def test_cli_setup_reports_only_after_success(tmp_path, monkeypatch, capsys):
    """Inputs: successful setup callback. Output: ready message follows the expected provision call."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path / "external"))
    with mock.patch.object(reader, "setup") as setup:
        assert reader.main(["setup"]) == 0
    setup.assert_called_once_with(tmp_path / "external")
    assert "ready" in capsys.readouterr().out


@pytest.mark.parametrize("selector", [None, "article > section"])
def test_cli_uses_qualified_runtime_and_preserves_arguments(
    tmp_path, monkeypatch, selector, capsys
):
    """Inputs: ready runtime and optional selector. Output: exact worker argv and retained results."""
    env = tmp_path / "env"
    env.mkdir()
    (env / "ready").write_text(reader.VERSION)
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path))
    monkeypatch.setattr(reader, "runtime", lambda home: env)
    args = ["read", "https://docs.example.org/guide"]
    if selector:
        args.extend(["--selector", selector])
    with mock.patch.object(
        reader, "run_process", return_value='{"markdown": "source"}'
    ) as run:
        assert reader.main(args) == 0
    command, home, timeout = run.call_args.args
    assert command[0] == str(env / "bin/python")
    assert home == tmp_path and timeout == 90
    if selector:
        assert command[-2:] == ["--selector", selector]
    assert json.loads(capsys.readouterr().out)["markdown"] == "source"
    saved = list((tmp_path / "receipts").glob("read-*/result.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_bytes())["markdown"] == "source"


def test_capture_directories_are_private_unique_and_cannot_escape(tmp_path):
    """Inputs: new and unsafe receipt paths. Output: unique private directories and rejected escapes."""
    first = reader.capture_directory(tmp_path, None)
    second = reader.capture_directory(tmp_path, None)
    assert first != second
    assert first.stat().st_mode & 0o777 == 0o700
    assert reader.capture_directory(tmp_path, str(first)) == first
    for invalid in (tmp_path, first / "missing"):
        with pytest.raises(ValueError):
            reader.capture_directory(tmp_path, str(invalid))
    link = first.parent / "link"
    link.symlink_to(first, target_is_directory=True)
    with pytest.raises(ValueError):
        reader.capture_directory(tmp_path, str(link))
    first.chmod(0o755)
    with pytest.raises(ValueError):
        reader.capture_directory(tmp_path, str(first))
    with mock.patch.object(reader.os, "getuid", return_value=-1):
        with pytest.raises(ValueError):
            reader.capture_directory(tmp_path, str(second))


def test_receipt_root_symlink_is_rejected(tmp_path):
    """Inputs: symlinked receipt root. Output: capture allocation refuses redirection."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "receipts").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        reader.capture_directory(home, None)


def test_capture_never_overwrites_evidence(tmp_path):
    """Inputs: two writes to one evidence name. Output: original bytes survive the refused overwrite."""
    reader.write_capture(tmp_path, "native.json", {"success": False})
    with pytest.raises(FileExistsError):
        reader.write_capture(tmp_path, "native.json", {"success": True})
    assert json.loads((tmp_path / "native.json").read_bytes()) == {"success": False}


def test_worker_failure_retains_native_record_before_rejection(tmp_path, monkeypatch):
    """Inputs: robots-denied worker. Output: native denial and failure diagnostics both persist."""

    async def source(url, count, selector, receipt):
        """Inputs: worker receipt. Output: saved native denial followed by a rejection error."""
        reader.write_capture(
            receipt, "native.json", {"success": False, "error_message": "robots denied"}
        )
        raise RuntimeError("robots denied")

    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path))
    monkeypatch.setattr(reader, "read_source", source)
    assert reader.main(["worker", "https://docs.example.org/"]) == 1
    saved = next((tmp_path / "receipts").glob("read-*/worker-failure.json"))
    assert json.loads(saved.read_bytes())["error"] == "robots denied"
    assert json.loads(saved.with_name("native.json").read_bytes())["success"] is False


def test_worker_receipt_argument_cannot_be_used_for_public_read(tmp_path, monkeypatch):
    """Inputs: public read with a worker-only path. Output: reuse is denied before crawling."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path))
    assert (
        reader.main(
            ["read", "https://docs.example.org/", "--receipt-dir", str(tmp_path)]
        )
        == 1
    )


def test_isolated_worker_preserves_parent_request_receipt(tmp_path, monkeypatch):
    """Inputs: existing parent request and worker arguments. Output: unchanged request bytes."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path))
    directory = reader.capture_directory(tmp_path, None)
    request = {"url": "https://docs.example.org/", "selector": "article"}
    digest = reader.write_capture(directory, "request.json", request)

    async def source(url, count, selector, receipt):
        """Inputs: forwarded source and selector. Output: evidence only for the exact parent request."""
        assert receipt == directory
        assert url == request["url"] and selector == "article"
        return {"tool": "crawl4ai", "markdown": "source"}

    monkeypatch.setattr(reader, "read_source", source)
    assert (
        reader.main(
            [
                "worker",
                request["url"],
                "--selector",
                "article",
                "--receipt-dir",
                str(directory),
            ]
        )
        == 0
    )
    assert (
        hashlib.sha256((directory / "request.json").read_bytes()).hexdigest() == digest
    )


def test_receipt_write_failure_does_not_hide_original_failure(
    tmp_path, monkeypatch, capsys
):
    """Inputs: unavailable evidence storage. Output: nonzero status and visible recording failure."""
    monkeypatch.setenv("AGENT_CRAWL4AI_HOME", str(tmp_path))
    monkeypatch.setattr(
        reader, "write_capture", mock.Mock(side_effect=OSError("disk full"))
    )
    assert reader.main(["read", "https://docs.example.org/"]) == 1
    assert "Could not retain research failure" in capsys.readouterr().err


def test_reader_cli_entrypoint_is_usable_without_runtime(monkeypatch):
    """Inputs: real reader help entrypoint. Output: successful usage without a crawler runtime."""
    import runpy

    monkeypatch.setattr(reader.sys, "argv", ["crawl4ai_research.py", "--help"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(
            str(reader.ROOT / "tools/crawl4ai_research.py"), run_name="__main__"
        )
    assert result.value.code == 0
