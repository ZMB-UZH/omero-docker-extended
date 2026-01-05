import json
import logging
import urllib.error
import urllib.request

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import (
    AiCredentialStoreError,
    list_ai_credentials,
    save_ai_credentials,
)


logger = logging.getLogger(__name__)

_PROVIDER_TESTS = {
    "openai": {
        "url": "https://api.openai.com/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/models",
        "headers": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
    },
    "google": {
        "url": lambda key: f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        "headers": lambda key: {},
    },
    "cohere": {
        "url": "https://api.cohere.ai/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "perplexity": {
        "url": "https://api.perplexity.ai/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "xai": {
        "url": "https://api.x.ai/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
}

_UNSUPPORTED_TEST_MESSAGE = {
    "aws": "AWS Bedrock requires additional server-side configuration. Connection test is not available.",
    "azure": "Azure OpenAI requires an endpoint and deployment configuration. Connection test is not available.",
}


def _perform_connection_test(provider, api_key):
    provider = (provider or "").strip().lower()
    api_key = (api_key or "").strip()
    if not provider or not api_key:
        return False, "Provider and API key are required."

    if provider in _UNSUPPORTED_TEST_MESSAGE:
        return False, _UNSUPPORTED_TEST_MESSAGE[provider]

    config = _PROVIDER_TESTS.get(provider)
    if not config:
        return False, f"Connection testing is not supported for provider '{provider}'."

    url = config["url"](api_key) if callable(config["url"]) else config["url"]
    headers = config["headers"](api_key)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = response.getcode()
            if 200 <= status < 300:
                return True, "Connection test passed."
            return False, f"Connection test failed with status {status}."
    except urllib.error.HTTPError as e:
        return False, f"Connection test failed with status {e.code}."
    except Exception as e:
        logger.exception("AI credential connection test failed for %s: %s", provider, e)
        return False, "Connection test failed. Please verify the API key."


def _current_username(request, conn):
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None


@csrf_exempt
@login_required()
def list_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)

    username = _current_username(request, conn)
    if not username:
        return JsonResponse({"error": "Unable to determine username."}, status=400)

    try:
        providers = list_ai_credentials(username)
        return JsonResponse({"providers": providers})
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error listing AI credentials: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)


@csrf_exempt
@login_required()
def test_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = request.POST

        provider = (data.get("provider") or "").strip()
        api_key = (data.get("api_key") or "").strip()

        ok, message = _perform_connection_test(provider, api_key)
        if not ok:
            return JsonResponse({"error": message}, status=400)
        return JsonResponse({"message": message})
    except Exception as e:
        logger.exception("Unexpected error testing AI credentials: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)


@csrf_exempt
@login_required()
def save_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    username = _current_username(request, conn)
    if not username:
        return JsonResponse({"error": "Unable to determine username."}, status=400)

    try:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = request.POST

        provider = (data.get("provider") or "").strip()
        api_key = (data.get("api_key") or "").strip()

        ok, message = _perform_connection_test(provider, api_key)
        if not ok:
            return JsonResponse({"error": message}, status=400)
        save_ai_credentials(username, provider, api_key)
        return JsonResponse({"message": "API key saved."})
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving AI credentials: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)
