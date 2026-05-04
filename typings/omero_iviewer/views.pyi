from typing import Any

imageMarshal: Any

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
