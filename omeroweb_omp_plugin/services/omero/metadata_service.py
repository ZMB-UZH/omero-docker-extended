"""
OMERO metadata extraction services.
"""
import logging
from omero.model import FileAnnotationI, OriginalFileI, ImageAnnotationLinkI
from omero.rtypes import rstring, rlong

logger = logging.getLogger(__name__)


def extract_acquisition_metadata(img):
    """
    Extract acquisition metadata from an OMERO image.
    
    Returns dict of metadata key-value pairs suitable for MapAnnotation.
    Long values are stored separately as FileAnnotation.
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
            logger.error("ACQ: error reading acquisition date for image %s: %s", img.getId(), e)
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
            except Exception:
                pass

            try:
                collar = os.getCorrectionCollar()
                if collar:
                    try:
                        meta["objective_collar"] = str(collar.getValue())
                    except AttributeError:
                        meta["objective_collar"] = str(collar)
            except Exception:
                pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading objective settings for image %s: %s", img.getId(), e)
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
            except Exception:
                pass

            try:
                ew = ch.getEmissionWave()
                if ew:
                    try:
                        meta[f"channel_{idx}_emission"] = str(ew.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_emission"] = str(ew)
            except Exception:
                pass

            try:
                exw = ch.getExcitationWave()
                if exw:
                    try:
                        meta[f"channel_{idx}_excitation"] = str(exw.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_excitation"] = str(exw)
            except Exception:
                pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading channel metadata for image %s: %s", img.getId(), e)
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
                except Exception:
                    pass

                try:
                    gain = ds.getGain()
                    if gain:
                        try:
                            meta[f"detector_{did}_gain"] = str(gain.getValue())
                        except AttributeError:
                            meta[f"detector_{did}_gain"] = str(gain)
                except Exception:
                    pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading detector settings for image %s: %s", img.getId(), e)
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

            for kv in (global_md + series_md):
                try:
                    # kv is usually (key, value, ...)
                    if len(kv) > 1:
                        k = kv[0]
                        v = kv[1]
                        if k and v:
                            meta[f"BF_{str(k)}"] = str(v)
                except Exception:
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
            cleaned[k] = f"[LONG_VALUE_STORED_IN_FILEANNOTATION key={k}]"
        else:
            cleaned[k] = v

    # ----------------------------------------------------
    # 4. If long values exist → create FileAnnotation
    # ----------------------------------------------------
    if long_values:
        text = "\n".join(f"{k} = {v}" for k, v in long_values.items())
        binary = text.encode("utf-8")

        update = img._conn.getUpdateService()

        of = OriginalFileI()
        of.setName(rstring("acquisition_metadata.txt"))
        of.setPath(rstring(f"img_{img.getId()}/"))
        of.setSize(rlong(len(binary)))
        of.setMimetype(rstring("text/plain"))

        of = update.saveAndReturnObject(of)

        store = img._conn.c.sf.createRawFileStore()
        try:
            store.setFileId(of.getId().getValue())
            store.write(binary, 0, len(binary))
            store.save()
        finally:
            try:
                store.close()
            except Exception:
                pass

        fa = FileAnnotationI()
        fa.setNs(rstring("acquisition.fullmetadata"))
        fa.setFile(of)

        link = ImageAnnotationLinkI()
        link.setParent(img._obj)
        link.setChild(fa)

        update.saveAndReturnObject(link)

        cleaned["full_metadata_file"] = f"FileAnnotation:{of.getId().getValue()}"

    # ----------------------------------------------------
    # RETURN CLEANED SEARCHABLE METADATA
    # ----------------------------------------------------
    return cleaned
