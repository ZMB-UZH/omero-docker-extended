from __future__ import annotations

import re


_CLAUSE_PATTERN = re.compile(r'"([^"]+)"|([^\W_]+)', re.UNICODE)
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def _phrase_tokens(raw_text: str) -> list[str]:
    """Handle phrase tokens."""
    tokens: list[str] = []
    for token in _TOKEN_PATTERN.findall(str(raw_text or "")):
        if len(token) == 1:
            continue
        tokens.append(token)
    return tokens


def _parsed_clauses(raw_text: str) -> list[tuple[str, list[str]]]:
    """Handle parsed clauses."""
    clauses: list[tuple[str, list[str]]] = []
    for match in _CLAUSE_PATTERN.finditer(str(raw_text or "")):
        phrase_text, term_text = match.groups()
        tokens = _phrase_tokens(phrase_text if phrase_text is not None else term_text)
        if not tokens:
            continue
        clause_type = "phrase" if phrase_text is not None else "term"
        clauses.append((clause_type, tokens))
    return clauses


def build_omero_fulltext_query(raw_text: str) -> str:
    """Build build OMERO fulltext query."""
    clauses = _parsed_clauses(raw_text)
    if not clauses:
        return ""

    query_parts: list[str] = []
    for clause_type, tokens in clauses:
        if clause_type == "phrase":
            query_parts.append(f'"{" ".join(tokens)}"')
            continue
        query_parts.extend(f"{token}*" for token in tokens)
    return " OR ".join(query_parts)


def build_postgres_prefix_tsquery(raw_text: str) -> str:
    """Build build postgres prefix tsquery."""
    clauses = _parsed_clauses(raw_text)
    if not clauses:
        return ""

    query_parts: list[str] = []
    for clause_type, tokens in clauses:
        prefixed_tokens = [f"{token}:*" for token in tokens]
        if clause_type == "phrase":
            query_parts.append(" <-> ".join(prefixed_tokens))
            continue
        query_parts.extend(prefixed_tokens)
    return " | ".join(query_parts)
