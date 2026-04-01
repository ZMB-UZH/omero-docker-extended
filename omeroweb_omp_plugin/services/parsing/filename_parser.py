"""
Filename parsing logic.
"""

import re
import logging

logger = logging.getLogger(__name__)
_UNSAFE_SEPARATOR_REGEX_RE = re.compile(r"(\(\?[:!=<]|\\[1-9]|\{\d|\*\+|\+\+)")


def _parse_separator_token(token):
    if token == r"\s":
        return "", True
    if token.startswith("\\"):
        if len(token) != 2:
            raise ValueError("Invalid separator regex.")
        return token[1], False
    if len(token) != 1 or token in "()[]{}?*+|.^$":
        raise ValueError("Invalid separator regex.")
    return token, False


def _extract_separator_tokens(pattern):
    if (
        not isinstance(pattern, str)
        or not pattern
        or len(pattern) > 128
        or _UNSAFE_SEPARATOR_REGEX_RE.search(pattern)
    ):
        raise ValueError("Invalid separator regex.")

    tokens = []
    match_whitespace = False
    length = len(pattern)
    index = 0

    while index < length:
        token_values = None
        char = pattern[index]

        if pattern.startswith("(?:", index):
            end = pattern.find(")", index + 3)
            if end == -1:
                raise ValueError("Invalid separator regex.")
            group_body = pattern[index + 3 : end]
            if not group_body:
                raise ValueError("Invalid separator regex.")
            token_values = []
            for group_token in group_body.split("|"):
                if not group_token:
                    raise ValueError("Invalid separator regex.")
                parsed_group_token, group_whitespace = _parse_separator_token(
                    group_token
                )
                if group_whitespace:
                    match_whitespace = True
                    continue
                token_values.append(parsed_group_token)
            index = end + 1
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                raise ValueError("Invalid separator regex.")
            class_body = pattern[index + 1 : end]
            if not class_body or class_body.startswith("^"):
                raise ValueError("Invalid separator regex.")
            token_values = []
            class_index = 0
            while class_index < len(class_body):
                class_char = class_body[class_index]
                if class_char == "\\":
                    if class_index + 1 >= len(class_body):
                        raise ValueError("Invalid separator regex.")
                    escaped = class_body[class_index + 1]
                    if escaped == "s":
                        match_whitespace = True
                    else:
                        token_values.append(escaped)
                    class_index += 2
                    continue
                token_values.append(class_char)
                class_index += 1
            index = end + 1
        else:
            parsed_token, token_whitespace = _parse_separator_token(char)
            token_values = [] if token_whitespace else [parsed_token]
            match_whitespace = match_whitespace or token_whitespace
            index += 1

        if index < length and pattern[index] == "+":
            index += 1

        tokens.extend(token_values)

    normalized_tokens = []
    seen = set()
    for token in tokens:
        if not token or token in seen:
            continue
        seen.add(token)
        normalized_tokens.append(token)
    if not normalized_tokens and not match_whitespace:
        raise ValueError("Invalid separator regex.")
    return tuple(normalized_tokens), match_whitespace


def _split_on_separator_tokens(value, tokens, match_whitespace):
    parts = []
    current = []
    index = 0
    sorted_tokens = sorted(tokens, key=len, reverse=True)

    while index < len(value):
        matched_length = 0
        if match_whitespace and value[index].isspace():
            matched_length = 1
        else:
            for token in sorted_tokens:
                if value.startswith(token, index):
                    matched_length = len(token)
                    break

        if matched_length:
            if current:
                parts.append("".join(current))
                current = []
            index += matched_length
            while index < len(value):
                if match_whitespace and value[index].isspace():
                    index += 1
                    continue
                next_length = 0
                for token in sorted_tokens:
                    if value.startswith(token, index):
                        next_length = len(token)
                        break
                if not next_length:
                    break
                index += next_length
            continue

        current.append(value[index])
        index += 1

    if current:
        parts.append("".join(current))
    return parts


def is_supported_separator_pattern(sep_pattern):
    try:
        _extract_separator_tokens(sep_pattern)
    except ValueError:
        return False
    return True


def parse_filename(filename, sep_pattern):
    """
    Parse filename into parts using separator pattern.

    Args:
        filename: Image filename to parse
        sep_pattern: Regular expression pattern for separator

    Returns:
        List of parsed parts
    """
    m = re.search(r"\[(.+?)\]", filename)
    if m:
        base_name = m.group(1)
    else:
        f = filename.replace("\t", " ")
        m2 = re.search(r".*\s+(.+?)\s*$", f)
        if m2:
            base_name = m2.group(1).rsplit(".", 1)[0]
        else:
            base_name = filename.rsplit(".", 1)[0]

    separator_tokens, match_whitespace = _extract_separator_tokens(sep_pattern)
    parts = [
        p
        for p in _split_on_separator_tokens(
            base_name,
            separator_tokens,
            match_whitespace,
        )
        if p
    ]
    return parts
