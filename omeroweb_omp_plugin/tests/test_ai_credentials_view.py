from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from urllib.parse import urlunsplit

import pytest
from django.test import RequestFactory

from omeroweb_omp_plugin.views import ai_credentials_view

TEST_API_CREDENTIAL = "fixture-api-credential"


def _json_payload(response):
    """Return the JSON payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def _json_post(payload):
    """Return the JSON post.

    Inputs: `payload` payload. Output: `post` result.
    """
    return RequestFactory().post(
        "/",
        data=json.dumps(payload),
        content_type="application/json",
    )


class _Response:
    """Test double for response behavior in this module."""

    def __init__(
        self,
        payload,
        status=200,
        *,
        headers=None,
        url="https://api.example.test/models",
    ):
        """Create `_Response` with `payload` and `status`.

        Inputs: `payload`, `status`, `headers`, `url`. Output: None.
        """
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.url = url
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        """Return the JSON payload.

        Inputs: none. Output: `_payload`. Raises: ValueError for the exercised failure path.
        """
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def _http_error(url="https://api.example.test/models", code=401, body="forbidden"):
    """Return the HTTP error.

    Inputs: `url` URL, `code`, `body`. Output: `exc`.
    """
    exc = ai_credentials_view.requests.HTTPError("failure")
    exc.response = _Response(body, status=code, url=url)
    return exc


def test_list_credentials_and_test_save_paths(monkeypatch):
    """Verify list credentials and test save paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in list credentials and test save paths.
    """
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "list_ai_credentials",
        lambda username: [{"provider": "groq", "configured": True}],
    )

    response = inspect.unwrap(ai_credentials_view.list_credentials)(request, conn=None)

    assert response.status_code == 200
    assert _json_payload(response) == {
        "providers": [{"provider": "groq", "configured": True}]
    }

    monkeypatch.setattr(
        ai_credentials_view,
        "_perform_connection_test",
        lambda provider, api_key: (True, "Connection test passed."),
    )
    saved = {}
    monkeypatch.setattr(
        ai_credentials_view,
        "save_ai_credentials",
        lambda username, provider, api_key: saved.update(
            {"username": username, "provider": provider, "api_key": api_key}
        ),
    )

    save_response = inspect.unwrap(ai_credentials_view.save_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    test_response = inspect.unwrap(ai_credentials_view.test_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )

    assert save_response.status_code == 200
    assert _json_payload(save_response) == {
        "message": ai_credentials_view.messages.api_key_saved_status()
    }
    assert saved == {
        "username": "alice",
        "provider": "groq",
        "api_key": TEST_API_CREDENTIAL,
    }
    assert test_response.status_code == 200
    assert _json_payload(test_response) == {"message": "Connection test passed."}


def test_list_credentials_handles_method_user_and_store_failures(monkeypatch):
    """Verify list credentials handles method user and store failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in list credentials handles method user and store failures.
    """
    method_response = inspect.unwrap(ai_credentials_view.list_credentials)(
        RequestFactory().post("/"),
        conn=None,
    )
    assert method_response.status_code == 405

    request = RequestFactory().get("/")
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "")
    missing_user = inspect.unwrap(ai_credentials_view.list_credentials)(
        request, conn=None
    )
    assert missing_user.status_code == 400

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "list_ai_credentials",
        lambda username: (_ for _ in ()).throw(
            ai_credentials_view.AiCredentialStoreError("db unavailable")
        ),
    )
    store_error = inspect.unwrap(ai_credentials_view.list_credentials)(
        request, conn=None
    )
    assert store_error.status_code == 500

    monkeypatch.setattr(
        ai_credentials_view,
        "list_ai_credentials",
        lambda username: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    unexpected = inspect.unwrap(ai_credentials_view.list_credentials)(
        request, conn=None
    )
    assert unexpected.status_code == 500


def test_test_credentials_reuses_saved_key_and_handles_failures(monkeypatch):
    """Verify AI credential checks reuse saved keys and report provider failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in saved-key
    reuse or provider-error handling.
    """
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: "stored-key",
    )
    monkeypatch.setattr(
        ai_credentials_view,
        "_perform_connection_test",
        lambda provider, api_key: (False, "provider rejected"),
    )

    response = inspect.unwrap(ai_credentials_view.test_credentials)(
        _json_post({"provider": "groq", "api_key": ""}),
        conn=None,
    )

    assert response.status_code == 400
    assert _json_payload(response) == {"error": "provider rejected"}

    missing_provider = inspect.unwrap(ai_credentials_view.test_credentials)(
        _json_post({"provider": "", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "")
    missing_key = inspect.unwrap(ai_credentials_view.test_credentials)(
        _json_post({"provider": "groq", "api_key": ""}),
        conn=SimpleNamespace(),
    )

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: (_ for _ in ()).throw(RuntimeError("broken store")),
    )
    unexpected = inspect.unwrap(ai_credentials_view.test_credentials)(
        _json_post({"provider": "groq", "api_key": ""}),
        conn=SimpleNamespace(),
    )

    assert missing_provider.status_code == 400
    assert missing_key.status_code == 400
    assert _json_payload(missing_key) == {
        "error": ai_credentials_view.errors.api_key_empty()
    }
    assert unexpected.status_code == 500


def test_save_credentials_handles_missing_username_failed_validation_and_store_error(
    monkeypatch,
):
    """Confirm save credentials handles missing username failed validation and store error exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when save credentials handles missing username failed validation and store error stops reporting the expected error.
    """
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "")
    missing_user = inspect.unwrap(ai_credentials_view.save_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    assert missing_user.status_code == 400

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "_perform_connection_test",
        lambda provider, api_key: (False, "bad key"),
    )
    failed_validation = inspect.unwrap(ai_credentials_view.save_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    assert failed_validation.status_code == 400

    monkeypatch.setattr(
        ai_credentials_view,
        "_perform_connection_test",
        lambda provider, api_key: (True, "ok"),
    )
    monkeypatch.setattr(
        ai_credentials_view,
        "save_ai_credentials",
        lambda *args: (_ for _ in ()).throw(
            ai_credentials_view.AiCredentialStoreError("write failed")
        ),
    )
    store_error = inspect.unwrap(ai_credentials_view.save_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    assert store_error.status_code == 500

    monkeypatch.setattr(
        ai_credentials_view,
        "save_ai_credentials",
        lambda *args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    unexpected = inspect.unwrap(ai_credentials_view.save_credentials)(
        _json_post({"provider": "groq", "api_key": TEST_API_CREDENTIAL}),
        conn=None,
    )
    assert unexpected.status_code == 500


def test_list_models_supports_provider_specific_payloads_and_default_selection(
    monkeypatch,
):
    """Verify list models supports provider specific payloads and default selection.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in list models supports provider specific payloads and default selection.
    """
    request = RequestFactory().get("/", data={"provider": "groq"})
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: TEST_API_CREDENTIAL,
    )
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response(
            {
                "data": [
                    {"id": "zz-custom", "context_length": 1024},
                    {"id": "llama-3.1-8b-instant", "context_length": 4096},
                ]
            }
        ),
    )

    response = inspect.unwrap(ai_credentials_view.list_models)(request, conn=None)

    assert response.status_code == 200
    assert _json_payload(response) == {
        "models": [
            {"context_length": 4096, "id": "llama-3.1-8b-instant"},
            {"context_length": 1024, "id": "zz-custom"},
        ],
        "default_model": "llama-3.1-8b-instant",
        "supports_models": True,
    }

    input_limit = int("100")
    output_limit = int("20")

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response(
            {
                "models": [
                    {
                        "name": "models/gemini-1.5-pro",
                        "displayName": "Gemini Pro",
                        "inputTokenLimit": input_limit,
                        "outputTokenLimit": output_limit,
                    }
                ]
            }
        ),
    )
    gemini_response = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "gemini"}),
        conn=None,
    )
    assert _json_payload(gemini_response) == {
        "models": [
            {
                "display_name": "Gemini Pro",
                "id": "gemini-1.5-pro",
                "input_token_limit": input_limit,
                "output_token_limit": output_limit,
            }
        ],
        "default_model": "gemini-1.5-pro",
        "supports_models": True,
    }

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response(
            {"models": [{"name": "command-r-plus"}, {"id": "command-r"}]}
        ),
    )
    cohere_response = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "cohere"}),
        conn=None,
    )
    assert _json_payload(cohere_response) == {
        "models": [
            {"context_length": None, "id": "command-r"},
            {"context_length": None, "id": "command-r-plus"},
        ],
        "default_model": "command-r",
        "supports_models": True,
    }


def test_list_models_handles_missing_inputs_http_errors_and_unknown_providers(
    monkeypatch,
):
    """Verify list models handles missing inputs HTTP errors and unknown providers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in list models handles missing inputs HTTP errors and unknown providers.
    """
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: TEST_API_CREDENTIAL,
    )

    empty_provider = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": ""}),
        conn=None,
    )
    assert _json_payload(empty_provider) == {
        "models": [],
        "default_model": None,
        "supports_models": False,
    }

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "")
    missing_user = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert missing_user.status_code == 400

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: (_ for _ in ()).throw(
            ai_credentials_view.AiCredentialStoreError("db unavailable")
        ),
    )
    store_error = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert store_error.status_code == 500

    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: "",
    )
    no_key = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert no_key.status_code == 400

    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: TEST_API_CREDENTIAL,
    )
    perplexity = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "perplexity"}),
        conn=None,
    )
    unknown = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "unknown"}),
        conn=None,
    )
    assert _json_payload(perplexity) == {
        "models": [],
        "default_model": None,
        "supports_models": False,
    }
    assert _json_payload(unknown) == {
        "models": [],
        "default_model": None,
        "supports_models": False,
    }

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(
            _http_error(code=403, body="credits exhausted")
        ),
    )
    http_error = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert http_error.status_code == 400
    assert "403" in _json_payload(http_error)["error"]
    assert "credits exhausted" not in _json_payload(http_error)["error"]

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response("plain response error", status=429),
    )
    http_response = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert http_response.status_code == 400
    assert "429" in _json_payload(http_response)["error"]
    assert "plain response error" not in _json_payload(http_response)["error"]

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    unexpected = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert unexpected.status_code == 500


def test_perform_connection_test_covers_success_http_error_and_exception(monkeypatch):
    """Confirm perform connection test covers success HTTP error and exception exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when perform connection test covers success HTTP error and exception stops reporting the expected error.
    """
    seen = {}
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (
            seen.update(
                {
                    "url": kwargs["url"],
                    "auth": kwargs["headers"].get("Authorization"),
                    "timeout": kwargs["timeout"],
                }
            )
            or _Response({}, status=204)
        ),
    )

    ok, message = ai_credentials_view._perform_connection_test(
        "groq", TEST_API_CREDENTIAL
    )
    assert ok is True
    assert message == ai_credentials_view.errors.connection_test_passed()
    assert seen["url"] == "https://api.groq.com/openai/v1/models"
    assert seen["auth"] == f"Bearer {TEST_API_CREDENTIAL}"
    assert seen["timeout"] == 8

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response("insufficient credits", status=403),
    )
    ok, message = ai_credentials_view._perform_connection_test(
        "xai", TEST_API_CREDENTIAL
    )
    assert ok is False
    assert "insufficient credits" not in message
    assert "paid credits" in message

    xai_error = _http_error(code=403, body="insufficient credits")
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(xai_error),
    )
    ok, message = ai_credentials_view._perform_connection_test(
        "xai", TEST_API_CREDENTIAL
    )
    assert ok is False
    assert "paid credits" in message

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(
            ai_credentials_view.requests.RequestException("network down")
        ),
    )
    ok, message = ai_credentials_view._perform_connection_test(
        "groq", TEST_API_CREDENTIAL
    )
    assert ok is False
    assert message == ai_credentials_view.errors.connection_test_failed()

    ok, message = ai_credentials_view._perform_connection_test("", "")
    assert ok is False
    assert message == ai_credentials_view.errors.provider_and_key_required()


def test_ai_credentials_helper_edges_cover_parser_and_transport_failures(
    monkeypatch,
):
    """Check ai credentials helper edges cover parser and transport failures parsing against the documented contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in ai credentials helper edges cover parser and transport failures.
    """
    assert (
        ai_credentials_view._validated_provider_url("https://api.example.test/models#x")
        == "https://api.example.test/models"
    )
    with pytest.raises(ValueError):
        ai_credentials_view._validated_provider_url("http://")
    with pytest.raises(ValueError):
        ai_credentials_view._validated_provider_url("ftp://api.example.test/models")

    assert ai_credentials_view._select_default_model("unknown", ["m2", "m1"]) == "m2"
    assert ai_credentials_view._select_default_model("groq", []) is None
    assert ai_credentials_view._parse_openai_style_models(
        {"data": [{"context_length": 7}, {"id": "model-a", "context_length": 9}]}
    ) == [{"id": "model-a", "context_length": 9}]
    assert ai_credentials_view._parse_anthropic_models(
        {"data": [{"foo": "bar"}, {"id": "claude-3"}]}
    ) == [{"id": "claude-3"}]
    parsed_gemini_models = ai_credentials_view._parse_gemini_models(
        {
            "models": [
                {"displayName": "skip"},
                {"name": "models/gemini-2.0", "displayName": "Gemini 2"},
            ]
        }
    )
    assert len(parsed_gemini_models) == 1
    assert parsed_gemini_models[0]["id"] == "gemini-2.0"
    assert parsed_gemini_models[0]["display_name"] == "Gemini 2"
    assert parsed_gemini_models[0]["input_token_limit"] is None
    assert parsed_gemini_models[0]["output_token_limit"] is None
    assert ai_credentials_view._parse_cohere_models(
        {
            "models": [{"context_length": 1}, {"name": "command-r-plus"}],
            "data": [{"foo": "bar"}, {"id": "command-r"}],
        }
    ) == [
        {"id": "command-r-plus", "context_length": None},
        {"id": "command-r"},
    ]

    ok, message = ai_credentials_view._perform_connection_test("unknown", "token")
    assert ok is False
    assert message == ai_credentials_view.errors.connection_test_not_supported(
        "unknown"
    )

    ai_credentials_view._PROVIDER_TESTS["fixture-post"] = {
        "url": "https://api.example.test/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "method": "POST",
        "payload": {"hello": "world"},
    }
    captured = {}
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: captured.update(kwargs) or _Response({}, status=204),
    )
    ok, message = ai_credentials_view._perform_connection_test("fixture-post", "token")
    assert ok is True
    assert message == ai_credentials_view.errors.connection_test_passed()
    assert json.loads(captured["data"].decode("utf-8")) == {"hello": "world"}

    ai_credentials_view._PROVIDER_TESTS["fixture-invalid"] = {
        "url": urlunsplit(("http", "api.example.test", "/models", "", "")),
        "headers": lambda key: {},
    }
    ok, message = ai_credentials_view._perform_connection_test(
        "fixture-invalid", "token"
    )
    assert ok is False
    assert message == ai_credentials_view.errors.connection_test_failed()

    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: TEST_API_CREDENTIAL,
    )

    request = inspect.unwrap(ai_credentials_view.test_credentials)(
        RequestFactory().get("/"),
        conn=None,
    )
    assert request.status_code == 405

    save_method = inspect.unwrap(ai_credentials_view.save_credentials)(
        RequestFactory().get("/"),
        conn=None,
    )
    assert save_method.status_code == 405

    list_method = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().post("/", data={"provider": "groq"}),
        conn=None,
    )
    assert list_method.status_code == 405

    request_exc = ai_credentials_view.requests.RequestException("too many requests")
    request_exc.response = _Response("limited", status=429)
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(request_exc),
    )
    rate_limited = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert rate_limited.status_code == 400
    assert "429" in _json_payload(rate_limited)["error"]

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: (_ for _ in ()).throw(
            ai_credentials_view.requests.RequestException("network down")
        ),
    )
    request_error = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert request_error.status_code == 500

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response("not-json", status=200),
    )
    invalid_json = inspect.unwrap(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "groq"}),
        conn=None,
    )
    assert invalid_json.status_code == 500
