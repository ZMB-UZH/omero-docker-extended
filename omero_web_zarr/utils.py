from django.http import Http404
import zarr


def marshal_pixel_sizes(image):
    pixel_sizes = {}
    pix_size_x = image.getPixelSizeX(units=True)
    pix_size_y = image.getPixelSizeY(units=True)
    pix_size_z = image.getPixelSizeZ(units=True)
    if pix_size_x is not None:
        pixel_sizes["x"] = {
            "unit": str(pix_size_x.getUnit()).lower(),
            "value": pix_size_x.getValue(),
        }
    if pix_size_y is not None:
        pixel_sizes["y"] = {
            "unit": str(pix_size_y.getUnit()).lower(),
            "value": pix_size_y.getValue(),
        }
    if pix_size_z is not None:
        pixel_sizes["z"] = {
            "unit": str(pix_size_z.getUnit()).lower(),
            "value": pix_size_z.getValue(),
        }
    return pixel_sizes


def marshal_axes_v3(image):
    dims = ["t", "c", "z", "y", "x"]
    axes = []
    for dim in dims:
        if getattr(image, "getSize" + dim.upper())() > 1:
            axes.append(dim)
    return axes


def marshal_axes(image, version):
    if version not in ("0.3", "0.4"):
        raise Http404("version not supported")

    if version == "0.3":
        return marshal_axes_v3(image)

    size_c = image.getSizeC()
    size_z = image.getSizeZ()
    size_t = image.getSizeT()
    pixel_sizes = marshal_pixel_sizes(image)

    axes = []
    if size_t > 1:
        axes.append({"name": "t", "type": "time"})
    if size_c > 1:
        axes.append({"name": "c", "type": "channel"})
    if size_z > 1:
        axes.append({"name": "z", "type": "space"})
        if pixel_sizes and "z" in pixel_sizes:
            axes[-1]["unit"] = pixel_sizes["z"]["unit"]
    for dim in ("y", "x"):
        axes.append({"name": dim, "type": "space"})
        if pixel_sizes and dim in pixel_sizes:
            axes[-1]["unit"] = pixel_sizes[dim]["unit"]

    return axes


def generate_coordinate_transformations(shapes):
    data_shape = shapes[0]
    transformations = []
    for shape in shapes:
        assert len(shape) == len(data_shape)
        scale = [full / level for full, level in zip(data_shape, shape)]
        transformations.append([{"type": "scale", "scale": scale}])

    return transformations


def open_compat_array(path, *, mode, shape, chunks, dtype):
    """Create a v2-compatible array layout under both Zarr 2 and 3 runtimes."""
    kwargs = {
        "mode": mode,
        "shape": shape,
        "chunks": chunks,
        "dtype": dtype,
    }
    try:
        return zarr.open_array(path, zarr_format=2, **kwargs)
    except TypeError as exc:
        if "zarr_format" not in str(exc):
            raise
        return zarr.open_array(path, **kwargs)
