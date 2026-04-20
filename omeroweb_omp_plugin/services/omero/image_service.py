"""
OMERO image collection and retrieval services.
"""

import logging
from typing import Any

from omero_plugin_common.logging_utils import sanitize_log_value

from ...utils.omero_helpers import get_id, get_text, is_owned_by_user

logger = logging.getLogger(__name__)


def fetch_images_by_ids(conn, image_ids):
    """Fetch multiple images by their IDs."""
    if not image_ids:
        return {}

    images = []
    try:
        images = list(conn.getObjects("Image", ids=image_ids))
    except TypeError:
        try:
            images = list(conn.getObjects("Image", obj_ids=image_ids))
        except Exception:
            images = []
    except Exception:
        images = []

    if not images:
        for iid in image_ids:
            try:
                img = conn.getObject("Image", iid)
            except Exception:
                img = None
            if img is not None:
                images.append(img)

    image_map = {}
    for img in images:
        iid = get_id(img)
        if iid is None:
            continue
        try:
            image_map[int(iid)] = img
        except Exception:
            image_map[iid] = img

    return image_map


def collect_images_by_dataset_sorted(conn, project_id, limit=None, owner_id=None):
    """
    Returns:
        [(dataset_obj, [image_obj_sorted_by_ID]), ...]
    Dataset ordering is preserved as OMERO returns it.
    Image ordering is strictly numeric ascending by image ID.
    """
    out: list[tuple[Any, list[Any]]] = []
    total = 0
    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return out

        for ds in prj.listChildren():  # dataset order preserved
            if not is_owned_by_user(ds, owner_id):
                continue
            imgs = list(ds.listChildren())
            # sort by numeric ID
            imgs_sorted = sorted(
                imgs, key=lambda img: int(get_id(img)) if get_id(img) else 999999999
            )

            total += len(imgs_sorted)
            if limit and total > limit:
                # truncate to satisfy limit
                remaining = limit - (total - len(imgs_sorted))
                imgs_sorted = imgs_sorted[:remaining]
                if imgs_sorted:
                    out.append((ds, imgs_sorted))
                return out

            out.append((ds, imgs_sorted))

    except Exception as e:
        logger.exception("Error collecting dataset-sorted images: %s", e)

    return out


def collect_images_by_selected_datasets(
    conn, project_id, dataset_ids, limit=None, owner_id=None
):
    """
    Returns:
        [(dataset_obj, [image_obj_sorted_by_ID]), ...]
    Only includes datasets from dataset_ids, preserving project dataset order.
    """
    out: list[tuple[Any, list[Any]]] = []
    total = 0
    if not dataset_ids:
        return out

    wanted = set()
    for ds_id in dataset_ids:
        try:
            wanted.add(int(ds_id))
        except Exception:
            logger.debug(
                "Ignoring non-numeric dataset selection %s",
                sanitize_log_value(ds_id),
            )

    if not wanted:
        return out

    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return out

        for ds in prj.listChildren():
            if not is_owned_by_user(ds, owner_id):
                continue
            ds_id = get_id(ds)
            if ds_id is None:
                continue
            try:
                ds_id_int = int(ds_id)
            except Exception:
                logger.debug("Failed to convert dataset ID to int: %s", ds_id)
                continue
            if ds_id_int not in wanted:
                continue

            imgs = list(ds.listChildren())
            imgs_sorted = sorted(
                imgs, key=lambda img: int(get_id(img)) if get_id(img) else 999999999
            )

            total += len(imgs_sorted)
            if limit and total > limit:
                remaining = limit - (total - len(imgs_sorted))
                imgs_sorted = imgs_sorted[:remaining]
                if imgs_sorted:
                    out.append((ds, imgs_sorted))
                return out

            out.append((ds, imgs_sorted))

    except Exception as e:
        logger.exception("Error collecting selected datasets: %s", e)

    return out


def collect_dataset_summaries(conn, project_id, owner_id=None):
    """
    Returns list of dataset summaries for a project.
    Each summary includes the Bio-Formats reader name.
    """
    summaries: list[dict[str, Any]] = []

    def _get_bioformat_from_image(img):
        """
        Get the Bio-Formats reader/format name for an image.
        Returns names like: "OME-TIFF", "Zeiss CZI", "Leica LIF", "PNG", etc.
        """
        # METHOD 1: Get format from original file Format object
        if hasattr(img, "getFileset"):
            try:
                fileset = img.getFileset()
                if fileset:
                    try:
                        # Use copyUsedFiles() instead of getUsedFiles()
                        used_files = fileset.copyUsedFiles()
                        if used_files:
                            for uf in used_files:
                                try:
                                    orig_file = uf.getOriginalFile()
                                    if orig_file:
                                        fmt = orig_file.getFormat()
                                        if fmt:
                                            fmt_val = (
                                                fmt.getValue()
                                                if hasattr(fmt, "getValue")
                                                else get_text(fmt)
                                            )
                                            if fmt_val and fmt_val not in [
                                                "text/plain",
                                                "Directory",
                                                "Companion/Unknown",
                                            ]:
                                                fmt_val = fmt_val.strip()
                                                if "/" in fmt_val:
                                                    fmt_val = fmt_val.split("/")[-1]
                                                fmt_val = fmt_val.upper()
                                                format_map = {
                                                    "OME-TIFF": "OME-TIFF",
                                                    "OME-TIFFS": "OME-TIFF",
                                                    "OMETIFF": "OME-TIFF",
                                                    "TIFF": "TIFF",
                                                    "TIF": "TIFF",
                                                    "CZI": "Zeiss CZI",
                                                    "LIF": "Leica LIF",
                                                    "VSI": "CellSens VSI",
                                                    "ND2": "Nikon ND2",
                                                    "OIB": "Olympus OIB",
                                                    "OIF": "Olympus OIF",
                                                    "LSM": "Zeiss LSM",
                                                    "ZVI": "Zeiss ZVI",
                                                    "DV": "DeltaVision",
                                                    "ICS": "ICS",
                                                    "IMS": "Imaris",
                                                    "PNG": "PNG",
                                                    "JPG": "JPEG",
                                                    "JPEG": "JPEG",
                                                    "BMP": "BMP",
                                                    "GIF": "GIF",
                                                }
                                                return format_map.get(fmt_val, fmt_val)
                                except Exception:
                                    logger.debug(
                                        "Failed to detect image format via pixel metadata"
                                    )
                                    continue
                    except Exception as exc:
                        logger.debug(
                            "Suppressed non-fatal exception in image_service.py",
                            exc_info=exc,
                        )
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in image_service.py", exc_info=exc
                )

        # METHOD 2: Extract from original filename extension
        if hasattr(img, "getFileset"):
            try:
                fileset = img.getFileset()
                if fileset:
                    used_files = fileset.copyUsedFiles()
                    if used_files:
                        for uf in used_files:
                            try:
                                orig_file = uf.getOriginalFile()
                                if orig_file:
                                    orig_name = orig_file.getName()
                                    if orig_name:
                                        name_str = (
                                            orig_name.getValue()
                                            if hasattr(orig_name, "getValue")
                                            else str(orig_name)
                                        )
                                        if name_str and "." in name_str:
                                            # Handle compound extensions like .ome.tiff
                                            parts = name_str.lower().split(".")
                                            if len(parts) >= 3 and parts[-2] == "ome":
                                                return "OME-TIFF"
                                            # Single extension
                                            ext = parts[-1].upper()
                                            # Map to common Bio-Formats names
                                            format_map = {
                                                "TIF": "TIFF",
                                                "TIFF": "TIFF",
                                                "CZI": "Zeiss CZI",
                                                "LIF": "Leica LIF",
                                                "VSI": "CellSens VSI",
                                                "ND2": "Nikon ND2",
                                                "OIB": "Olympus OIB",
                                                "OIF": "Olympus OIF",
                                                "LSM": "Zeiss LSM",
                                                "ZVI": "Zeiss ZVI",
                                                "DV": "DeltaVision",
                                                "ICS": "ICS",
                                                "IMS": "Imaris",
                                                "PNG": "PNG",
                                                "JPG": "JPEG",
                                                "JPEG": "JPEG",
                                                "BMP": "BMP",
                                                "GIF": "GIF",
                                            }
                                            return format_map.get(ext, ext)
                            except Exception:
                                logger.debug(
                                    "Failed to detect image format via file extension"
                                )
                                continue
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in image_service.py", exc_info=exc
                )

        # METHOD 3: Fallback to image name extension
        if hasattr(img, "getName"):
            try:
                img_name = img.getName()
                name_str = (
                    img_name.getValue()
                    if hasattr(img_name, "getValue")
                    else get_text(img_name)
                )
                if name_str and "." in name_str:
                    parts = name_str.lower().split(".")
                    if len(parts) >= 3 and parts[-2] == "ome":
                        return "OME-TIFF"
                    ext = parts[-1].upper()
                    if ext and len(ext) <= 10:
                        return ext
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in image_service.py", exc_info=exc
                )

        return "Unknown"

    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return summaries

        for ds in prj.listChildren():
            if not is_owned_by_user(ds, owner_id):
                continue
            ds_id = get_id(ds)
            ds_name = get_text(ds.getName())
            try:
                images = list(ds.listChildren())
                image_count = len(images)
            except Exception:
                images = []
                image_count = 0

            format_names = set()
            for img in images:
                try:
                    fmt_name = _get_bioformat_from_image(img)
                    if fmt_name and fmt_name != "Unknown":
                        format_names.add(fmt_name)
                except Exception as e:
                    logger.debug(
                        "Error getting format for image %s: %s",
                        sanitize_log_value(get_id(img)),
                        sanitize_log_value(e),
                    )
                    continue

            # If no formats detected, mark as Unknown
            if not format_names:
                format_names.add("Unknown")

            format_list = ", ".join(sorted(format_names, key=lambda name: name.lower()))

            summaries.append(
                {
                    "id": str(ds_id),
                    "name": ds_name,
                    "image_count": image_count,
                    "formats": format_list,
                }
            )
    except Exception as e:
        logger.exception("Error collecting dataset summaries: %s", e)

    return summaries


def collect_images_in_project(conn, project_id, limit=None):
    """Legacy collector that returns flat list of images."""
    images: list[Any] = []
    try:
        project = conn.getObject("Project", int(project_id))
        if project is None:
            logger.warning("Project %s not found", sanitize_log_value(project_id))
            return images

        for ds in project.listChildren():
            for img in ds.listChildren():
                images.append(img)
                if limit and len(images) >= limit:
                    return images
    except Exception as e:
        logger.exception("Error collecting images: %s", e)

    return images
