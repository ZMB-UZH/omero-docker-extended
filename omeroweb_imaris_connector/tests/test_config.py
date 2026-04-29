from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_imaris_connector import config

TEST_AUTH_WEB = "web-fixture-auth"
TEST_AUTH_SERVER = "server-fixture-auth"


def test_use_celery_reads_boolean_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test use celery reads boolean flag."""
    monkeypatch.setenv("OMERO_IMS_USE_CELERY", "true")
    assert config.use_celery() is True


def test_use_job_service_session_requires_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test use job service session requires explici behavior."""
    monkeypatch.delenv("OMERO_IMS_USE_JOB_SERVICE_SESSION", raising=False)
    with pytest.raises(RuntimeError):
        config.use_job_service_session()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ],
)
def test_use_job_service_session_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    """Verify test use job service session parsing."""
    monkeypatch.setenv("OMERO_IMS_USE_JOB_SERVICE_SESSION", value)
    assert config.use_job_service_session() is expected


def test_use_job_service_session_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test use job service session rejects invalid behavior."""
    monkeypatch.setenv("OMERO_IMS_USE_JOB_SERVICE_SESSION", "unexpected")
    with pytest.raises(ValueError):
        config.use_job_service_session()


def test_get_job_service_credentials_prefers_web_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test get job service credentials prefers web env."""
    monkeypatch.setenv("OMERO_WEB_JOB_SERVICE_USERNAME", "web-user")
    monkeypatch.setenv("OMERO_WEB_JOB_SERVICE_PASS", TEST_AUTH_WEB)
    monkeypatch.setenv("OMERO_JOB_SERVICE_USERNAME", "server-user")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", TEST_AUTH_SERVER)

    username, password = config.get_job_service_credentials()

    assert username == "web-user"
    assert password == TEST_AUTH_WEB


def test_get_job_service_credentials_falls_back_to_server_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test get job service credentials falls back t behavior."""
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_PASS", raising=False)
    monkeypatch.setenv("OMERO_JOB_SERVICE_USERNAME", "server-user")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", TEST_AUTH_SERVER)

    username, password = config.get_job_service_credentials()

    assert username == "server-user"
    assert password == TEST_AUTH_SERVER


def test_get_job_service_credentials_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test get job service credentials missing retu behavior."""
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_PASS", raising=False)
    monkeypatch.delenv("OMERO_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_JOB_SERVICE_PASS", raising=False)

    username, password = config.get_job_service_credentials()

    assert username is None
    assert password is None
