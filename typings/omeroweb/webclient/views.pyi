from typing import Any

class BaseContainer:
    image: Any
    well: Any

    # Create the typed stub object. Inputs: *args, **kwargs. Output: None.
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    # Return a dynamic attribute. Inputs: name. Output: Any.
    def __getattr__(self, name: str) -> Any: ...

class BaseShare:
    # Create the typed stub object. Inputs: *args, **kwargs. Output: None.
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    # Return a dynamic attribute. Inputs: name. Output: Any.
    def __getattr__(self, name: str) -> Any: ...

# Return Int Or Default. Inputs: *args, **kwargs. Output: Any.
def getIntOrDefault(*args: Any, **kwargs: Any) -> Any: ...

# Load metadata preview. Inputs: *args, **kwargs. Output: Any.
def load_metadata_preview(*args: Any, **kwargs: Any) -> Any: ...

# Render response. Inputs: *args, **kwargs. Output: Any.
def render_response(*args: Any, **kwargs: Any) -> Any: ...

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
