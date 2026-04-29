from django import template

from omero_web_zarr.utils import is_store_backed_image as _is_store_backed_image

register = template.Library()


@register.filter(name="is_store_backed_image")
def is_store_backed_image_filter(image):
    """Return whether is store backed image filter."""
    return bool(image and _is_store_backed_image(image))
