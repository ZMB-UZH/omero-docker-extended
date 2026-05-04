from typing import Any

class ImageWrapper:
    # Return Channels. Inputs: *args, **kwargs. Output: Any.
    def getChannels(self, *args: Any, **kwargs: Any) -> Any: ...

# Return a dynamic attribute. Inputs: name. Output: Any.
def __getattr__(name: str) -> Any: ...
