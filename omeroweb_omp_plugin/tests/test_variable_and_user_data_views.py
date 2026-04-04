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
    wrong_method_sets = user_data_view.delete_variable_sets(
        RequestFactory().get("/omp/user-data/delete-variable-sets/"), conn=None
    )
    assert wrong_method_sets.status_code == 405
    assert _payload(wrong_method_sets)["error"] == omp_errors.method_post_required()

    monkeypatch.setattr(user_data_view, "current_username", lambda request, conn: "")
    missing_user = user_data_view.delete_all_data(
        RequestFactory().post("/omp/user-data/delete-all/"), conn=None
    )
    assert missing_user.status_code == 400
    assert _payload(missing_user)["error"] == omp_errors.unable_to_determine_username()


def test_variable_and_user_data_views_cover_store_failures_and_guard_edges(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        variable_set_view,
        "load_request_data",
        lambda request: request._decoded_payload,
    )

    monkeypatch.setattr(variable_set_view, "current_username", lambda request, conn: "")
    list_missing_user = variable_set_view.list_sets(
        RequestFactory().get("/"), conn=None
    )
    assert list_missing_user.status_code == 400
    assert (
        _payload(list_missing_user)["error"]
        == omp_errors.unable_to_determine_username()
    )

    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: (_ for _ in ()).throw(
            variable_set_view.VariableStoreError("backend")
        ),
    )
    list_store_error = variable_set_view.list_sets(RequestFactory().get("/"), conn=None)
    assert list_store_error.status_code == 500
    assert (
        _payload(list_store_error)["error"] == omp_errors.variable_sets_fetch_failed()
    )

    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    list_unexpected = variable_set_view.list_sets(RequestFactory().get("/"), conn=None)
    assert list_unexpected.status_code == 500
    assert _payload(list_unexpected)["error"] == omp_errors.unexpected_error()

    invalid_payload_request = RequestFactory().post("/omp/varsets/save/")
    invalid_payload_request._decoded_payload = {
        "set_name": "demo",
        "var_names": "alpha",
        "max_sets": "invalid",
    }
    invalid_payload = variable_set_view.save_set(invalid_payload_request, conn=None)
    assert invalid_payload.status_code == 400
    assert _payload(invalid_payload)["error"] == omp_errors.invalid_variable_payload()

    blank_name_request = RequestFactory().post("/omp/varsets/save/")
    blank_name_request._decoded_payload = {"set_name": " ", "var_names": ["alpha"]}
    blank_name = variable_set_view.save_set(blank_name_request, conn=None)
    assert blank_name.status_code == 400
    assert _payload(blank_name)["error"] == omp_errors.variable_set_name_required()

    save_store_error_request = RequestFactory().post("/omp/varsets/save/")
    save_store_error_request._decoded_payload = {
        "set_name": "demo",
        "var_names": ["alpha"],
    }
    monkeypatch.setattr(variable_set_view, "list_variable_sets", lambda username: [])
    monkeypatch.setattr(
        variable_set_view,
        "save_variable_set",
        lambda username, set_name, var_names: (_ for _ in ()).throw(
            variable_set_view.VariableStoreError("save failed")
        ),
    )
    save_store_error = variable_set_view.save_set(save_store_error_request, conn=None)
    assert save_store_error.status_code == 500
    assert _payload(save_store_error)["error"] == omp_errors.variable_set_save_failed()

    monkeypatch.setattr(
        variable_set_view,
        "save_variable_set",
        lambda username, set_name, var_names: (_ for _ in ()).throw(
            RuntimeError("save boom")
        ),
    )
    save_unexpected = variable_set_view.save_set(save_store_error_request, conn=None)
    assert save_unexpected.status_code == 500
    assert _payload(save_unexpected)["error"] == omp_errors.unexpected_error()

    monkeypatch.setattr(variable_set_view, "current_username", lambda request, conn: "")
    load_user_missing = variable_set_view.load_set(
        RequestFactory().get("/omp/varsets/load/", data={"set_name": "demo"}),
        conn=None,
    )
    assert load_user_missing.status_code == 400
    assert (
        _payload(load_user_missing)["error"]
        == omp_errors.unable_to_determine_username()
    )

    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: (_ for _ in ()).throw(
            variable_set_view.VariableStoreError("load failed")
        ),
    )
    load_store_error = variable_set_view.load_set(
        RequestFactory().get("/omp/varsets/load/", data={"set_name": "demo"}),
        conn=None,
    )
    assert load_store_error.status_code == 500
    assert _payload(load_store_error)["error"] == omp_errors.variable_set_load_failed()

    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: ["demo"],
    )
    monkeypatch.setattr(
        variable_set_view,
        "load_variable_set",
        lambda username, set_name: (_ for _ in ()).throw(RuntimeError("load boom")),
    )
    load_unexpected = variable_set_view.load_set(
        RequestFactory().get("/omp/varsets/load/", data={"set_name": "demo"}),
        conn=None,
    )
    assert load_unexpected.status_code == 500
    assert _payload(load_unexpected)["error"] == omp_errors.unexpected_error()

    delete_wrong_method = variable_set_view.delete_set(
        RequestFactory().get("/omp/varsets/delete/"),
        conn=None,
    )
    assert delete_wrong_method.status_code == 405

    monkeypatch.setattr(variable_set_view, "current_username", lambda request, conn: "")
    delete_missing_user = variable_set_view.delete_set(
        RequestFactory().post("/omp/varsets/delete/"),
        conn=None,
    )
    assert delete_missing_user.status_code == 400
    assert (
        _payload(delete_missing_user)["error"]
        == omp_errors.unable_to_determine_username()
    )

    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    delete_store_error_request = RequestFactory().post("/omp/varsets/delete/")
    delete_store_error_request._decoded_payload = {"set_name": "demo"}
    monkeypatch.setattr(
        variable_set_view,
        "delete_variable_set",
        lambda username, set_name: (_ for _ in ()).throw(
            variable_set_view.VariableStoreError("delete failed")
        ),
    )
    delete_store_error = variable_set_view.delete_set(
        delete_store_error_request,
        conn=None,
    )
    assert delete_store_error.status_code == 500
    assert (
        _payload(delete_store_error)["error"] == omp_errors.variable_set_delete_failed()
    )

    monkeypatch.setattr(
        variable_set_view,
        "delete_variable_set",
        lambda username, set_name: (_ for _ in ()).throw(RuntimeError("delete boom")),
    )
    delete_unexpected = variable_set_view.delete_set(
        delete_store_error_request,
        conn=None,
    )
    assert delete_unexpected.status_code == 500
    assert _payload(delete_unexpected)["error"] == omp_errors.unexpected_error()

    monkeypatch.setattr(
        user_data_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        user_data_view,
        "delete_all_ai_credentials",
        lambda username: (_ for _ in ()).throw(
            user_data_view.AiCredentialStoreError("credentials failed")
        ),
    )
    api_key_store_error = user_data_view.delete_api_keys(
        RequestFactory().post("/omp/user-data/delete-api-keys/"),
        conn=None,
    )
    assert api_key_store_error.status_code == 500
    assert (
        _payload(api_key_store_error)["error"]
        == omp_errors.ai_credentials_delete_failed()
    )

    monkeypatch.setattr(
        user_data_view,
        "delete_all_ai_credentials",
        lambda username: (_ for _ in ()).throw(RuntimeError("credentials boom")),
    )
    api_key_unexpected = user_data_view.delete_api_keys(
        RequestFactory().post("/omp/user-data/delete-api-keys/"),
        conn=None,
    )
    assert api_key_unexpected.status_code == 500
    assert _payload(api_key_unexpected)["error"] == omp_errors.unexpected_error()

    monkeypatch.setattr(
        user_data_view,
        "delete_all_variable_sets",
        lambda username: (_ for _ in ()).throw(
            user_data_view.VariableStoreError("sets failed")
        ),
    )
    delete_sets_store_error = user_data_view.delete_variable_sets(
        RequestFactory().post("/omp/user-data/delete-variable-sets/"),
        conn=None,
    )
    assert delete_sets_store_error.status_code == 500
    assert (
        _payload(delete_sets_store_error)["error"]
        == omp_errors.variable_sets_delete_failed()
    )

    monkeypatch.setattr(
        user_data_view,
        "delete_all_variable_sets",
        lambda username: (_ for _ in ()).throw(RuntimeError("sets boom")),
    )
    delete_sets_unexpected = user_data_view.delete_variable_sets(
        RequestFactory().post("/omp/user-data/delete-variable-sets/"),
        conn=None,
    )
    assert delete_sets_unexpected.status_code == 500
    assert _payload(delete_sets_unexpected)["error"] == omp_errors.unexpected_error()

    monkeypatch.setattr(
        user_data_view,
        "delete_all_user_data",
        lambda username: (_ for _ in ()).throw(
            user_data_view.UserDataStoreError("all data failed")
        ),
    )
    delete_all_store_error = user_data_view.delete_all_data(
        RequestFactory().post("/omp/user-data/delete-all/"),
        conn=None,
    )
    assert delete_all_store_error.status_code == 500
    assert (
        _payload(delete_all_store_error)["error"]
        == omp_errors.user_data_delete_failed()
    )

    monkeypatch.setattr(
        user_data_view,
        "delete_all_user_data",
        lambda username: (_ for _ in ()).throw(RuntimeError("all data boom")),
    )
    delete_all_unexpected = user_data_view.delete_all_data(
        RequestFactory().post("/omp/user-data/delete-all/"),
        conn=None,
    )
    assert delete_all_unexpected.status_code == 500
    assert _payload(delete_all_unexpected)["error"] == omp_errors.unexpected_error()


def test_variable_and_user_data_views_cover_remaining_method_and_username_guards(
    monkeypatch,
) -> None:
    monkeypatch.setattr(variable_set_view, "current_username", lambda request, conn: "")
    save_missing_user_request = RequestFactory().post("/omp/varsets/save/")
    save_missing_user_request._decoded_payload = {
        "set_name": "demo",
        "var_names": ["a"],
    }
    monkeypatch.setattr(
        variable_set_view,
        "load_request_data",
        lambda request: request._decoded_payload,
    )
    save_missing_user = variable_set_view.save_set(save_missing_user_request, conn=None)
    assert save_missing_user.status_code == 400
    assert (
        _payload(save_missing_user)["error"]
        == omp_errors.unable_to_determine_username()
    )

    save_wrong_method = variable_set_view.save_set(
        RequestFactory().get("/omp/varsets/save/"),
        conn=None,
    )
    assert save_wrong_method.status_code == 405

    load_wrong_method = variable_set_view.load_set(
        RequestFactory().post("/omp/varsets/load/"),
        conn=None,
    )
    assert load_wrong_method.status_code == 405

    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(variable_set_view, "list_variable_sets", lambda username: [])
    empty_db = variable_set_view.load_set(
        RequestFactory().get("/omp/varsets/load/", data={"set_name": "demo"}),
        conn=None,
    )
    assert empty_db.status_code == 400
    assert _payload(empty_db)["error"] == omp_errors.variable_set_empty_db()

    monkeypatch.setattr(user_data_view, "current_username", lambda request, conn: "")
    missing_user_keys = user_data_view.delete_api_keys(
        RequestFactory().post("/omp/user-data/delete-api-keys/"),
        conn=None,
    )
    missing_user_sets = user_data_view.delete_variable_sets(
        RequestFactory().post("/omp/user-data/delete-variable-sets/"),
        conn=None,
    )
    wrong_method_all = user_data_view.delete_all_data(
        RequestFactory().get("/omp/user-data/delete-all/"),
        conn=None,
    )

    assert missing_user_keys.status_code == 400
    assert missing_user_sets.status_code == 400
    assert wrong_method_all.status_code == 405
