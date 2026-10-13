"""Source-bound false-positive approvals must never admit unrelated findings."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml

from tools import sarif_result_guard as guard


@pytest.fixture
def reviewed(tmp_path):
    """Inputs: isolated checkout. Output: genuine source-bound approval fixtures."""
    rule = "example.directory-rule"
    source = tmp_path / "directory.py"
    source.write_text(f"# nosemgrep: {rule}\napply_directory_permissions()\n")
    result = {
        "ruleId": rule,
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": source.name, "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": 2, "endLine": 2},
                }
            }
        ],
        "suppressions": [{"kind": "inSource"}],
    }
    policy = {
        "schema": 1,
        "tool": "Semgrep OSS",
        "version": "1.179.0",
        "findings": [
            {
                "rule_id": rule,
                "path": source.name,
                "line": 2,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "reason": "Reviewed directory contract.",
            }
        ],
    }
    payload = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": policy["tool"],
                        "semanticVersion": policy["version"],
                    }
                },
                "invocations": [{"executionSuccessful": True}],
                "results": [result],
            }
        ],
    }
    return source, policy, payload


def run_guard(monkeypatch, tmp_path, reviewed, *, approval=True, extra_report=False):
    """Inputs: mutable fixtures. Output: real CLI status and unchanged raw bytes."""
    _, policy, payload = reviewed
    manifest, report = tmp_path / "reviewed.json", tmp_path / "raw.sarif"
    manifest.write_text(json.dumps(policy))
    report.write_text(json.dumps(payload))
    before = report.read_bytes()
    arguments = ["sarif_result_guard.py", str(report)]
    if extra_report:
        arguments.append(str(report))
    if approval:
        arguments += ["--reviewed-suppressions", str(manifest)]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", arguments)
    status = guard.main()
    assert report.read_bytes() == before
    return status


def test_exact_approval_preserves_raw_and_requires_explicit_option(
    monkeypatch, tmp_path, reviewed, capsys
):
    """Inputs: matching approval and CLI options. Output: opt-in admission only."""
    assert run_guard(monkeypatch, tmp_path, reviewed) == 0
    assert "1 verified native suppression(s)" in capsys.readouterr().out
    assert run_guard(monkeypatch, tmp_path, reviewed, approval=False) == 1
    assert run_guard(monkeypatch, tmp_path, reviewed, extra_report=True) == 2


@pytest.mark.parametrize(
    "change", ["hash", "annotation", "missing", "symlink", "parent-symlink"]
)
def test_changed_or_indirect_source_is_rejected(
    monkeypatch, tmp_path, reviewed, change
):
    """Inputs: altered or redirected source. Output: closed approval failure."""
    source, policy, _ = reviewed
    if change == "hash":
        source.write_text(source.read_text() + "changed()\n")
    elif change == "annotation":
        source.write_text("# different annotation\napply_directory_permissions()\n")
        policy["findings"][0]["sha256"] = hashlib.sha256(
            source.read_bytes()
        ).hexdigest()
    else:
        target = source.with_name("moved.py")
        source.rename(target)
        if change == "symlink":
            source.symlink_to(target)
        elif change == "parent-symlink":
            (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
            policy["findings"][0]["path"] = "alias/moved.py"
    assert run_guard(monkeypatch, tmp_path, reviewed) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../directory.py"),
        ("path", "/directory.py"),
        ("path", "./directory.py"),
        ("path", "a//b"),
        ("path", "a\\b"),
        ("path", "https:example"),
        ("path", []),
        ("rule_id", ""),
        ("line", True),
        ("line", "2"),
        ("line", 1),
        ("line", 99),
        ("sha256", "0" * 64),
        ("reason", " "),
    ],
)
def test_invalid_finding_fields_fail_closed(
    monkeypatch, tmp_path, reviewed, field, value
):
    """Inputs: invalid approval fields. Output: rejection before report admission."""
    reviewed[1]["findings"][0][field] = value
    assert run_guard(monkeypatch, tmp_path, reviewed) == 2


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "boolean-schema",
        "tool",
        "version",
        "empty",
        "non-list",
        "non-object",
        "extra-field",
        "duplicate",
        "missing-field",
        "invalid-record",
    ],
)
def test_malformed_policy_fails_closed(monkeypatch, tmp_path, reviewed, change):
    """Inputs: malformed policy structures. Output: no permissive interpretation."""
    source, policy, payload = reviewed
    if change == "schema":
        policy["schema"] = 2
    elif change == "boolean-schema":
        policy["schema"] = True
    elif change in ("tool", "version"):
        policy[change] = ""
    elif change == "empty":
        policy["findings"] = []
    elif change == "non-list":
        policy["findings"] = {}
    elif change == "non-object":
        policy = []
    elif change == "extra-field":
        policy["extra"] = True
    elif change == "duplicate":
        policy["findings"] *= 2
    elif change == "missing-field":
        del policy["findings"][0]["reason"]
    else:
        policy["findings"] = [None]
    assert run_guard(monkeypatch, tmp_path, (source, policy, payload)) == 2


@pytest.mark.parametrize(
    "change",
    [
        "tool",
        "version",
        "failed",
        "no-invocations",
        "invalid-invocation",
        "two-runs",
        "missing-tool",
        "wrong-rule",
        "wrong-path",
        "wrong-line",
        "wrong-base",
        "wide-region",
        "invalid-key",
        "boolean-line",
        "missing-location",
        "two-locations",
        "no-physical",
        "non-object-location",
        "non-list-locations",
        "missing-native-suppression",
        "other-suppression",
        "missing-result",
    ],
)
def test_report_identity_and_exact_native_match_are_required(
    monkeypatch, tmp_path, reviewed, change
):
    """Inputs: mismatched scanner evidence. Output: an explicit validation failure."""
    run = reviewed[2]["runs"][0]
    result = run["results"][0]
    physical = result["locations"][0]["physicalLocation"]
    if change in ("tool", "version"):
        run["tool"]["driver"]["name" if change == "tool" else "semanticVersion"] = (
            "other"
        )
    elif change == "failed":
        run["invocations"][0]["executionSuccessful"] = False
    elif change == "no-invocations":
        run["invocations"] = []
    elif change == "invalid-invocation":
        run["invocations"] = [None]
    elif change == "two-runs":
        reviewed[2]["runs"].append(deepcopy(run))
    elif change == "missing-tool":
        del run["tool"]
    elif change == "wrong-rule":
        result["ruleId"] = "other"
    elif change == "wrong-path":
        physical["artifactLocation"]["uri"] = "other.py"
    elif change in ("wrong-line", "boolean-line"):
        physical["region"]["startLine"] = 3 if change == "wrong-line" else True
    elif change == "wrong-base":
        physical["artifactLocation"]["uriBaseId"] = "%OTHER%"
    elif change == "wide-region":
        physical["region"]["endLine"] = 3
    elif change == "invalid-key":
        result["ruleId"] = []
    elif change == "missing-location":
        result["locations"] = []
    elif change == "two-locations":
        result["locations"] *= 2
    elif change == "no-physical":
        result["locations"] = [{}]
    elif change == "non-object-location":
        result["locations"] = [None]
    elif change == "non-list-locations":
        result["locations"] = {}
    elif change == "missing-native-suppression":
        result.pop("suppressions")
    elif change == "other-suppression":
        result["suppressions"] = [{"kind": "external"}]
    else:
        run["results"] = []
    assert run_guard(monkeypatch, tmp_path, reviewed) == 2


@pytest.mark.parametrize(
    "additional", ["duplicate", "different", "native-but-unapproved"]
)
def test_additional_results_always_block(monkeypatch, tmp_path, reviewed, additional):
    """Inputs: duplicate or unrelated findings. Output: a blocked upload."""
    extra = deepcopy(reviewed[2]["runs"][0]["results"][0])
    if additional != "duplicate":
        extra["ruleId"] = "different-rule"
    if additional == "different":
        extra.pop("suppressions")
    reviewed[2]["runs"][0]["results"].append(extra)
    assert run_guard(monkeypatch, tmp_path, reviewed) == 1


@pytest.mark.parametrize("content", [None, "not json"])
def test_unreadable_policy_fails_closed(tmp_path, content):
    """Inputs: absent or malformed manifest. Output: a bounded validation error."""
    manifest = tmp_path / "manifest.json"
    if content is not None:
        manifest.write_text(content)
    with pytest.raises(guard.SarifValidationError, match="cannot verify"):
        guard.reviewed_suppressions(tmp_path / "scan.sarif", manifest, tmp_path)


def test_repository_approval_is_limited_to_two_directory_modes(tmp_path):
    """Inputs: committed approvals and workflow. Output: exact reviewed scope."""
    root = Path(__file__).resolve().parents[1]
    manifest = root / ".github/semgrep-reviewed-findings.json"
    policy = json.loads(manifest.read_text())
    assert len(policy["findings"]) == 2
    assert {item["path"] for item in policy["findings"]} == {
        "tools/prepare_quota_directories.py"
    }
    assert {item["rule_id"] for item in policy["findings"]} == {
        "python.lang.security.audit.insecure-file-permissions.insecure-file-permissions"
    }
    report = tmp_path / "scanner.sarif"
    report.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": policy["tool"],
                                "semanticVersion": policy["version"],
                            }
                        },
                        "invocations": [{"executionSuccessful": True}],
                    }
                ]
            }
        )
    )
    assert len(guard.reviewed_suppressions(report, manifest, root)) == 2
    source = (root / policy["findings"][0]["path"]).read_text().splitlines()
    assert [source[item["line"] - 1].strip() for item in policy["findings"]] == [
        "os.fchmod(admin, 0o1770)  # nosec B103",
        "os.fchmod(quota, 0o700)",
    ]
    workflow = yaml.safe_load(
        (root / ".github/workflows/security-code-scanning.yml").read_text()
    )
    commands = [
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]
    assert sum("--reviewed-suppressions" in command for command in commands) == 1
