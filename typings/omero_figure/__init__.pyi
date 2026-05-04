from typing import Any

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
