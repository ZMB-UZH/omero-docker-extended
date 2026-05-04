from collections.abc import Callable
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

# Return login required. Inputs: *args, **kwargs. Output: Callable[[_F], _F].
def login_required(*args: object, **kwargs: object) -> Callable[[_F], _F]: ...
