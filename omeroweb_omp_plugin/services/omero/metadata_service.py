"""OMERO metadata extraction services."""

import logging
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info
from omero.model import FileAnnotationI, ImageAnnotationLinkI, ImageI, OriginalFileI
from omero.rtypes import rstring, rlong

from ...utils.omero_helpers import get_id

logger = logging.getLogger(__name__)


def _long_value_marker(key, *, stored):
    """Return the long value marker.

    Inputs: `key` lookup key, `stored`. Output: long value marker result.
    """
    status = "STORED_IN_FILEANNOTATION" if stored else "NOT_STORED"
    return f"[LONG_VALUE_{status} key={key}]"


def _set_long_value_markers(cleaned, long_values, *, stored):
    """Set the long value markers.

    Inputs: `cleaned`, `long_values`, `stored`. Output: None.
    """
    for key in long_values:
        cleaned[key] = _long_value_marker(key, stored=stored)


def extract_acquisition_metadata(img):
    """Extract the acquisition metadata.

    Inputs: `img`. Output: `cleaned`.
    """
    meta = {}

    # ----------------------------------------------------
    # 1. Typed metadata directly from OMERO model
    # ----------------------------------------------------

    # Acquisition date
    try:
        ad = img.getAcquisitionDate()
        if ad:
            try:
                meta["acquisition_date"] = str(ad.getValue())
            except AttributeError:
                # Sometimes gateway returns a datetime or string directly
                meta["acquisition_date"] = str(ad)
    except Exception as e:
        try:
            logger.error(
                "ACQ: error reading acquisition date for image %s: %s", img.getId(), e
            )
        except Exception:
            logger.error("ACQ: error reading acquisition date: %s", e)

    # Objective settings
    try:
        os = img.getObjectiveSettings()
        if os:
            try:
                oid = os.getID()
                if oid:
                    try:
                        meta["objective_id"] = str(oid.getValue())
                    except AttributeError:
                        meta["objective_id"] = str(oid)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in metadata_service.py",
                    exc_info=exc,
                )

            try:
                collar = os.getCorrectionCollar()
                if collar:
                    try:
                        meta["objective_collar"] = str(collar.getValue())
                    except AttributeError:
                        meta["objective_collar"] = str(collar)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in metadata_service.py",
                    exc_info=exc,
                )
    except Exception as e:
        try:
            logger.error(
                "ACQ: error reading objective settings for image %s: %s", img.getId(), e
            )
        except Exception:
            logger.error("ACQ: error reading objective settings: %s", e)

    # Channels
    try:
        for ch in img.getChannels():
            try:
                idx = ch.getIndex()
            except Exception:
                idx = "unknown"

            try:
                lbl = ch.getLabel()
                if lbl:
                    meta[f"channel_{idx}_label"] = str(lbl)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in metadata_service.py",
                    exc_info=exc,
                )

            try:
                ew = ch.getEmissionWave()
                if ew:
                    try:
                        meta[f"channel_{idx}_emission"] = str(ew.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_emission"] = str(ew)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in metadata_service.py",
                    exc_info=exc,
                )

            try:
                exw = ch.getExcitationWave()
                if exw:
                    try:
                        meta[f"channel_{idx}_excitation"] = str(exw.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_excitation"] = str(exw)
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in metadata_service.py",
                    exc_info=exc,
                )
    except Exception as e:
        try:
            logger.error(
                "ACQ: error reading channel metadata for image %s: %s", img.getId(), e
            )
        except Exception:
            logger.error("ACQ: error reading channel metadata: %s", e)

    # Detector settings
    try:
        # Not all gateway versions expose getDetectorSettings()
        ds_list = None
        try:
            ds_list = img.getDetectorSettings()
        except Exception:
            ds_list = None

        if ds_list:
            for ds in ds_list:
                try:
                    did = ds.getID().getValue() if ds.getID() else "unknown"
                except Exception:
                    did = "unknown"

                try:
                    binning = ds.getBinning()
                    if binning:
                        try:
                            meta[f"detector_{did}_binning"] = str(binning.getValue())
                        except AttributeError:
                            meta[f"detector_{did}_binning"] = str(binning)
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in metadata_service.py",
                        exc_info=exc,
                    )

                try:
                    gain = ds.getGain()
                    if gain:
                        try:
                            meta[f"detector_{did}_gain"] = str(gain.getValue())
                        except AttributeError:
                            meta[f"detector_{did}_gain"] = str(gain)
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in metadata_service.py",
                        exc_info=exc,
                    )
    except Exception as e:
        try:
            logger.error(
                "ACQ: error reading detector settings for image %s: %s", img.getId(), e
            )
        except Exception:
            logger.error("ACQ: error reading detector settings: %s", e)

    # ----------------------------------------------------
    # 2. Original Metadata imported by Bio-Formats
    #    (This contains MOST of the useful acquisition data)
    #    Use ImageWrapper.loadOriginalMetadata(), NOT MetadataService.
    # ----------------------------------------------------
    try:
        om = img.loadOriginalMetadata()
        # om is typically a tuple: (pixelsId, global_metadata, series_metadata)
        if om:
            try:
                global_md = om[1] if len(om) > 1 and om[1] else []
            except Exception:
                global_md = []
            try:
                series_md = om[2] if len(om) > 2 and om[2] else []
            except Exception:
                series_md = []

            for kv in global_md + series_md:
                try:
                    # kv is usually (key, value, ...)
                    if len(kv) > 1:
                        k = kv[0]
                        v = kv[1]
                        if k and v:
                            meta[f"BF_{str(k)}"] = str(v)
                except Exception:
                    logger.debug("Failed to parse metadata key-value pair")
                    continue
    except Exception as e:
        try:
            logger.error(
                "ACQ: error loading original metadata for image %s: %s",
                img.getId(),
                e,
            )
        except Exception:
            logger.error("ACQ: error loading original metadata: %s", e)

    # ----------------------------------------------------
    # 3. Separate long values (FileAnnotation)
    # ----------------------------------------------------
    long_values = {}
    cleaned = {}

    for k, v in meta.items():
        v = str(v)
        if len(v) > 250:
            long_values[k] = v
            cleaned[k] = _long_value_marker(k, stored=False)
        else:
            cleaned[k] = v

    # ----------------------------------------------------
    # 4. If long values exist → create FileAnnotation
    # ----------------------------------------------------
    if long_values:
        image_id = get_id(img)
        if image_id is None:
            logger.warning("Cannot store long acquisition metadata: missing image id")
            return cleaned
        try:
            image_id_int = int(image_id)
        except (TypeError, ValueError, OverflowError):
            logger.warning(
                "Cannot store long acquisition metadata: invalid image id %s",
                sanitize_log_value(image_id),
            )
            return cleaned
        image_parent = ImageI(image_id_int, False)

        text = "\n".join(f"{k} = {v}" for k, v in long_values.items())
        binary = text.encode("utf-8")

        image_conn = getattr(img, "_conn", None)
        if image_conn is None:
            logger.warning(
                "Cannot store long acquisition metadata for image %s: missing OMERO connection",
                image_id_int,
            )
            return cleaned
        try:
            update = image_conn.getUpdateService()

            of = OriginalFileI()
            of.setName(rstring("acquisition_metadata.txt"))
            of.setPath(rstring(f"img_{image_id_int}/"))
            of.setSize(rlong(len(binary)))
            of.setMimetype(rstring("text/plain"))

            of = update.saveAndReturnObject(of)

            store = image_conn.c.sf.createRawFileStore()
            try:
                store.setFileId(of.getId().getValue())
                store.write(binary, 0, len(binary))
                store.save()
            finally:
                try:
                    store.close()
                except Exception as exc:
                    logger.debug(
                        "Suppressed non-fatal exception in metadata_service.py",
                        exc_info=sanitized_exc_info(exc),
                    )

            fa = FileAnnotationI()
            fa.setNs(rstring("acquisition.fullmetadata"))
            fa.setFile(of)

            link = ImageAnnotationLinkI()
            link.setParent(image_parent)
            link.setChild(fa)

            update.saveAndReturnObject(link)
        except Exception as exc:
            logger.warning(
                "Cannot store long acquisition metadata for image %s: %s",
                image_id_int,
                sanitize_log_value(exc),
                exc_info=sanitized_exc_info(exc),
            )
            return cleaned

        _set_long_value_markers(cleaned, long_values, stored=True)
        cleaned["full_metadata_file"] = f"FileAnnotation:{of.getId().getValue()}"

    # ----------------------------------------------------
    # RETURN CLEANED SEARCHABLE METADATA
    # ----------------------------------------------------
    return cleaned
