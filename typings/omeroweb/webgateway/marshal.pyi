from typing import Any

imageMarshal: Any

# Return channel Marshal. Inputs: *args, **kwargs. Output: Any.
def channelMarshal(*args: Any, **kwargs: Any) -> Any: ...

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
