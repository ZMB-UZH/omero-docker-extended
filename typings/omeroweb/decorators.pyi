from collections.abc import Callable
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

def login_required(*args: object, **kwargs: object) -> Callable[[_F], _F]: ...
