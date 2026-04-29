from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

_T = TypeVar("_T")


def next_or_fail(iterator: Iterator[_T], label: str = "test iterator") -> _T:
    """Handle next or fail."""
    try:
        return next(iterator)
    except StopIteration as exc:
        raise AssertionError(f"{label} was exhausted") from exc
