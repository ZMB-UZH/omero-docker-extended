import json
import logging
import urllib.error
import urllib.request

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import (
    AiCredentialStoreError,
    get_ai_credential,
    list_ai_credentials,
    save_ai_credentials,
)
from ..services.http_utils import extract_error_details
from ..views.utils import current_username, load_request_data
from ..strings import errors, messages


logger = logging.getLogger(__name__)

_MODEL_PREFERENCES = {
    "groq": (
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
        "llama3-8b-8192",
        "llama3-70b-8192",
    ),
    "gemini": (
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ),
    "claude": (
        "claude-3-5-sonnet-20240620",
        "claude-3-5-haiku-20241022",
    ),
    "perplexity": (
        "sonar",
        "sonar-pro",
    ),
    "xai": (
        "grok-2-latest",
    ),
    "cohere": (
        "command-r",
        "command-r-plus",
    ),
}

_OPENAI_STYLE_PROVIDERS = {"groq", "xai", "perplexity"}

_MODEL_ENDPOINTS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/models",
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "User-Agent": "omero-omp-plugin",
        },
    },
    "xai": {
        "url": "https://api.x.ai/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "perplexity": {
        "url": "https://api.perplexity.ai/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "claude": {
        "url": "https://api.anthropic.com/v1/models",
        "headers": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
    },
    "gemini": {
        "url": lambda key: f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        "headers": lambda key: {},
    },
    "cohere": {
        "url": "https://api.cohere.ai/v2/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
    },
}


_PROVIDER_TESTS = _MODEL_ENDPOINTS


def _perform_connection_test(provider, api_key):
    provider = (provider or "").strip().lower()
    api_key = (api_key or "").strip()
    if not provider or not api_key:
        return False, errors.provider_and_key_required()

    config = _PROVIDER_TESTS.get(provider)
    if not config:
        return False, errors.connection_test_not_supported(provider)

    url = config["url"](api_key) if callable(config["url"]) else config["url"]
    headers = config["headers"](api_key)
    method = config.get("method", "GET")
    payload = config.get("payload")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = response.getcode()
            if 200 <= status < 300:
                return True, errors.connection_test_passed()
            return False, errors.connection_test_failed_status(status)
    except urllib.error.HTTPError as e:
        detail = extract_error_details(e)
        message = errors.connection_test_failed_status(e.code)
        if detail:
            message = f"{message} {detail}"
        if provider == "xai" and e.code == 403:
            message = (
                f"{message} xAI accounts need paid credits to access the API."
            )
        return False, message
    except Exception as e:
        logger.exception("AI credential connection test failed for %s: %s", provider, e)
        return False, errors.connection_test_failed()


def _select_default_model(provider, model_ids):
    preferences = _MODEL_PREFERENCES.get(provider, ())
    for preferred in preferences:
        if preferred in model_ids:
            return preferred
    return model_ids[0] if model_ids else None


def _parse_openai_style_models(payload):
    models = []
    for item in payload.get("data", []) or []:
        model_id = item.get("id")
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "context_length": item.get("context_length"),
            }
        )
    return models


def _parse_anthropic_models(payload):
    models = []
    for item in payload.get("data", []) or []:
        model_id = item.get("id")
        if not model_id:
            continue
        models.append({"id": model_id})
    return models


def _parse_gemini_models(payload):
    models = []
    for item in payload.get("models", []) or []:
        name = item.get("name")
        if not name:
            continue
        model_id = name.split("/", 1)[-1]
        models.append(
            {
                "id": model_id,
                "display_name": item.get("displayName"),
                "input_token_limit": item.get("inputTokenLimit"),
                "output_token_limit": item.get("outputTokenLimit"),
            }
        )
    return models


def _parse_cohere_models(payload):
    models = []
    for item in payload.get("models", []) or []:
        model_id = item.get("name") or item.get("id")
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "context_length": item.get("context_length"),
            }
        )
    for item in payload.get("data", []) or []:
        model_id = item.get("id")
        if not model_id:
            continue
        models.append({"id": model_id})
    return models


@csrf_exempt
@login_required()
def list_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": errors.method_get_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        providers = list_ai_credentials(username)
        return JsonResponse({"providers": providers})
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error listing AI credentials: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def test_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    try:
        data = load_request_data(request)

        provider = (data.get("provider") or "").strip()
        api_key = (data.get("api_key") or "").strip()
        if not provider:
            return JsonResponse({"error": errors.provider_and_key_required()}, status=400)
        if not api_key:
            username = current_username(request, conn)
            if username:
                api_key = (get_ai_credential(username, provider) or "").strip()
        if not api_key:
            return JsonResponse({"error": errors.api_key_empty()}, status=400)

        ok, message = _perform_connection_test(provider, api_key)
        if not ok:
            return JsonResponse({"error": message}, status=400)
        return JsonResponse({"message": message})
    except Exception as e:
        logger.exception("Unexpected error testing AI credentials: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def save_credentials(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)

        provider = (data.get("provider") or "").strip()
        api_key = (data.get("api_key") or "").strip()

        ok, message = _perform_connection_test(provider, api_key)
        if not ok:
            return JsonResponse({"error": message}, status=400)
        save_ai_credentials(username, provider, api_key)
        return JsonResponse({"message": messages.api_key_saved_status()})
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving AI credentials: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def list_models(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": errors.method_get_required()}, status=405)

    provider = (request.GET.get("provider") or "").strip().lower()
    if not provider:
        return JsonResponse({"models": [], "default_model": None, "supports_models": False})

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        api_key = (get_ai_credential(username, provider) or "").strip()
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)

    if not api_key:
        return JsonResponse({"error": errors.ai_api_key_required()}, status=400)

    if provider == "perplexity":
        return JsonResponse({"models": [], "default_model": None, "supports_models": False})

    config = _MODEL_ENDPOINTS.get(provider)
    if not config:
        return JsonResponse({"models": [], "default_model": None, "supports_models": False})

    url = config["url"](api_key) if callable(config["url"]) else config["url"]
    headers = config["headers"](api_key)
    request_obj = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request_obj, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = extract_error_details(e)
        message = errors.provider_http_status(e.code)
        if detail:
            message = errors.provider_http_status_with_detail(e.code, detail)
        return JsonResponse({"error": message}, status=400)
    except Exception as e:
        logger.exception("Unexpected error fetching models for %s: %s", provider, e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)

    if provider in _OPENAI_STYLE_PROVIDERS:
        models = _parse_openai_style_models(payload)
    elif provider == "claude":
        models = _parse_anthropic_models(payload)
    elif provider == "gemini":
        models = _parse_gemini_models(payload)
    elif provider == "cohere":
        models = _parse_cohere_models(payload)
    else:
        models = []

    models.sort(key=lambda model: (model.get("id") or "").casefold())
    model_ids = [model["id"] for model in models]
    default_model = _select_default_model(provider, model_ids)

    if not models:
        return JsonResponse({"models": [], "default_model": None, "supports_models": False})

    return JsonResponse(
        {"models": models, "default_model": default_model, "supports_models": True}
    )
