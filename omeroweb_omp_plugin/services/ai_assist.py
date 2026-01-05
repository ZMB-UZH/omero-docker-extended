import json
import logging
import re
import urllib.error
import urllib.request


logger = logging.getLogger(__name__)


class AiAssistError(Exception):
    """Raised when AI assistance fails."""


_OPENAI_COMPATIBLE = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-70b-versatile",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-2-latest",
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "model": "llama-3.1-sonar-small-128k-online",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
}


def _build_prompt(filenames):
    sample = filenames[:60]
    list_block = "\n".join(f"- {name}" for name in sample)
    return (
        "You generate a single regex pattern to split filenames into tokens.\n"
        "Return only the regex pattern with no explanation or code fences.\n"
        "Filenames:\n"
        f"{list_block}\n"
        "Regex:"
    )


def _clean_regex(text):
    if not text:
        return ""
    cleaned = text.strip()
    fenced = re.search(r"```(?:regex)?\s*([\s\S]+?)```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    if cleaned.lower().startswith("regex:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[0].strip().strip("'\"")


def _post_json(url, headers, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("AI provider HTTP error %s from %s", exc.code, url)
        raise AiAssistError(f"Provider returned status {exc.code}.")
    except urllib.error.URLError as exc:
        logger.warning("AI provider connection error for %s: %s", url, exc)
        raise AiAssistError("Unable to reach the AI provider.")


def _openai_like(provider, api_key, prompt):
    config = _OPENAI_COMPATIBLE.get(provider)
    if not config:
        raise AiAssistError(f"Provider '{provider}' is not supported.")
    payload = {
        "model": config["model"],
        "messages": [
            {
                "role": "system",
                "content": "Return only the regex pattern. Do not add explanations.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 120,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{config['base_url']}/chat/completions"
    response = _post_json(url, headers, payload)
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiAssistError("Provider response was missing the regex suggestion.")
    regex = _clean_regex(content)
    if not regex:
        raise AiAssistError("Provider response did not include a regex suggestion.")
    return regex


def _anthropic(api_key, prompt):
    payload = {
        "model": "claude-3-5-sonnet-20240620",
        "max_tokens": 120,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    response = _post_json("https://api.anthropic.com/v1/messages", headers, payload)
    try:
        content = response["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AiAssistError("Provider response was missing the regex suggestion.")
    regex = _clean_regex(content)
    if not regex:
        raise AiAssistError("Provider response did not include a regex suggestion.")
    return regex


def _google(api_key, prompt):
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 120},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-1.5-flash:generateContent?key={api_key}"
    )
    response = _post_json(url, {"Content-Type": "application/json"}, payload)
    try:
        content = response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AiAssistError("Provider response was missing the regex suggestion.")
    regex = _clean_regex(content)
    if not regex:
        raise AiAssistError("Provider response did not include a regex suggestion.")
    return regex


def _cohere(api_key, prompt):
    payload = {
        "model": "command-r",
        "message": prompt,
        "temperature": 0.2,
        "max_tokens": 120,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = _post_json("https://api.cohere.ai/v1/chat", headers, payload)
    content = response.get("text") or response.get("response")
    if not content:
        raise AiAssistError("Provider response was missing the regex suggestion.")
    regex = _clean_regex(content)
    if not regex:
        raise AiAssistError("Provider response did not include a regex suggestion.")
    return regex


def generate_ai_regex(provider, api_key, filenames):
    provider = (provider or "").strip().lower()
    if not provider:
        raise AiAssistError("Provider is required.")
    if provider in {"aws", "azure"}:
        raise AiAssistError("Provider requires additional configuration.")
    prompt = _build_prompt(filenames)
    if provider in _OPENAI_COMPATIBLE:
        return _openai_like(provider, api_key, prompt)
    if provider == "anthropic":
        return _anthropic(api_key, prompt)
    if provider == "google":
        return _google(api_key, prompt)
    if provider == "cohere":
        return _cohere(api_key, prompt)
    raise AiAssistError(f"Provider '{provider}' is not supported.")
