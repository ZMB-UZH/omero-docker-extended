"""Repository-prefix lookup must identify the active store and close its session."""

from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

from startup import repo_root_sync_helper as helper


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    """Inputs: isolated API boundary. Output: connection and store-specific model fixtures."""
    root = tmp_path / "managed"
    root.mkdir()
    descriptions = [
        SimpleNamespace(path=None, name=None, hash=None),
        SimpleNamespace(path=str(tmp_path), name="elsewhere", hash="old-store"),
        SimpleNamespace(
            _path=SimpleNamespace(val=str(tmp_path) + "/"),
            _name=SimpleNamespace(val="managed"),
            _hash=SimpleNamespace(val="active-store"),
        ),
    ]
    conn = Mock()
    conn.connect.return_value = True
    conn.c.sf.sharedResources.return_value.repositories.return_value = SimpleNamespace(
        descriptions=descriptions
    )
    conn.getObjects.return_value = []
    factory = Mock(return_value=conn)
    module = ModuleType("omero.gateway")
    module.BlitzGateway = factory
    monkeypatch.setitem(sys.modules, "omero.gateway", module)
    return conn, factory, root, descriptions


@pytest.mark.parametrize(
    "prefix,parent", [("group", "/"), ("shared/group", "/shared/")]
)
def test_lookup_requires_both_active_repository_and_exact_parent(
    gateway, capsys, prefix, parent
):
    """Inputs: colliding names in different stores/parents. Output: only the exact object wins."""
    conn, factory, root, _ = gateway
    objects = []
    for identity, path, repo in (
        (11, parent, "old-store"),
        (12, "/different/", "active-store"),
        (13, parent, "active-store"),
    ):
        obj = Mock()
        obj.getId.return_value = identity
        obj.getPath.return_value = path
        obj.getRepo.return_value = repo
        obj.getOwnerOmeName.return_value = "fixture-owner"
        objects.append(obj)
    conn.getObjects.return_value = iter(objects)
    assert (
        helper.lookup_prefix(
            "fixture-password", "service.example", 14064, prefix, str(root)
        )
        == 0
    )
    assert capsys.readouterr().out == "FOUND|13|fixture-owner|active-store\n"
    factory.assert_called_once_with(
        "root", "fixture-password", host="service.example", port=14064
    )
    conn.SERVICE_OPTS.setOmeroGroup.assert_called_once_with("-1")
    conn.getObjects.assert_called_once_with(
        "OriginalFile", attributes={"name": "group"}
    )
    conn.close.assert_called_once_with()


def test_missing_prefix_is_not_a_connection_failure(gateway, capsys):
    """Inputs: healthy store with no requested directory. Output: explicit MISSING and closed session."""
    conn, _, root, _ = gateway
    assert (
        helper.lookup_prefix("unused", "service.example", 14064, "group", str(root))
        == 0
    )
    assert capsys.readouterr().out == "MISSING\n"
    conn.close.assert_called_once_with()


@pytest.mark.parametrize(
    "failure", ["connect", "repository", "empty_uuid", "wrapped_empty_uuid"]
)
def test_lookup_unavailable_connection_or_store_fails_closed(gateway, capsys, failure):
    """Inputs: unavailable connection/store identity. Output: failure before any directory query."""
    conn, _, root, descriptions = gateway
    if failure == "connect":
        conn.connect.return_value = False
    elif failure == "repository":
        descriptions.clear()
    elif failure == "empty_uuid":
        descriptions[-1]._hash = None
    else:
        descriptions[-1]._hash.val = None
    assert (
        helper.lookup_prefix("unused", "service.example", 14064, "group", str(root))
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR:" in captured.err
    conn.getObjects.assert_not_called()
    conn.close.assert_called_once_with()


def test_query_failure_closes_session_without_fabricating_missing(gateway, capsys):
    """Inputs: query transport failure. Output: original failure survives and the session closes."""
    conn, _, root, _ = gateway
    conn.getObjects.side_effect = ConnectionError("fixture transport failure")
    with pytest.raises(ConnectionError, match="fixture transport failure"):
        helper.lookup_prefix("unused", "service.example", 14064, "group", str(root))
    assert capsys.readouterr().out == ""
    conn.close.assert_called_once_with()


def test_close_failure_preserves_result_without_disclosing_exception_text(
    gateway, capsys
):
    """Inputs: shutdown exception with sensitive-looking details. Output: safe warning and correct result."""
    conn, _, root, _ = gateway
    conn.close.side_effect = RuntimeError("private fixture connection details")
    assert (
        helper.lookup_prefix("unused", "service.example", 14064, "group", str(root))
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "MISSING\n"
    assert "RuntimeError" in captured.err
    assert "private fixture connection details" not in captured.err


@pytest.mark.parametrize("prefix,root", [("/", "/managed"), ("group", "relative")])
def test_invalid_lookup_arguments_never_connect(gateway, capsys, prefix, root):
    """Inputs: invalid directory contract. Output: usage failure before credentials reach the gateway."""
    _, factory, _, _ = gateway
    assert helper.lookup_prefix("unused", "service.example", 14064, prefix, root) == 2
    assert "ERROR:" in capsys.readouterr().err
    factory.assert_not_called()


def test_missing_python_bindings_reports_failure(monkeypatch, capsys):
    """Inputs: missing optional OMERO binding. Output: explicit diagnostic and failure status."""
    monkeypatch.setitem(sys.modules, "omero.gateway", None)
    assert (
        helper.lookup_prefix("unused", "service.example", 14064, "group", "/managed")
        == 1
    )
    assert "failed to import OMERO Python bindings" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value", ["", ".", "..", "group/path", "group\\path", "nul\x00value"]
)
def test_group_path_components_reject_escape_and_empty_names(value):
    """Inputs: invalid deployment group names. Output: no usable repository seed is produced."""
    with pytest.raises(ValueError, match="Invalid"):
        helper._validate_path_component(value, "fixture")


@pytest.mark.parametrize("template", ["", "root/%unknown%/%user%", "broken%/x/%user%"])
def test_unresolvable_stable_template_is_rejected(template):
    """Inputs: malformed stable-prefix templates. Output: rejection instead of guessing directories."""
    with pytest.raises(ValueError):
        helper.stable_shared_prefix_parts(template)


def test_group_list_normalization_preserves_order_and_deduplicates_ldap():
    """Inputs: duplicate/blank/comment entries. Output: deterministic configured groups only."""
    groups = " ,#comment,alpha:private,alpha:read-only,:ignored,beta:private"
    assert helper._configured_groups(groups, "true", "alpha") == ["alpha", "beta"]
    assert helper._configured_groups(groups, "yes", "gamma") == [
        "alpha",
        "beta",
        "gamma",
    ]
    assert helper.configured_seed_paths(
        "root/%group%/shared/%user%", groups, "true", "gamma"
    ) == [
        "root",
        "root/alpha",
        "root/alpha/shared",
        "root/beta",
        "root/beta/shared",
        "root/gamma",
        "root/gamma/shared",
    ]


def test_literal_and_group_matchers_do_not_treat_literals_as_regex():
    """Inputs: punctuation in path templates. Output: literal matching with bounded group components."""
    literal = helper._stable_prefix_matcher("a.b")
    assert literal.fullmatch("a.b") and not literal.fullmatch("axb")
    grouped = helper._stable_prefix_matcher("team-%group%")
    assert grouped.fullmatch("team-research")
    for name in ("team-", "team-a/b", "team-a\\b", "team-a\x00b"):
        assert not grouped.fullmatch(name)
    with pytest.raises(ValueError, match="Only %group%"):
        helper._stable_prefix_matcher("%user%")


def test_cli_reads_only_selected_password_variable(gateway, monkeypatch, capsys):
    """Inputs: explicit credential-variable selection. Output: correct gateway identity, no disclosure."""
    conn, factory, root, _ = gateway
    monkeypatch.setenv("FIXTURE_REPO_PASSWORD", "chosen-fixture-secret")
    assert (
        helper.main(
            [
                "lookup",
                "--host",
                "service.example",
                "--port",
                "14064",
                "--repo-dir-path",
                "group",
                "--expected-managed-dir",
                str(root),
                "--root-password-env",
                "FIXTURE_REPO_PASSWORD",
            ]
        )
        == 0
    )
    assert factory.call_args.args == ("root", "chosen-fixture-secret")
    assert "chosen-fixture-secret" not in capsys.readouterr().out
    conn.close.assert_called_once_with()


def test_cli_missing_credential_and_bad_template_fail_before_connect(
    gateway, monkeypatch, capsys
):
    """Inputs: incomplete deployment config. Output: usage errors with no connection attempt."""
    _, factory, root, _ = gateway
    monkeypatch.delenv("FIXTURE_REPO_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as error:
        helper.main(
            [
                "lookup",
                "--host",
                "service.example",
                "--port",
                "14064",
                "--repo-dir-path",
                "group",
                "--expected-managed-dir",
                str(root),
                "--root-password-env",
                "FIXTURE_REPO_PASSWORD",
            ]
        )
    assert error.value.code == 2
    assert "populated --root-password-env" in capsys.readouterr().err
    assert helper.main(["stable-depth", "--repo-template", "root/%unknown%"]) == 2
    assert "unsupported tokens" in capsys.readouterr().err
    factory.assert_not_called()
