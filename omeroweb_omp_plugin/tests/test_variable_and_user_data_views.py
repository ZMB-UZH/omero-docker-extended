from __future__ import annotations

import json

from django.test import RequestFactory

from omeroweb_omp_plugin.strings import errors as omp_errors
from omeroweb_omp_plugin.strings import messages as omp_messages
from omeroweb_omp_plugin.views import user_data_view, variable_set_view


def _payload(response):
    return json.loads(response.content.decode("utf-8"))


def test_variable_set_views_cover_success_and_validation_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        variable_set_view,
        "load_request_data",
        lambda request: request._decoded_payload,
    )

    list_request = RequestFactory().get("/omp/varsets/")
    monkeypatch.setattr(
        variable_set_view, "list_variable_sets", lambda username: ["demo", "qc"]
    )
    list_response = variable_set_view.list_sets(list_request, conn=None)
    assert list_response.status_code == 200
    assert _payload(list_response) == {"sets": ["demo", "qc"]}

    wrong_method_response = variable_set_view.list_sets(
        RequestFactory().post("/omp/varsets/"), conn=None
    )
    assert wrong_method_response.status_code == 405
    assert _payload(wrong_method_response)["error"] == omp_errors.method_get_required()

    save_request = RequestFactory().post("/omp/varsets/save/")
    save_request._decoded_payload = {
        "set_name": "demo",
        "var_names": ["alpha", "beta"],
        "max_sets": "50",
    }
    saved = {}
    monkeypatch.setattr(variable_set_view, "list_variable_sets", lambda username: [])
    monkeypatch.setattr(
        variable_set_view,
        "save_variable_set",
        lambda username, set_name, var_names: saved.update(
            {"username": username, "set_name": set_name, "var_names": list(var_names)}
        ),
    )
    save_response = variable_set_view.save_set(save_request, conn=None)
    assert save_response.status_code == 200
    assert _payload(save_response) == {
        "message": omp_messages.variable_set_saved_response()
    }
    assert saved == {
        "username": "alice",
        "set_name": "demo",
        "var_names": ["alpha", "beta"],
    }

    duplicate_request = RequestFactory().post("/omp/varsets/save/")
    duplicate_request._decoded_payload = {
        "set_name": "demo",
        "var_names": ["alpha"],
        "max_sets": "10",
    }
    monkeypatch.setattr(
        variable_set_view, "list_variable_sets", lambda username: ["demo"]
    )
    duplicate_response = variable_set_view.save_set(duplicate_request, conn=None)
    assert duplicate_response.status_code == 400
    assert _payload(duplicate_response)["error"] == (
        omp_errors.variable_set_already_exists()
    )

    invalid_request = RequestFactory().post("/omp/varsets/save/")
    invalid_request._decoded_payload = {
        "set_name": "new-set",
        "var_names": ["alpha", ""],
    }
    invalid_response = variable_set_view.save_set(invalid_request, conn=None)
    assert invalid_response.status_code == 400
    assert _payload(invalid_response)["error"] == omp_errors.variable_names_empty()

    limited_request = RequestFactory().post("/omp/varsets/save/")
    limited_request._decoded_payload = {
        "set_name": "overflow",
        "var_names": ["alpha"],
        "max_sets": "5",
    }
    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: ["a", "b", "c", "d", "e"],
    )
    limited_response = variable_set_view.save_set(limited_request, conn=None)
    assert limited_response.status_code == 400
    assert _payload(limited_response)["error"] == omp_errors.variable_set_max_entries(5)

    load_request = RequestFactory().get("/omp/varsets/load/", data={"set_name": "demo"})
    monkeypatch.setattr(
        variable_set_view, "list_variable_sets", lambda username: ["demo"]
    )
    monkeypatch.setattr(
        variable_set_view, "load_variable_set", lambda username, set_name: ["alpha"]
    )
    load_response = variable_set_view.load_set(load_request, conn=None)
    assert load_response.status_code == 200
    assert _payload(load_response) == {"var_names": ["alpha"]}

    not_found_request = RequestFactory().get(
        "/omp/varsets/load/",
        data={"set_name": "missing"},
    )
    monkeypatch.setattr(
        variable_set_view, "load_variable_set", lambda username, set_name: None
    )
    not_found_response = variable_set_view.load_set(not_found_request, conn=None)
    assert not_found_response.status_code == 404
    assert _payload(not_found_response)["error"] == omp_errors.variable_set_not_found()

    empty_request = RequestFactory().get("/omp/varsets/load/", data={"set_name": ""})
    empty_response = variable_set_view.load_set(empty_request, conn=None)
    assert empty_response.status_code == 400
    assert _payload(empty_response)["error"] == (
        omp_errors.variable_set_dropdown_required()
    )

    delete_request = RequestFactory().post("/omp/varsets/delete/")
    delete_request._decoded_payload = {"set_name": "demo"}
    deleted = {}
    monkeypatch.setattr(
        variable_set_view,
        "delete_variable_set",
        lambda username, set_name: deleted.update(
            {"username": username, "set_name": set_name}
        ),
    )
    delete_response = variable_set_view.delete_set(delete_request, conn=None)
    assert delete_response.status_code == 200
    assert _payload(delete_response) == {"ok": True}
    assert deleted == {"username": "alice", "set_name": "demo"}

    missing_delete_request = RequestFactory().post("/omp/varsets/delete/")
    missing_delete_request._decoded_payload = {"set_name": " "}
    missing_delete_response = variable_set_view.delete_set(
        missing_delete_request, conn=None
    )
    assert missing_delete_response.status_code == 400
    assert _payload(missing_delete_response)["error"] == omp_errors.missing_set_name()


def test_user_data_views_cover_success_and_request_guards(monkeypatch) -> None:
    monkeypatch.setattr(
        user_data_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(user_data_view, "delete_all_ai_credentials", lambda username: 2)
    monkeypatch.setattr(user_data_view, "delete_all_variable_sets", lambda username: 3)
    monkeypatch.setattr(user_data_view, "delete_all_user_data", lambda username: 5)

    delete_keys = user_data_view.delete_api_keys(
        RequestFactory().post("/omp/user-data/delete-api-keys/"), conn=None
    )
    delete_sets = user_data_view.delete_variable_sets(
        RequestFactory().post("/omp/user-data/delete-variable-sets/"), conn=None
    )
    delete_all = user_data_view.delete_all_data(
        RequestFactory().post("/omp/user-data/delete-all/"), conn=None
    )

    assert _payload(delete_keys) == {"ok": True, "deleted": 2}
    assert _payload(delete_sets) == {"ok": True, "deleted": 3}
    assert _payload(delete_all) == {"ok": True, "deleted": 5}

    wrong_method = user_data_view.delete_api_keys(
        RequestFactory().get("/omp/user-data/delete-api-keys/"), conn=None
    )
    assert wrong_method.status_code == 405
    assert _payload(wrong_method)["error"] == omp_errors.method_post_required()

    monkeypatch.setattr(user_data_view, "current_username", lambda request, conn: "")
    missing_user = user_data_view.delete_all_data(
        RequestFactory().post("/omp/user-data/delete-all/"), conn=None
    )
    assert missing_user.status_code == 400
    assert _payload(missing_user)["error"] == omp_errors.unable_to_determine_username()
