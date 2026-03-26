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
