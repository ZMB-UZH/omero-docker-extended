from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_imaris_connector import config


def test_use_job_service_session_requires_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setenv("OMERO_IMS_USE_JOB_SERVICE_SESSION", value)
    assert config.use_job_service_session() is expected


def test_use_job_service_session_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMERO_IMS_USE_JOB_SERVICE_SESSION", "unexpected")
    with pytest.raises(ValueError):
        config.use_job_service_session()


def test_get_job_service_credentials_prefers_web_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMERO_WEB_JOB_SERVICE_USERNAME", "web-user")
    monkeypatch.setenv("OMERO_WEB_JOB_SERVICE_PASS", "web-pass")
    monkeypatch.setenv("OMERO_JOB_SERVICE_USERNAME", "server-user")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "server-pass")

    username, password = config.get_job_service_credentials()

    assert username == "web-user"
    assert password == "web-pass"


def test_get_job_service_credentials_falls_back_to_server_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_PASS", raising=False)
    monkeypatch.setenv("OMERO_JOB_SERVICE_USERNAME", "server-user")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "server-pass")

    username, password = config.get_job_service_credentials()

    assert username == "server-user"
    assert password == "server-pass"


def test_get_job_service_credentials_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_WEB_JOB_SERVICE_PASS", raising=False)
    monkeypatch.delenv("OMERO_JOB_SERVICE_USERNAME", raising=False)
    monkeypatch.delenv("OMERO_JOB_SERVICE_PASS", raising=False)

    username, password = config.get_job_service_credentials()

    assert username is None
    assert password is None
