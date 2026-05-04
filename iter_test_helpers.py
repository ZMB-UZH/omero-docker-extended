from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

_T = TypeVar("_T")


def next_or_fail(iterator: Iterator[_T], label: str = "test iterator") -> _T:
    """Return the next iterator item, failing the caller when none exists.

    Inputs: `iterator` (Iterator[_T]), `label` (str). Output: `_T`. Raises:
    AssertionError when validation or the called operation fails.
    """
    try:
        return next(iterator)
    except StopIteration as exc:
        raise AssertionError(f"{label} was exhausted") from exc
