from __future__ import annotations

from types import SimpleNamespace

import pytest

from omero_plugin_common import env_utils, omero_helpers, tmp_cleanup, tmp_utils


class _Value:
    """Represent value."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self._stored_value = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._stored_value`.
        """
        return self._stored_value


def test_env_utils_cover_reference_messages_and_optional_required_values(
    monkeypatch,
) -> None:
    """Verify environment utils cover reference messages and optional required values.

    Inputs: `monkeypatch`. Output: None.
    """
    docs_url = "https://example.invalid/docs"
    assert env_utils._env_reference(env_utils.ENV_FILE_OMEROWEB, docs_url) == (
        f"Set it in {env_utils.ENV_FILE_OMEROWEB} (referenced by docker-compose.yml). "
        f"See {docs_url}."
    )
    assert "Provide a value." in env_utils._missing_env_message(
        "REQUIRED_SETTING",
        env_utils.ENV_FILE_OMEROWEB,
        hint="Provide a value.",
        docs_url=docs_url,
    )

    monkeypatch.delenv("OPTIONAL_SETTING", raising=False)
    assert (
        env_utils.get_optional_env(
            "OPTIONAL_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )
        is None
    )

    monkeypatch.setenv("OPTIONAL_SETTING", "   ")
    assert (
        env_utils.get_optional_env(
            "OPTIONAL_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )
        is None
    )
    assert (
        env_utils.get_optional_env(
            "OPTIONAL_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            allow_empty=True,
        )
        == "   "
    )
    with pytest.raises(ValueError, match="configuration contract"):
        env_utils.get_optional_env("OPTIONAL_SETTING", env_file="")

    monkeypatch.delenv("REQUIRED_SETTING", raising=False)
    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        env_utils.require_env(
            "REQUIRED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            hint="Set it before startup.",
            docs_url=docs_url,
        )

    monkeypatch.setenv("REQUIRED_SETTING", "configured")
    assert (
        env_utils.get_env(
            "REQUIRED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            docs_url=docs_url,
        )
        == "configured"
    )


def test_env_utils_cover_numeric_boolean_and_sanitized_validation(monkeypatch) -> None:
    """Verify environment utils cover numeric boolean and sanitized validation.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setenv("INT_SETTING", "41")
    assert (
        env_utils.get_int_env(
            "INT_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )
        == 41
    )

    monkeypatch.setenv("INT_SETTING", "not-an-int")
    with pytest.raises(ValueError, match="Expected an integer"):
        env_utils.get_int_env(
            "INT_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )

    monkeypatch.setenv("FLOAT_SETTING", "nope")
    with pytest.raises(ValueError, match="Expected a number"):
        env_utils.get_float_env(
            "FLOAT_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )

    monkeypatch.setenv("BOOL_SETTING", "off")
    assert (
        env_utils.get_bool_env(
            "BOOL_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )
        is False
    )
    monkeypatch.setenv("BOOL_SETTING", "sometimes")
    with pytest.raises(ValueError, match="Expected a boolean"):
        env_utils.get_bool_env(
            "BOOL_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
        )

    monkeypatch.setenv("SANITIZED_SETTING", " 999 ")
    assert (
        env_utils.get_sanitized_int_env(
            "SANITIZED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            sanitizer=lambda value: value.strip(),
            min_value=10,
            max_value=50,
        )
        == 50
    )

    monkeypatch.setenv("SANITIZED_SETTING", "  ")
    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        env_utils.get_sanitized_int_env(
            "SANITIZED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            sanitizer=lambda value: value.strip(),
            min_value=10,
            max_value=50,
        )

    monkeypatch.setenv("SANITIZED_SETTING", "oops")
    with pytest.raises(ValueError, match="Expected an integer"):
        env_utils.get_sanitized_int_env(
            "SANITIZED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            sanitizer=lambda value: value,
            min_value=10,
            max_value=50,
        )


def test_env_utils_and_tmp_utils_cover_sanitized_empty_and_missing_tmp_root(
    monkeypatch,
) -> None:
    """Verify environment utils and temporary utils cover sanitized empty and missing temporary root.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setenv("SANITIZED_SETTING", "configured")
    with pytest.raises(ValueError, match="Expected a non-empty integer"):
        env_utils.get_sanitized_int_env(
            "SANITIZED_SETTING",
            env_file=env_utils.ENV_FILE_OMEROWEB,
            sanitizer=lambda value: "   ",
            min_value=10,
            max_value=50,
        )

    monkeypatch.delenv(tmp_utils.TMP_PATH_ENV, raising=False)
    with pytest.raises(RuntimeError, match=tmp_utils.TMP_PATH_ENV):
        tmp_utils.get_tmp_base()


def test_omero_helpers_cover_none_and_exception_fallback_paths() -> None:
    """Verify OMERO helpers cover none and exception fallback paths.

    Inputs: none. Output: None.
    """
    invalid_owner = SimpleNamespace(
        getDetails=lambda: SimpleNamespace(
            getOwner=lambda: SimpleNamespace(getId=lambda: _Value("abc"))
        )
    )
    no_owner = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("no details")),
        getOwner=lambda: (_ for _ in ()).throw(RuntimeError("no owner")),
    )
    conn_without_user = SimpleNamespace(getUser=lambda: None)
    permission_failures = SimpleNamespace(
        canEdit=lambda: (_ for _ in ()).throw(RuntimeError("no edit")),
        canWrite=lambda: (_ for _ in ()).throw(RuntimeError("no write")),
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("no permissions")),
    )
    permission_unknown = SimpleNamespace(getDetails=lambda: None)

    assert omero_helpers.get_owner_id(None) is None
    assert omero_helpers.is_owned_by_user(invalid_owner, "alice") is False
    assert omero_helpers._current_user_id(conn_without_user) is None
    assert omero_helpers._get_owner_username(no_owner) == ""
    assert omero_helpers._has_read_write_permissions(permission_failures) is False
    assert omero_helpers._has_read_write_permissions(permission_unknown) is False


def test_tmp_cleanup_handles_missing_paths_and_walk_failures(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify temporary cleanup handles missing paths and walk failures.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    root = tmp_path / "root"
    root.mkdir()
    missing = root / "missing"
    target = root / "target"
    target.mkdir()
    (target / "payload.txt").write_text("payload", encoding="utf-8")

    assert tmp_cleanup.safe_remove_tree(missing, root) is True
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            missing,
            root,
            ttl_seconds=60,
        )
        is True
    )
    assert tmp_cleanup.is_within_root(target, tmp_path / "absent-root") is False

    monkeypatch.setattr(
        tmp_cleanup.os,
        "walk",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("walk failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False
