"""Shared string helpers for message payloads."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Mapping


def snake_to_camel(name: str) -> str:
    """Convert snake_case to lowerCamelCase.

    Inputs: `name`. Output: `str`.
    """
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def build_message_payload(
    names: Iterable[str],
    message_lookup: Mapping[str, Callable[[], str]],
) -> Dict[str, str]:
    """A payload for a list of message names from the provided lookup.

    Inputs: `names`, `message_lookup`. Output: `Dict[str, str]`.
    """
    payload: Dict[str, str] = {}
    for name in names:
        key = (
            "confirmIrreversible"
            if name == "confirm_irreversible_action"
            else snake_to_camel(name)
        )
        payload[key] = message_lookup[name]()
    return payload
