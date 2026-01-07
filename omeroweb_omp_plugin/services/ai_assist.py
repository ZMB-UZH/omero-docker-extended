import json
import logging
import re
import urllib.error
import urllib.request
from collections import Counter
from .filename_utils import extract_base_name, regex_for_separators
from ..constants import COMMON_SEPARATORS

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
        "model": "sonar",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
}


def _suggest_separator_regex(filenames):
    counts = Counter()
    for name in filenames:
        base = extract_base_name(name)
        for char in base:
            if char in COMMON_SEPARATORS:
                counts[char] += 1
    if not counts:
        return _regex_for_separators([])
    top = counts.most_common()
    max_count = top[0][1]
    candidates = [char for char, count in top if count >= max_count * 0.4]
    return regex_for_separators(candidates[:5])


def _summarize_separators(filenames):
    counts = Counter()
    for name in filenames:
        base = extract_base_name(name)
        for char in base:
            if char in COMMON_SEPARATORS:
                counts[char] += 1
    if not counts:
        return ""
    top = [char for char, _ in counts.most_common(6)]
    return ", ".join(repr(char) for char in top)


def _build_prompt(filenames):
    sample = filenames[:60]
    list_block = "\n".join(f"- {name}" for name in sample)
    separators = _summarize_separators(filenames)
    separator_hint = f"Common separators observed: {separators}\n" if separators else ""
    return (
        "You generate a single regex pattern suitable for re.split.\n"
        "The regex must match separators (not tokens) and avoid capturing groups.\n"
        "Prefer a simple character-class or alternation using common delimiters.\n"
        "Return only the regex pattern with no explanation or code fences.\n"
        f"{separator_hint}"
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


def _extract_error_details(error):
    if not error:
        return None
    try:
        raw = error.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="ignore").strip() or None
    if isinstance(payload, dict):
        info = payload.get("error") or payload.get("message")
        if isinstance(info, dict):
            message = info.get("message")
            if message:
                return message
        if isinstance(info, str):
            return info
    return None


def _post_json(url, headers, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _extract_error_details(exc)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        logger.warning(
            "AI provider HTTP error %s from %s (detail=%s)",
            exc.code,
            url,
            detail or "n/a",
        )
        message = f"Provider returned status {exc.code}."
        if detail:
            message = f"{message} {detail}"
        if retry_after:
            message = f"{message} Retry after {retry_after} seconds."
        raise AiAssistError(message)
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
        "temperature": 0.0,
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
        "temperature": 0.0,
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
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 120},
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
        "temperature": 0.0,
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


def _is_regex_reasonable(regex, filenames):
    if not regex:
        return False
    sample = filenames[:30]
    if not sample:
        return True
    has_separator = False
    for name in sample:
        base = extract_base_name(name)
        if any(not char.isalnum() for char in base):
            has_separator = True
            break
    try:
        split_counts = []
        for name in sample:
            base = extract_base_name(name)
            parts = [p for p in re.split(regex, base) if p]
            split_counts.append(len(parts))
    except re.error:
        return False

    if not has_separator:
        return True

    non_trivial = sum(count > 1 for count in split_counts)
    return non_trivial / len(split_counts) >= 0.4


def generate_ai_regex(provider, api_key, filenames):
    provider = (provider or "").strip().lower()
    if not provider:
        raise AiAssistError("Provider is required.")
    if provider in {"aws", "azure"}:
        raise AiAssistError("Provider requires additional configuration.")
    prompt = _build_prompt(filenames)
    if provider in _OPENAI_COMPATIBLE:
        regex = _openai_like(provider, api_key, prompt)
    elif provider == "anthropic":
        regex = _anthropic(api_key, prompt)
    elif provider == "google":
        regex = _google(api_key, prompt)
    elif provider == "cohere":
        regex = _cohere(api_key, prompt)
    else:
        raise AiAssistError(f"Provider '{provider}' is not supported.")

    if not _is_regex_reasonable(regex, filenames):
        fallback = _suggest_separator_regex(filenames)
        if fallback and fallback != regex:
            logger.warning("AI regex looked unreliable; using heuristic suggestion.")
            return fallback
    return regex
