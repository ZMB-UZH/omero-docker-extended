import json
import logging
import re
import urllib.error
import urllib.request
from collections import Counter
from .filename_utils import (
    build_hyphen_protection_pattern,
    detect_label_value_pairs,
    extract_base_name,
    regex_for_separators,
)
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
        return regex_for_separators([], filenames=filenames)
    
    top = counts.most_common()
    max_count = top[0][1]
    candidates = [char for char, count in top if count >= max_count * 0.4]
    
    # Pass filenames for intelligent pattern detection
    return regex_for_separators(candidates[:5], filenames=filenames)


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


def _separator_candidates(filenames):
    counts = Counter()
    for name in filenames:
        base = extract_base_name(name)
        for char in base:
            if char in COMMON_SEPARATORS:
                counts[char] += 1
    if not counts:
        return []
    top = counts.most_common()
    max_count = top[0][1]
    return [char for char, count in top if count >= max_count * 0.4][:6]


def _build_hyphen_hint(filenames):
    has_pairs, detected_labels = detect_label_value_pairs(filenames)
    if not has_pairs:
        detected_labels = None
    return build_hyphen_protection_pattern(detected_labels)


def _build_prompt(filenames, strict=False):
    sample = filenames[:60]
    list_block = "\n".join(f"- {name}" for name in sample)
    separators = _summarize_separators(filenames)
    separator_hint = f"Common separators observed: {separators}\n" if separators else ""
    strict_lines = ""
    if strict:
        candidates = _separator_candidates(filenames)
        if candidates:
            strict_lines += (
                "Use only the following separators when building the regex: "
                f"{', '.join(repr(c) for c in candidates)}.\n"
            )
        if "-" in candidates:
            hyphen_hint = _build_hyphen_hint(filenames)
            strict_lines += (
                "If you need to split on hyphens, prefer this hyphen-safe pattern: "
                f"{hyphen_hint}\n"
            )
    return (
        "You generate a single regex pattern suitable for re.split.\n"
        "The regex must match separators (not tokens) and avoid capturing groups.\n"
        "Prefer a simple character-class or alternation using delimiters that appear.\n"
        "Avoid complex lookarounds unless absolutely required.\n"
        "Do not return a single separator unless it is the only delimiter present.\n"
        "Return only the regex pattern with no explanation or code fences.\n"
        f"{separator_hint}"
        f"{strict_lines}"
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
    else:
        inline = re.search(r"`([^`]+)`", cleaned)
        if inline:
            cleaned = inline.group(1).strip()
    if cleaned.lower().startswith("regex:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0]
    if "regex:" in first.lower():
        first = first.split(":", 1)[1].strip()
    return first.strip().strip("'\"")


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
    if non_trivial == 0:
        return False
    return non_trivial / len(split_counts) >= 0.1


def _extract_single_separator(regex):
    if not regex:
        return None
    candidate = regex.strip()
    if re.fullmatch(r"\\s", candidate):
        return " "
    match = re.fullmatch(r"\\?.", candidate)
    if match:
        return match.group(0).lstrip("\\")
    wrapped = re.fullmatch(r"\(\?:(.+)\)\+?", candidate)
    if wrapped:
        inner = wrapped.group(1)
        match = re.fullmatch(r"\\?.", inner)
        if match:
            return match.group(0).lstrip("\\")
        if re.fullmatch(r"\\s", inner):
            return " "
    return None


def _is_regex_too_generic(regex, filenames):
    candidates = _separator_candidates(filenames)
    if len(candidates) <= 1:
        return False
    single = _extract_single_separator(regex)
    if single and single in candidates:
        return True
    return False


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

    if not _is_regex_reasonable(regex, filenames) or _is_regex_too_generic(regex, filenames):
        retry_prompt = _build_prompt(filenames, strict=True)
        if provider in _OPENAI_COMPATIBLE:
            retry_regex = _openai_like(provider, api_key, retry_prompt)
        elif provider == "anthropic":
            retry_regex = _anthropic(api_key, retry_prompt)
        elif provider == "google":
            retry_regex = _google(api_key, retry_prompt)
        elif provider == "cohere":
            retry_regex = _cohere(api_key, retry_prompt)
        else:
            retry_regex = ""
        if retry_regex and _is_regex_reasonable(retry_regex, filenames) and not _is_regex_too_generic(
            retry_regex, filenames
        ):
            regex = retry_regex
        else:
            regex = ""
    if not regex or not _is_regex_reasonable(regex, filenames):
        fallback = _suggest_separator_regex(filenames)
        if fallback:
            if fallback != regex:
                logger.warning("AI regex looked unreliable; using heuristic suggestion.")
            return {
                "regex": fallback,
                "source": "fallback",
                "ai_regex": regex,
                "fallback_reason": "ai_regex_unreliable",
            }
    return {"regex": regex, "source": "ai", "ai_regex": regex}
