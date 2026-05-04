from typing import Any

class ImarisLib:
    # Return a dynamic attribute. Inputs: name. Output: Any.
    def __getattr__(self, name: str) -> Any: ...

# Return Application. Inputs: *args, **kwargs. Output: Any.
def GetApplication(*args: Any, **kwargs: Any) -> Any: ...
