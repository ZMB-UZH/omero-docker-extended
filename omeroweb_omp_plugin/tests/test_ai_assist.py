import json
from urllib.parse import urlunsplit

import pytest

from omeroweb_omp_plugin.services import ai_assist


def test_generate_ai_regex_accepts_reasonable_separator_pattern(monkeypatch):
    """Verify generate ai regex accepts reasonable separator pattern.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in generate ai regex accepts reasonable separator pattern.
    """
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
    """Verify generate ai regex falls back when pattern is too generic.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in generate ai regex falls back when pattern is too generic.
    """
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
    """Check prompt and regex helpers cover strict hints cleanup and validation cleanup behavior.

    Inputs: OMP service fakes. Output: fails on regressions in prompt and regex helpers cover strict hints cleanup and validation.
    """
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


def test_ai_regex_validation_uses_safe_separator_parser(monkeypatch):
    """Check AI regex validation avoids Python regex splitting.

    Inputs: pytest `monkeypatch`. Output: asserts separator parser behavior.
    """
    filenames = [
        "sample-cond-ctrl_rep-3.tif",
        "sample-cond-treated_rep-4.tif",
    ]

    def fail_split(*_args, **_kwargs):
        """Raise if the unsafe regex split engine is used.

        Inputs: ignored split args. Output: raises AssertionError.
        """
        raise AssertionError("re.split must not validate AI regex suggestions")

    monkeypatch.setattr(ai_assist.re, "split", fail_split)

    assert ai_assist._is_regex_reasonable("(?:-|_)+", filenames) is True
    assert ai_assist._is_regex_reasonable("(a+)+", filenames) is False
    assert ai_assist._is_regex_too_generic("(a+)+", filenames) is True


def test_post_json_and_provider_dispatch_cover_success_and_failure_paths(monkeypatch):
    """Verify post JSON and provider dispatch cover success and failure paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in post JSON and provider dispatch cover success and failure paths.
    Raises: exc when validation or the called operation fails.
    """
    captured = []

    class _Response:
        """Test double for response behavior in this module."""

        def __init__(self, payload, status_code=200, headers=None):
            """Create `_Response` with `payload`, `status_code`, and `headers`.

            Inputs: `payload`, `status_code`, `headers`. Output: None.
            """
            self.payload = payload
            self.status_code = status_code
            self.headers = headers or {}
            self.text = payload.decode("utf-8")

        def json(self):
            """Return the JSON payload.

            Inputs: none. Output: `json.loads` result.
            """
            return json.loads(self.payload.decode("utf-8"))

        def raise_for_status(self):
            """Raise the configured HTTP error for this fake response.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            if self.status_code >= 400:
                exc = ai_assist.requests.HTTPError("request failed")
                exc.response = self
                raise exc

    def fake_post(url, headers=None, data=None, timeout=15):
        """Simulate post so the surrounding test controls that dependency.

        Inputs: `url` URL, `headers`, `data` payload, `timeout` timeout seconds. Output:
        `_Response` result.
        """
        captured.append((url, dict(headers or {}), data, timeout))
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(ai_assist.requests, "post", fake_post)

    assert ai_assist._post_json(
        "https://api.example.test/v1/chat",
        {"Authorization": "Bearer token"},
        {"hello": "world"},
        timeout=7,
    ) == {"ok": True}
    assert captured[0][0] == "https://api.example.test/v1/chat"
    assert json.loads(captured[0][2].decode("utf-8")) == {"hello": "world"}
    assert captured[0][3] == 7

    insecure_url = urlunsplit(("http", "api.example.test", "/v1/chat", "", ""))
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._post_json(insecure_url, {}, {})

    def raise_http_error(url, headers=None, data=None, timeout=15):
        """Record the raise http error call on the test double for later assertions.

        Inputs: `url` URL, `headers`, `data` payload, `timeout` timeout seconds. Output:
        None. Raises: exc when validation or the called operation fails.
        """
        response = _Response(
            b'{"error": {"message": "slow down"}}',
            status_code=429,
            headers={"Retry-After": "11"},
        )
        exc = ai_assist.requests.HTTPError("too many requests")
        exc.response = response
        raise exc

    monkeypatch.setattr(ai_assist.requests, "post", raise_http_error)
    with pytest.raises(ai_assist.AiAssistError) as exc_info:
        ai_assist._post_json("https://api.example.test/v1/chat", {}, {})
    assert "429" in str(exc_info.value)
    assert "11" in str(exc_info.value)

    monkeypatch.setattr(
        ai_assist.requests,
        "post",
        lambda url, headers=None, data=None, timeout=15: (_ for _ in ()).throw(
            ai_assist.requests.RequestException("connection refused")
        ),
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._post_json("https://api.example.test/v1/chat", {}, {})

    provider_calls = []

    def fake_post_json(url, headers, payload, timeout=15):
        """Simulate post JSON so the surrounding test controls that dependency.

        Inputs: `url` URL, `headers`, `payload` payload, `timeout` timeout seconds.
        Output: `dict`.
        """
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
    """Verify generate ai regex retries with strict prompt before accepting result result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in generate ai regex retries with strict prompt before accepting result.
    """
    prompts = []

    def fake_call(provider, api_key, prompt, max_tokens, model=None):
        """Simulate call so the surrounding test controls that dependency.

        Inputs: `provider`, `api_key`, `prompt`, `max_tokens`, `model`. Output: `str`.
        """
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
    """Verify parse prompt rows and generate ai parsed values cover validation.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in parse prompt rows and generate ai parsed values cover validation.
    """
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


def test_ai_assist_helper_edges_cover_empty_inputs_and_provider_shape_failures(
    monkeypatch,
):
    """Verify ai assist helper edges cover empty inputs and provider shape failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in ai assist helper edges cover empty inputs and provider shape failures.
    """
    filenames = [
        "sample_A-01.tif",
        "sample_B-02.tif",
    ]

    assert ai_assist._extract_cohere_response_text(None) is None
    assert ai_assist._extract_cohere_response_text({"text": "direct"}) == "direct"
    assert (
        ai_assist._extract_cohere_response_text({"message": {"content": "message"}})
        == "message"
    )
    assert (
        ai_assist._extract_cohere_response_text(
            {"message": {"content": [{"ignored": True}]}}
        )
        is None
    )
    assert ai_assist._summarize_separators(["plain"]) == ""
    assert ai_assist._separator_candidates(["plain"]) == []
    assert ai_assist._clean_regex("") == ""
    assert ai_assist._clean_regex("  \n  ") == ""
    assert ai_assist._clean_regex("Regex: (?:_|-)+") == "(?:_|-)+"
    assert ai_assist._clean_regex("pattern regex: (?:_)+") == "(?:_)+"
    assert ai_assist._is_regex_reasonable("", filenames) is False
    assert ai_assist._is_regex_reasonable("(", filenames) is False
    assert ai_assist._is_regex_reasonable(".*", filenames) is False
    assert ai_assist._is_regex_reasonable("ZZZ", filenames) is False
    assert ai_assist._is_regex_too_generic("", filenames) is True
    assert ai_assist._is_regex_too_generic("(", filenames) is True
    assert ai_assist._is_regex_too_generic(".*", filenames) is True
    assert ai_assist._is_regex_too_generic("_", ["plain"]) is False
    assert (
        ai_assist._is_regex_too_generic(
            "-",
            ["a-b-c-d-e-f-g-h-i", "j-k-l-m-n-o-p-q-r"],
        )
        is True
    )

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._parse_ai_value_rows("", 1)

    original_extract_base_name = ai_assist.extract_base_name
    monkeypatch.setattr(
        ai_assist,
        "extract_base_name",
        lambda name: (
            (_ for _ in ()).throw(RuntimeError("bad name"))
            if name == "sample_A-01.tif"
            else "sample_B-02"
        ),
    )
    assert ai_assist._parse_ai_value_rows("alpha\nbeta", 2, filenames=filenames) == [
        ["alpha"],
        ["beta"],
    ]
    monkeypatch.setattr(ai_assist, "extract_base_name", original_extract_base_name)
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._parse_ai_value_rows(",\nvalue", 2)

    monkeypatch.setattr(
        ai_assist, "_post_json", lambda *_args, **_kwargs: {"content": []}
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._call_ai_provider_raw("claude", "token", "prompt", 64)

    monkeypatch.setattr(
        ai_assist, "_post_json", lambda *_args, **_kwargs: {"candidates": []}
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._call_ai_provider_raw("gemini", "token", "prompt", 64)

    monkeypatch.setattr(
        ai_assist, "_post_json", lambda *_args, **_kwargs: {"message": {}}
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist._call_ai_provider_raw("cohere", "token", "prompt", 64)

    with pytest.raises(ai_assist.AiAssistError):
        ai_assist.generate_ai_regex("", "token", filenames)

    monkeypatch.setattr(
        ai_assist, "_call_ai_provider_raw", lambda *_args, **_kwargs: ""
    )
    with pytest.raises(ai_assist.AiAssistError):
        ai_assist.generate_ai_regex("groq", "token", filenames)
