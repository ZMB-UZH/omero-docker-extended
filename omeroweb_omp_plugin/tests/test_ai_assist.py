import io
import json
import urllib.error

import pytest

from omeroweb_omp_plugin.services import ai_assist


def test_generate_ai_regex_accepts_reasonable_separator_pattern(monkeypatch):
    filenames = [
        "sample_cond_ctrl_rep_3_ch_DAPI.tif",
        "sample_cond_treated_rep_4_ch_GFP.tif",
    ]

    monkeypatch.setattr(
        ai_assist, "_call_ai_provider_raw", lambda *args, **kwargs: "(?:_)+"
    )

    result = ai_assist.generate_ai_regex("groq", "token", filenames)

    assert result == {"regex": "(?:_)+", "source": "ai", "ai_regex": "(?:_)+"}

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist.generate_ai_regex("groq", "token", [])


def test_generate_ai_regex_falls_back_when_pattern_is_too_generic(monkeypatch):
    filenames = [
        "sample_cond_ctrl_rep_3_ch_DAPI.tif",
        "sample_cond_treated_rep_4_ch_GFP.tif",
    ]

    monkeypatch.setattr(ai_assist, "_call_ai_provider_raw", lambda *args, **kwargs: ".")

    result = ai_assist.generate_ai_regex("groq", "token", filenames)

    assert result["source"] == "fallback"
    assert result["ai_regex"] == ""
    assert result["fallback_reason"] == "ai_regex_unreliable"
    assert "_" in result["regex"]


def test_prompt_and_regex_helpers_cover_strict_hints_cleanup_and_validation():
    filenames = [
        "10444-ec-01-sa-01-sc-01-20x.tif",
        "10445-ec-02-sa-03-sc-04-40x.tif",
    ]

    prompt = ai_assist._build_prompt(filenames, strict=True)

    assert "Use only the following separators" in prompt
    assert "hyphen-safe pattern" in prompt
    assert (
        ai_assist._extract_cohere_response_text(
            {"message": {"content": [{"text": "alpha"}, "beta"]}}
        )
        == "alphabeta"
    )
    assert ai_assist._clean_regex("```regex\n(?:-|_)+\n```") == "(?:-|_)+"
    assert ai_assist._clean_regex("Regex: `(?:-|_)+`") == "(?:-|_)+"
    assert ai_assist._is_regex_reasonable("(?:-|_)+", filenames) is True
    assert ai_assist._is_regex_reasonable("(.+)", filenames) is False
    assert ai_assist._is_regex_too_generic(".", filenames) is True


def test_post_json_and_provider_dispatch_cover_success_and_failure_paths(monkeypatch):
    captured = []

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=15):
        captured.append(
            (request.full_url, dict(request.headers), request.data, timeout)
        )
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(ai_assist.urllib.request, "urlopen", fake_urlopen)

    assert ai_assist._post_json(
        "https://api.example.test/v1/chat",
        {"Authorization": "Bearer token"},
        {"hello": "world"},
        timeout=7,
    ) == {"ok": True}
    assert captured[0][0] == "https://api.example.test/v1/chat"
    assert json.loads(captured[0][2].decode("utf-8")) == {"hello": "world"}
    assert captured[0][3] == 7

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._post_json("http://api.example.test/v1/chat", {}, {})

    def raise_http_error(request, timeout=15):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "too many requests",
            {"Retry-After": "11"},
            io.BytesIO(b'{"error": {"message": "slow down"}}'),
        )

    monkeypatch.setattr(ai_assist.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(ai_assist.AiAssistError) as exc_info:
        ai_assist._post_json("https://api.example.test/v1/chat", {}, {})
    assert "429" in str(exc_info.value)
    assert "11" in str(exc_info.value)

    monkeypatch.setattr(
        ai_assist.urllib.request,
        "urlopen",
        lambda request, timeout=15: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")
        ),
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._post_json("https://api.example.test/v1/chat", {}, {})

    provider_calls = []

    def fake_post_json(url, headers, payload, timeout=15):
        provider_calls.append((url, headers, payload))
        if "anthropic" in url:
            return {"content": [{"text": "claude-output"}]}
        if "generativelanguage" in url:
            return {"candidates": [{"content": {"parts": [{"text": "gemini-output"}]}}]}
        if "cohere" in url:
            return {"response": "cohere-output"}
        return {"choices": [{"message": {"content": "openai-compatible-output"}}]}

    monkeypatch.setattr(ai_assist, "_post_json", fake_post_json)

    assert (
        ai_assist._call_ai_provider_raw("groq", "token", "prompt", 64)
        == "openai-compatible-output"
    )
    assert (
        ai_assist._call_ai_provider_raw("claude", "token", "prompt", 64)
        == "claude-output"
    )
    assert (
        ai_assist._call_ai_provider_raw(
            "gemini", "api+key", "prompt", 64, model="flash 2"
        )
        == "gemini-output"
    )
    assert (
        ai_assist._call_ai_provider_raw("cohere", "token", "prompt", 64)
        == "cohere-output"
    )
    assert "models/flash%202:generateContent?key=api%2Bkey" in provider_calls[2][0]

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._call_ai_provider_raw("unknown", "token", "prompt", 64)

    monkeypatch.setattr(
        ai_assist, "_post_json", lambda *args, **kwargs: {"choices": []}
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._call_ai_provider_raw("groq", "token", "prompt", 64)


def test_generate_ai_regex_retries_with_strict_prompt_before_accepting_result(
    monkeypatch,
):
    prompts = []

    def fake_call(provider, api_key, prompt, max_tokens, model=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "."
        return "(?:-|_)+"

    filenames = [
        "sample-cond_ctrl-rep-3-ch-DAPI.tif",
        "sample-cond_treated-rep-4-ch-GFP.tif",
    ]

    monkeypatch.setattr(ai_assist, "_call_ai_provider_raw", fake_call)

    result = ai_assist.generate_ai_regex("groq", "token", filenames)

    assert result == {"regex": "(?:-|_)+", "source": "ai", "ai_regex": "(?:-|_)+"}
    assert len(prompts) == 2
    assert "Use only the following separators" in prompts[1]


def test_parse_prompt_rows_and_generate_ai_parsed_values_cover_validation(monkeypatch):
    filenames = ["10444-ec-01-sa-01.tif", "10445-ec-02-sa-03.tif"]
    prompt = ai_assist._build_parse_prompt(
        filenames, custom_instructions="Keep microscope magnification suffixes."
    )

    assert "USER CUSTOM INSTRUCTIONS" in prompt
    assert "Keep microscope magnification suffixes." in prompt
    assert ai_assist._parse_ai_value_rows("10444,01,01\n10445,02,03", 2) == [
        ["10444", "01", "01"],
        ["10445", "02", "03"],
    ]

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._parse_ai_value_rows("only-one-line", 2)

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._parse_ai_value_rows(
            "10444-ec-01-sa-01\n10445,02,03", 2, filenames=filenames
        )

    monkeypatch.setattr(
        ai_assist,
        "_call_ai_provider_raw",
        lambda *args, **kwargs: "10444,01,01\n10445,02,03",
    )

    parsed = ai_assist.generate_ai_parsed_values("groq", "token", filenames)

    assert parsed == {
        "rows": [
            {"filename": "10444-ec-01-sa-01.tif", "values": ["10444", "01", "01"]},
            {"filename": "10445-ec-02-sa-03.tif", "values": ["10445", "02", "03"]},
        ],
        "source": "ai",
    }

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist.generate_ai_parsed_values("", "token", filenames)

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist.generate_ai_parsed_values("groq", "token", [])
