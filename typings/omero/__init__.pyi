from typing import Any

class ClientError(Exception): ...
class SecurityViolation(Exception): ...

class client:
    # Initialize the instance. Inputs: *args, **kwargs. Output: None.
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    # Return a dynamic attribute. Inputs: name. Output: Any.
    def __getattr__(self, name: str) -> Any: ...

scripts: Any
sys: Any
rtypes: Any

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
