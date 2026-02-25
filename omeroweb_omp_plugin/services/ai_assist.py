import json
import logging
import re
import urllib.error
import urllib.request
import urllib.parse
from collections import Counter
from .filename_utils import (
    build_hyphen_protection_pattern,
    detect_label_value_pairs,
    extract_base_name,
    regex_for_separators,
    suggest_separator_regex,
)
from .http_utils import extract_error_details
from ..constants import COMMON_SEPARATORS
from ..strings import errors

logger = logging.getLogger(__name__)


class AiAssistError(Exception):
    """Raised when AI assistance fails."""


_OPENAI_COMPATIBLE = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-2-latest",
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "model": "sonar",
    },
}

_CLAUDE_DEFAULT_MODEL = "claude-3-5-sonnet-20240620"
_GEMINI_DEFAULT_MODEL = "gemini-1.5-flash"
_COHERE_DEFAULT_MODEL = "command-r"


def _extract_cohere_response_text(payload):
    if not payload:
        return None
    if payload.get("text"):
        return payload.get("text")
    if payload.get("response"):
        return payload.get("response")
    message = payload.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    chunks.append(text)
        if chunks:
            return "".join(chunks)
    return None


def _suggest_separator_regex(filenames):
    return suggest_separator_regex(filenames, allowed_separators=COMMON_SEPARATORS)


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


def _post_json(url, headers, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = extract_error_details(exc)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        logger.warning(
            "AI provider HTTP error %s from %s (detail=%s)",
            exc.code,
            url,
            detail or "n/a",
        )
        message = errors.provider_http_status(exc.code)
        if detail:
            message = errors.provider_http_status_with_detail(exc.code, detail)
        if retry_after:
            message = errors.provider_http_retry_after(message, retry_after)
        raise AiAssistError(message)
    except urllib.error.URLError as exc:
        logger.warning("AI provider connection error for %s: %s", url, exc)
        raise AiAssistError(errors.provider_unreachable())


def _call_ai_provider_raw(provider, api_key, prompt, max_tokens, model=None):
    provider = (provider or "").strip().lower()

    if provider in _OPENAI_COMPATIBLE:
        config = _OPENAI_COMPATIBLE[provider]
        payload = {
            "model": model or config["model"],
            "messages": [
                {
                    "role": "system",
                    "content": "Return only the requested output. No explanations.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "groq":
            headers["User-Agent"] = "omero-omp-plugin"
        url = f"{config['base_url']}/chat/completions"
        response = _post_json(url, headers, payload)
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AiAssistError(errors.provider_response_empty())

    if provider == "claude":
        payload = {
            "model": model or _CLAUDE_DEFAULT_MODEL,
            "max_tokens": max_tokens,
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
            return response["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise AiAssistError(errors.provider_response_empty())

    if provider == "gemini":
        selected_model = model or _GEMINI_DEFAULT_MODEL
        model_path = (
            selected_model
            if selected_model.startswith("models/")
            else f"models/{selected_model}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens},
        }
        # FIX: URL-encode the user-provided parts of the URL to prevent SSRF via path traversal
        # or query injection ( CodeQL #89 ). We do NOT enforce strict https allowlist to allow local proxies.
        safe_model_path = urllib.parse.quote(model_path, safe="/")
        safe_api_key = urllib.parse.quote(api_key, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{safe_model_path}:generateContent?key={safe_api_key}"
        )
        response = _post_json(url, {"Content-Type": "application/json"}, payload)
        try:
            return response["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise AiAssistError(errors.provider_response_empty())

    if provider == "cohere":
        payload = {
            "model": model or _COHERE_DEFAULT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = _post_json("https://api.cohere.ai/v2/chat", headers, payload)
        content = _extract_cohere_response_text(response)
        if not content:
            raise AiAssistError(errors.provider_response_empty())
        return content

    raise AiAssistError(errors.provider_not_supported(provider))


def generate_ai_regex(provider, api_key, filenames, model=None):
    provider = (provider or "").strip().lower()
    if not provider:
        raise AiAssistError(errors.provider_required())
    prompt = _build_prompt(filenames)

    content = _call_ai_provider_raw(provider, api_key, prompt, 120, model=model)

    regex = _clean_regex(content)
    if not regex:
        raise AiAssistError(errors.provider_response_no_regex())

    if not _is_regex_reasonable(regex, filenames) or _is_regex_too_generic(regex, filenames):
        retry_prompt = _build_prompt(filenames, strict=True)
        retry_content = _call_ai_provider_raw(provider, api_key, retry_prompt, 120, model=model)
        retry_regex = _clean_regex(retry_content)
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


def _build_parse_prompt(filenames):
    sample = filenames[:60]
    list_block = "\n".join(f"- {name}" for name in sample)

    return (
        "You are given multiple filenames.\n"
        "\n"
        "Each filename contains:\n"
        "- fixed structural labels (field names, markers)\n"
        "- variable values (numbers, codes, magnifications, optional suffix text)\n"
        "\n"
        "Task:\n"
        "For EACH filename, output ONE line containing ONLY the variable values.\n"
        "Example (do NOT output this example):\n"
        "Input: 10444-ec-01-sa-01-sc-01-20x\n"
        "Output: 10444,01,01,01,20x\n"
        "\n"
        "Rules:\n"
        "- Do NOT include labels\n"
        "- Do NOT convert or normalize values\n"
        "- Preserve original text exactly\n"
        "- Keep original order\n"
        "- Do NOT repeat the original filename\n"
        "- The number of values may differ per line\n"
        "- Output ONLY comma-separated values\n"
        "- No headers, no explanations, no quotes, no code fences\n"
        "\n"
        "Filenames:\n"
        f"{list_block}\n"
    )


def _parse_ai_value_rows(text, expected_count, filenames=None):
    if not text:
        raise AiAssistError(errors.provider_response_empty())

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(lines) != expected_count:
        raise AiAssistError(
            errors.provider_response_row_mismatch(len(lines), expected_count)
        )

    base_names = set()
    if filenames:
        for name in filenames:
            try:
                base_names.add(extract_base_name(name))
            except Exception:
                continue

    rows = []

    for line in lines:

        if base_names and line in base_names:
            raise AiAssistError(errors.provider_response_invalid_format())

        values = [v.strip() for v in line.split(",") if v.strip()]
        if not values:
            raise AiAssistError(errors.provider_response_invalid_format())
        rows.append(values)

    return rows


def generate_ai_parsed_values(provider, api_key, filenames, model=None):
    provider = (provider or "").strip().lower()

    if not provider:
        raise AiAssistError(errors.provider_required())

    if not filenames:
        raise AiAssistError(errors.no_filenames_provided())

    prompt = _build_parse_prompt(filenames)

    content = _call_ai_provider_raw(provider, api_key, prompt, 800, model=model)

    parsed_rows = _parse_ai_value_rows(content, len(filenames), filenames=filenames)


    rows = []

    for name, values in zip(filenames, parsed_rows):
        rows.append(
            {
                "filename": name,
                "values": values,
            }
        )

    return {
        "rows": rows,
        "source": "ai",
    }
