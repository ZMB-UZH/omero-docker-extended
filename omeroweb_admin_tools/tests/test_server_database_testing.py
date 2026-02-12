from __future__ import annotations

import json

from django.test import RequestFactory

from omeroweb_admin_tools.views.index_view import server_database_testing_run


def test_server_database_testing_run_requires_post(monkeypatch) -> None:
    request = RequestFactory().get("/admin_tools/server-database-testing/run/")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    response = server_database_testing_run(request, conn=None)

    assert response.status_code == 405


def test_server_database_testing_run_rejects_empty_script_ids(monkeypatch) -> None:
    request = RequestFactory().post(
        "/admin_tools/server-database-testing/run/",
        data=json.dumps({"scripts": ["omero_server_core", ""]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    response = server_database_testing_run(request, conn=None)

    assert response.status_code == 400
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["error"] == "Payload contains invalid empty script IDs."


def test_server_database_testing_run_returns_results(monkeypatch) -> None:
    request = RequestFactory().post(
        "/admin_tools/server-database-testing/run/",
        data=json.dumps({"scripts": ["omero_server_core"]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.run_diagnostic_script",
        lambda script_id: {"script_id": script_id, "status": "pass", "checks": []},
    )

    response = server_database_testing_run(request, conn=None)

    assert response.status_code == 200
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["results"] == [
        {"script_id": "omero_server_core", "status": "pass", "checks": []}
    ]
    assert isinstance(payload["request_id"], str)
    assert payload["request_id"]
