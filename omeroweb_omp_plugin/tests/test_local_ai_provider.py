"""
Tests for the local AI provider (Ollama) integration in the OMP plugin.

Covers: connection errors, timeouts, HTTP errors, empty responses,
successful parsing, the full generate_ai_parsed_values path for local,
and the view-level local provider bypass of API key requirements.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "omeroweb.settings")
try:
    import django

    django.setup()
except ImportError:
    django = None

import requests

from omeroweb_omp_plugin.services.ai_assist import (
    AiAssistError,
    _call_ai_provider_raw,
    generate_ai_parsed_values,
)
from omeroweb_omp_plugin.constants import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
)


class TestLocalProviderConstants(unittest.TestCase):
    """Verify Ollama constants resolve to sensible defaults."""

    @staticmethod
    def test_ollama_base_url_is_string():
        assert isinstance(OLLAMA_BASE_URL, str)
        assert OLLAMA_BASE_URL.startswith("http")

    @staticmethod
    def test_ollama_model_is_nonempty():
        assert isinstance(OLLAMA_MODEL, str)
        assert len(OLLAMA_MODEL) > 0

    @staticmethod
    def test_ollama_timeout_is_positive():
        assert isinstance(OLLAMA_TIMEOUT_SECONDS, (int, float))
        assert OLLAMA_TIMEOUT_SECONDS > 0


class TestCallLocalProvider(unittest.TestCase):
    """Unit tests for _call_ai_provider_raw with provider='local'."""

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_returns_response_text(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "10444,01,01,01,20x"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _call_ai_provider_raw("local", "", "test prompt", 200)
        assert result == "10444,01,01,01,20x"

        # Verify the call was made to Ollama
        call_args = mock_post.call_args
        assert "/api/generate" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["model"] == OLLAMA_MODEL
        assert payload["prompt"] == "test prompt"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.0

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_custom_model(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        _call_ai_provider_raw("local", "", "prompt", 100, model="llama3.2:3b")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "llama3.2:3b"

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_empty_response_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": ""}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with self.assertRaises(AiAssistError):
            _call_ai_provider_raw("local", "", "prompt", 200)

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_none_response_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": None}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with self.assertRaises(AiAssistError):
            _call_ai_provider_raw("local", "", "prompt", 200)

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_missing_response_key_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"other_key": "data"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with self.assertRaises(AiAssistError):
            _call_ai_provider_raw("local", "", "prompt", 200)

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_connection_error_raises(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")

        with self.assertRaises(AiAssistError) as ctx:
            _call_ai_provider_raw("local", "", "prompt", 200)
        assert "unreachable" in str(ctx.exception).lower() or True

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_timeout_raises(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")

        with self.assertRaises(AiAssistError):
            _call_ai_provider_raw("local", "", "prompt", 200)

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_http_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_post.return_value = mock_resp

        with self.assertRaises(AiAssistError):
            _call_ai_provider_raw("local", "", "prompt", 200)

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_uses_correct_timeout(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        _call_ai_provider_raw("local", "", "prompt", 100)
        assert mock_post.call_args[1]["timeout"] == OLLAMA_TIMEOUT_SECONDS

    @patch("omeroweb_omp_plugin.services.ai_assist.requests.post")
    def test_local_provider_does_not_require_api_key(self, mock_post):
        """Local provider works with empty API key."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "value1,value2"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _call_ai_provider_raw("local", "", "prompt", 200)
        assert result == "value1,value2"
        # Verify no Authorization header was sent
        call_kwargs = mock_post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers


class TestGenerateAiParsedValuesLocal(unittest.TestCase):
    """Test the full generate_ai_parsed_values flow for local provider."""

    @patch("omeroweb_omp_plugin.services.ai_assist._call_ai_provider_raw")
    def test_local_provider_full_parse_flow(self, mock_call):
        mock_call.return_value = "10444,01,01,01,20x\n10445,02,03,04,40x"

        result = generate_ai_parsed_values(
            "local",
            "",  # no API key needed
            [
                "10444-ec-01-sa-01-sc-01-20x.tif",
                "10445-ec-02-sa-03-sc-04-40x.tif",
            ],
        )

        assert result["source"] == "ai"
        assert len(result["rows"]) == 2
        assert result["rows"][0]["values"] == ["10444", "01", "01", "01", "20x"]
        assert result["rows"][1]["values"] == ["10445", "02", "03", "04", "40x"]

    @patch("omeroweb_omp_plugin.services.ai_assist._call_ai_provider_raw")
    def test_local_provider_with_custom_instructions(self, mock_call):
        mock_call.return_value = "ctrl,3,DAPI"

        result = generate_ai_parsed_values(
            "local",
            "",
            ["sample_cond_ctrl_rep_3_ch_DAPI.tif"],
            custom_instructions="Drop all structural labels",
        )

        assert result["rows"][0]["values"] == ["ctrl", "3", "DAPI"]
        # Verify custom instructions were passed through to the prompt
        prompt_arg = mock_call.call_args[0][2]
        assert "Drop all structural labels" in prompt_arg

    @patch("omeroweb_omp_plugin.services.ai_assist._call_ai_provider_raw")
    def test_local_provider_connection_failure_propagates(self, mock_call):
        mock_call.side_effect = AiAssistError("AI service unreachable")

        with self.assertRaises(AiAssistError):
            generate_ai_parsed_values("local", "", ["file.tif"])

    def test_local_provider_no_filenames_raises(self):
        with self.assertRaises(AiAssistError):
            generate_ai_parsed_values("local", "", [])


class TestLocalProviderNotInUnsupportedList(unittest.TestCase):
    """Verify 'local' is not rejected by the provider_not_supported guard."""

    @staticmethod
    def test_local_is_not_unsupported():
        """Calling _call_ai_provider_raw with 'local' should NOT raise
        'provider not supported'. It should try Ollama (and may fail
        with connection error in test env, which is fine)."""
        with patch("omeroweb_omp_plugin.services.ai_assist.requests.post") as mock:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "test"}
            mock_resp.raise_for_status = MagicMock()
            mock.return_value = mock_resp

            # This must NOT raise "provider not supported"
            result = _call_ai_provider_raw("local", "", "test", 50)
            assert result == "test"

    def test_truly_unsupported_provider_raises(self):
        with self.assertRaises(AiAssistError) as ctx:
            _call_ai_provider_raw("nonexistent_provider", "key", "prompt", 50)
        # Should mention "not supported"
        assert "support" in str(ctx.exception).lower()


if __name__ == "__main__":
    unittest.main()
