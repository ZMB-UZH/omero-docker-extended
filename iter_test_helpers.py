from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

_T = TypeVar("_T")


def next_or_fail(iterator: Iterator[_T], label: str = "test iterator") -> _T:
    """Next or fail.

    Inputs: `iterator`, `label`. Output: `_T`. Raises on invalid or unavailable state.
    """
    try:
        return next(iterator)
    except StopIteration as exc:
        raise AssertionError(f"{label} was exhausted") from exc
