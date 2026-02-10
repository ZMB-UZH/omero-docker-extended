"""
Upload workflow orchestration - compatibility checking and import processing.
"""
import os
import json
import logging
import threading
import time
import subprocess
import shutil
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

logger = logging.getLogger(__name__)

UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"
_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()

def _classify_compatibility_output(return_code: int, stdout: str, stderr: str):
    """
    Classify OMERO import compatibility check output.

    Returns a tuple of (status, details) where status is one of:
    - "compatible": File can be imported
    - "incompatible": File format not supported
    - "error": Check failed due to an error

    CRITICAL: The -f flag ALWAYS returns exit code 0, even for incompatible files.
    Actual compatibility is determined by checking if import candidates exist in stdout.

    Stdout is checked FIRST because Java/Bio-Formats commonly writes warnings to stderr
    (log4j, reflection access, class loading) that would cause false "error" results if
    stderr were checked first.  Only treat stderr as a fatal error when stdout contains
    no usable information at all.
    """
    details = (stderr or stdout or "").strip()
    lowered = (stdout or "").strip().lower() + " " + (stderr or "").strip().lower()

    # 1. Check stdout for actual import candidates FIRST.
    #    If Bio-Formats found importable files, the file IS compatible regardless
    #    of any warnings/errors printed to stderr.
    has_candidates = _has_import_candidates_in_output(stdout or "")
    if has_candidates:
        return "compatible", "File format supported by OMERO"

    # 2. Check for explicit incompatibility messages (in stdout OR stderr).
    incompatible_markers = [
        "unsupported",
        "unknown format",
        "no suitable reader",
        "cannot read",
        "not a supported",
        "cannot determine reader",
        "no reader found",
        "failed to determine reader",
    ]

    if any(marker in lowered for marker in incompatible_markers):
        return "incompatible", details

    # 3. No candidates found and no clear incompatibility message.
    #    Check stderr for fatal errors (missing file, CLI crash, etc.).
    if stderr and stderr.strip():
        stderr_lower = stderr.lower()
        fatal_indicators = [
            "no such file",
            "permission denied",
            "timeout",
        ]
        if any(indicator in stderr_lower for indicator in fatal_indicators):
            return "error", stderr.strip()

    # 4. Fallback: no candidates, no clear signal → incompatible.
    return "incompatible", details or "No importable files detected by Bio-Formats"






def _has_import_candidates_in_output(output: str) -> bool:
    """
    Check if omero import -f output contains actual import candidates.
    
    The -f flag displays files grouped by import groups, separated by "#" comments.
    Real import candidates are non-empty, non-comment lines.
    
    Returns True if at least one import candidate is found.
    """
    if not output or not output.strip():
        return False
    
    lines = output.strip().split('\n')
    
    # Metadata patterns to skip (these are NOT import candidates)
    skip_patterns = [
        "# group:",
        "to import",
        "file(s)",
        "group(s)",
        "call(s)",
        "parsed into",
        "setid",
        "reader:",
        "dry run",
        "would import",
    ]
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        
        # Skip metadata lines
        stripped_lower = stripped.lower()
        if any(pattern in stripped_lower for pattern in skip_patterns):
            continue
        
        # If we reach here, this is likely an actual file path (import candidate)
        # Additional validation: check if it looks like a file path
        if '/' in stripped or '\\' in stripped or '.' in stripped:
            return True
    
    return False




def _extract_import_candidates(output: str):
    """
    Extract import candidates from OMERO import -f output.
    
    Returns a list of file paths that would be imported.
    This is used for additional validation after compatibility check.
    """
    if not output or not output.strip():
        return []
    
    candidates = []
    lines = output.strip().split('\n')
    
    skip_patterns = [
        "# group:",
        "to import",
        "file(s)",
        "group(s)",
        "call(s)",
        "parsed into",
        "setid",
        "reader:",
        "dry run",
        "would import",
    ]
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue
        
        # Skip metadata lines
        stripped_lower = stripped.lower()
        if any(pattern in stripped_lower for pattern in skip_patterns):
            continue
        
        # This looks like an actual file path
        if '/' in stripped or '\\' in stripped or '.' in stripped:
            candidates.append(stripped)
    
    return candidates




def _check_import_compatibility(
    session_key: str,
    host: str,
    port: int,
    file_path: Path,
    dataset_id: Optional[int],
    relative_path: str,
):
    """
    Check if a file can be imported into OMERO by analyzing it with Bio-Formats.
    
    CRITICAL FIXES:
    1. The -f flag ALWAYS returns exit code 0, regardless of compatibility
    2. Compatibility is determined by parsing stdout for import candidates
    3. Proper distinction between errors and incompatibility
    
    Uses 'omero import -f' which performs local file format analysis
    without requiring server connection or authentication.
    """
    if not file_path.exists():
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": f"Missing staged file: {file_path.name}",
            "details": f"Missing staged file: {file_path.name}",
        }
    
    # Use -f flag for local Bio-Formats analysis (no server connection needed)
    cmd = [OMERO_CLI, "import", "-f", str(file_path)]
    
    # Use a temporary OMERODIR for isolation
    env = os.environ.copy()
    env["OMERODIR"] = f"/tmp/omero-compat-check-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,  # Increased timeout for large files
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": "Compatibility check timeout",
            "details": "Compatibility check timeout after 45 seconds",
        }
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"OMERO CLI not found: {exc}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"Unexpected error during compatibility check: {exc}",
        }
    
    # CRITICAL FIX: Classify based on stdout content, NOT return code
    status, details = _classify_compatibility_output(result.returncode, result.stdout, result.stderr)
    
    # Additional logging for debugging
    logger.debug(
        "Compatibility check for %s: status=%s, returncode=%d, stdout_lines=%d, stderr_lines=%d",
        relative_path,
        status,
        result.returncode,
        len((result.stdout or "").splitlines()),
        len((result.stderr or "").splitlines()),
    )
    
    return {
        "status": status,
        "relative_path": relative_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "details": details or "Compatibility check completed.",
    }



def _run_compatibility_check(job_id: str):
    job = _load_job(job_id)
    if not job:
        return

    session_key = job.get("session_key")
    host = job.get("host")
    port = job.get("port")
    upload_root = _get_upload_root() / job_id
    pending_entries = [
        (index, entry)
        for index, entry in enumerate(job.get("files", []))
        if (
            entry.get("status") == "uploaded"
            and not entry.get("compatibility")
            and not entry.get("compatibility_skip")
        )
    ]
    if not pending_entries:
        def mark_idle(job_dict):
            job_dict["compatibility_thread_active"] = False
            has_uploaded = any(entry.get("status") == "uploaded" for entry in job_dict.get("files", []))
            if has_uploaded:
                has_errors = any(
                    entry.get("compatibility") == "error" for entry in job_dict.get("files", [])
                )
                if job_dict.get("incompatible_files"):
                    job_dict["compatibility_status"] = "incompatible"
                elif has_errors:
                    job_dict["compatibility_status"] = "error"
                else:
                    job_dict["compatibility_status"] = "compatible"
            else:
                if job_dict.get("compatibility_status") not in ("incompatible", "error", "compatible"):
                    job_dict["compatibility_status"] = "pending"
            _refresh_job_status(job_dict)
            job_dict["updated"] = time.time()
            return job_dict

        _update_job(job_id, mark_idle)
        return

    pending_entries.sort(key=lambda item: item[0])
    batch_size = _resolve_job_batch_size(job)
    entries_to_check = pending_entries[:batch_size]

    max_workers = min(4, len(entries_to_check), os.cpu_count() or 2)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for entry_index, entry in entries_to_check:
            staged_path = entry.get("staged_path") or entry.get("relative_path")
            if not staged_path:
                continue
            file_path = upload_root / staged_path
            dataset_name = _dataset_name_for_path(entry.get("relative_path"), job.get("orphan_dataset_name"))
            dataset_id = (job.get("dataset_map") or {}).get(dataset_name)
            future = executor.submit(
                _check_import_compatibility,
                session_key,
                host,
                port,
                file_path,
                dataset_id,
                entry.get("relative_path"),
            )
            future_map[future] = (entry_index, entry)
        for future in as_completed(future_map):
            entry_index, entry = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.warning("Compatibility check failed for %s: %s", entry.get("relative_path"), exc)
                result = {
                    "status": "error",
                    "stdout": "",
                    "stderr": str(exc),
                    "details": str(exc),
                }
            results.append(
                {
                    "index": entry_index,
                    "upload_id": entry.get("upload_id"),
                    "relative_path": entry.get("relative_path"),
                    "status": result.get("status"),
                    "details": result.get("details", ""),
                }
            )

    new_incompatible = [
        result["relative_path"]
        for result in results
        if result.get("status") == "incompatible"
           and isinstance(result.get("relative_path"), str)
    ]

    def apply_results(job_dict):
        entries = job_dict.get("files", [])
        for result in results:
            entry_index = result.get("index")
            if entry_index is None or entry_index >= len(entries):
                continue
            entry = entries[entry_index]
            status = result.get("status")
            if status == "compatible":
                entry["compatibility"] = "compatible"
            elif status == "incompatible":
                entry["compatibility"] = "incompatible"
                entry.setdefault("compatibility_errors", []).append(
                    result.get("details") or "Import check failed."
                )
            else:
                entry["compatibility"] = "error"
                entry.setdefault("compatibility_errors", []).append(
                    result.get("details") or "Compatibility check failed."
                )

        existing_incompatible = set(job_dict.get("incompatible_files", []))
        existing_incompatible.update(filter(None, new_incompatible))
        job_dict["incompatible_files"] = sorted(existing_incompatible)

        pending_after = _compatibility_pending_entries(job_dict)
        has_errors = any(
            entry.get("compatibility") == "error" for entry in job_dict.get("files", [])
        )
        if job_dict["incompatible_files"]:
            job_dict["compatibility_status"] = "incompatible"
        elif pending_after:
            job_dict["compatibility_status"] = "checking"
        elif has_errors:
            job_dict["compatibility_status"] = "error"
        else:
            job_dict["compatibility_status"] = "compatible"
        job_dict["compatibility_thread_active"] = False
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    updated_job = _update_job(job_id, apply_results)
    if updated_job:
        if _should_start_compatibility_check(updated_job):
            _start_compatibility_check_thread(job_id)
            return
        if updated_job.get("status") == "ready":
            _start_import_thread(job_id)




def _start_compatibility_check_thread(job_id: str):
    started = {"value": False}

    def mark_started(job_dict):
        if job_dict.get("compatibility_thread_active"):
            return job_dict
        job_dict["compatibility_thread_active"] = True
        if job_dict.get("compatibility_status") != "incompatible":
            job_dict["compatibility_status"] = "checking"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        started["value"] = True
        return job_dict

    job = _update_job(job_id, mark_started)
    if not job or not started["value"]:
        return
    worker = threading.Thread(target=_run_compatibility_check, args=(job_id,), daemon=True)
    worker.start()




def _import_job_entry(
    entry,
    upload_root,
    session_key,
    host,
    port,
    dataset_map,
    orphan_dataset_name,
):
    rel_path = entry.get("relative_path")
    staged_rel = entry.get("staged_path")

    # ------------------------------------------------------------------
    # CRITICAL FIX:
    # Allow callers (SEM-EDX) to FORCE the dataset via dataset_id_override.
    # If not provided, fall back to dataset_map resolution.
    # ------------------------------------------------------------------
    dataset_id = entry.get("dataset_id_override")

    if dataset_id is None:
        dataset_name = _dataset_name_for_path(
            rel_path,
            orphan_dataset_name,
        )
        dataset_id = dataset_map.get(dataset_name)

    logger.info(
        "Import entry resolved: rel_path=%s staged_rel=%s dataset_id=%s",
        rel_path,
        staged_rel,
        dataset_id,
    )

    return _import_file(
        upload_root=upload_root,
        session_key=session_key,
        host=host,
        port=port,
        staged_rel=staged_rel,
        dataset_id=dataset_id,
    )


def _process_import_job(job_id: str):
    job = _load_job(job_id)
    if not job:
        return

    try:
        username = job.get("username") or ""
        lock = _get_import_lock(username)

        with lock:
            job = _load_job(job_id)
            if not job:
                return

            if job.get("status") in ("done", "error"):
                return

            job.setdefault("errors", [])
            job.setdefault("messages", [])
            job["status"] = "importing"
            _save_job(job)

            session_key = job.get("session_key")
            host = job.get("host")
            port = job.get("port")
            if not session_key or not host or not port:
                job["status"] = "error"
                job["errors"].append(errors.missing_omero_connection_details())
                _save_job(job)
                return

            upload_root = _get_upload_root() / job_id
            if not upload_root.exists():
                job["status"] = "error"
                job["errors"].append(errors.upload_folder_missing_on_server())
                _save_job(job)
                return

            dataset_map = job.get("dataset_map") or {}
            orphan_dataset_name = job.get("orphan_dataset_name")
            batch_size = _resolve_job_batch_size(job)
            entries_to_import = []
            for index, entry in enumerate(job.get("files", [])):
                if entry.get("status") not in ("uploaded", "pending"):
                    continue
                if entry.get("import_skip"):
                    continue
                if not entry.get("relative_path"):
                    continue
                entries_to_import.append(
                    {
                        "index": index,
                        "relative_path": entry.get("relative_path"),
                        "staged_path": entry.get("staged_path"),
                    }
                )

            for start in range(0, len(entries_to_import), batch_size):
                batch = entries_to_import[start:start + batch_size]
                if not batch:
                    continue
                with ThreadPoolExecutor(max_workers=min(batch_size, len(batch))) as executor:
                    futures = [
                        executor.submit(
                            _import_job_entry,
                            entry,
                            upload_root,
                            session_key,
                            host,
                            port,
                            dataset_map,
                            orphan_dataset_name,
                        )
                        for entry in batch
                    ]
                    for future in as_completed(futures):
                        result = future.result()
                        if not result or result.get("skip"):
                            continue
                        entry_index = result.get("index")
                        if entry_index is None:
                            continue
                        entry = job.get("files", [])[entry_index]

                        if result.get("status") == "error":
                            entry["status"] = "error"
                            entry_error = result.get("entry_error")
                            if entry_error:
                                entry.setdefault("errors", []).append(entry_error)
                            if result.get("job_error"):
                                _append_job_error(job, result["job_error"])
                            if result.get("job_message"):
                                _append_job_message(job, result["job_message"])
                            _save_job(job)
                            continue

                        if result.get("status") == "imported":
                            rel_path = result.get("rel_path") or entry.get("relative_path")
                            entry["status"] = "imported"
                            job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                            if rel_path:
                                _append_job_message(job, messages.imported_file(rel_path))
                            file_path = result.get("file_path")
                            if file_path:
                                try:
                                    file_path.unlink()
                                except OSError as exc:
                                    logger.warning("Failed to remove staged file %s: %s", file_path, exc)
                            _save_job(job)

            job = _load_job(job_id) or job
            sem_edx_associations = job.get("sem_edx_associations") or {}
            sem_edx_settings = job.get("sem_edx_settings") or {}
            create_tables = sem_edx_settings.get("create_tables", True)
            create_figures_attachments = sem_edx_settings.get("create_figures_attachments", True)
            create_figures_images = sem_edx_settings.get("create_figures_images", True)

            if job.get("special_upload") == "sem_edx_spectra" and not sem_edx_associations:
                # Fallback: derive associations server-side from uploaded file list.
                derived = _build_sem_edx_associations_from_entries(job.get("files", []))
                if derived:
                    sem_edx_associations = derived
                    job["sem_edx_associations"] = derived
                    _append_job_message(
                        job,
                        f"SEM EDX: derived {sum(len(v) for v in derived.values())} TXT attachment(s) from uploaded files (no UI associations received)"
                    )
                    _save_job(job)
                else:
                    logger.info(
                        "SEM EDX mode enabled for job %s but no TXT/image associations could be derived; skipping TXT attachments",
                        job_id,
                    )
                    _append_job_message(job, "SEM EDX: no TXT/image associations found; skipping TXT attachments")
                    _save_job(job)

            if job.get("special_upload") == "sem_edx_spectra" and sem_edx_associations:
                try:
                    conn = _open_service_connection(host, port, group_id=job.get("group_id"))
                    if not conn:
                        logger.error("Failed to open SEM-EDX service connection for TXT attachments")
                        _append_job_message(job, "SEM EDX: failed to open service connection for TXT attachments")
                        _save_job(job)
                    else:
                        try:
                            entries_by_path = {
                                entry.get("relative_path"): entry for entry in job.get("files", [])
                            }
                            attachment_count = 0
                            total_attachments = sum(
                                len(txt_paths) for txt_paths in sem_edx_associations.values() 
                                if isinstance(txt_paths, list)
                            )
                            
                            logger.info("Processing %d SEM EDX text attachments for job %s", total_attachments, job_id)
                            
                            # CRITICAL FIX: Batch lookup ALL images at once instead of one-by-one
                            logger.info("Pre-loading image cache for %d images", len(sem_edx_associations))
                            all_image_names = []
                            image_to_dataset = {}  # Track which dataset each image should be in
                            
                            for image_rel in sem_edx_associations.keys():
                                image_name = PurePosixPath(image_rel).name if image_rel else ""
                                if image_name:
                                    all_image_names.append(image_name)
                                    dataset_name = _dataset_name_for_path(image_rel, orphan_dataset_name)
                                    dataset_id = dataset_map.get(dataset_name)
                                    image_to_dataset[image_name] = dataset_id
                            
                            # Do batch lookup - this is 100-1000x faster than individual lookups
                            image_cache = {}
                            datasets_to_search = set(image_to_dataset.values())
                            
                            for dataset_id in datasets_to_search:
                                if dataset_id:
                                    # Find all images for this dataset
                                    dataset_images = [name for name, did in image_to_dataset.items() if did == dataset_id]
                                    if dataset_images:
                                        batch_results = _batch_find_images_by_name(conn, dataset_images, dataset_id)
                                        image_cache.update({name: img for name, img in batch_results.items()})
                            
                            # Fallback: global search for images not found in datasets
                            missing_images = set(all_image_names) - set(image_cache.keys())
                            if missing_images:
                                logger.info("Searching globally for %d missing images", len(missing_images))
                                global_results = _batch_find_images_by_name(conn, list(missing_images), None)
                                image_cache.update(global_results)
                            
                            logger.info("Image cache loaded: %d/%d found", len(image_cache), len(all_image_names))

                            plot_cache = {}
                            plot_rel_cache = {}
                            imported_plots = set()
                            if create_figures_attachments or create_figures_images:
                                from ..omero.sem_edx_parser import create_edx_spectrum_plot
                            
                            # Now process attachments using cached images
                            for attachment_idx, (image_rel, txt_paths) in enumerate(sem_edx_associations.items()):
                                if not isinstance(txt_paths, list):
                                    continue
                                
                                # Progress logging
                                progress_pct = (attachment_idx / len(sem_edx_associations)) * 100
                                logger.info("Processing image %d/%d (%.1f%%) - %s", 
                                          attachment_idx + 1, len(sem_edx_associations), progress_pct, image_rel)

                                image_name = PurePosixPath(image_rel).name if image_rel else ""

                                # Validate job-service session periodically (every 10 attachments).
                                # IMPORTANT: NEVER reconnect using the end-user session_key here.
                                if attachment_count > 0 and attachment_count % 10 == 0:
                                    if not _validate_session(conn):
                                        logger.warning("job-service session expired, reopening service connection...")
                                        try:
                                            try:
                                                conn.close()
                                            except Exception:
                                                pass
                                            conn = _open_service_connection(host, port, group_id=job.get("group_id"))
                                        except Exception:
                                            conn = None

                                        if not conn:
                                            logger.error("Failed to reopen job-service connection, aborting SEM EDX attachments")
                                            break

                                        # Re-populate cache after reconnect
                                        logger.info("Re-loading image cache after reconnect")
                                        image_cache.clear()
                                        for dataset_id in datasets_to_search:
                                            if dataset_id:
                                                dataset_images = [name for name, did in image_to_dataset.items() if did == dataset_id]
                                                if dataset_images:
                                                    batch_results = _batch_find_images_by_name(conn, dataset_images, dataset_id)
                                                    image_cache.update(batch_results)
                                        missing_images = set(all_image_names) - set(image_cache.keys())
                                        if missing_images:
                                            global_results = _batch_find_images_by_name(conn, list(missing_images), None)
                                            image_cache.update(global_results)

                                # Get cached image (no query needed!)
                                image_obj = image_cache.get(image_name)

                                # Process each text file for this image
                                for txt_rel in txt_paths:
                                    txt_name = PurePosixPath(txt_rel).name
                                    attachment_count += 1

                                    if not image_obj:
                                        logger.warning("Image not found for %s, skipping attachment", txt_name)
                                        _append_txt_attachment_message(job, txt_name, image_name or image_rel, False)
                                        continue

                                    image_id = _get_id(image_obj)
                                    if not image_id:
                                        logger.warning(
                                            "Could not get image ID for %s, skipping %s",
                                            image_name,
                                            txt_name,
                                        )
                                        _append_txt_attachment_message(
                                            job,
                                            txt_name,
                                            image_name or image_rel,
                                            False,
                                        )
                                        continue

                                    # ------------------------------------------------------------------
                                    # CRITICAL FIX:
                                    # Determine the REAL dataset ID of the SEM image directly from OMERO.
                                    # dataset_map may not contain this dataset if the SEM image was not
                                    # imported in the current job's main import phase.
                                    # ------------------------------------------------------------------
                                    sem_dataset_id = None
                                    try:
                                        for ds in image_obj.listParents():
                                            sem_dataset_id = ds.getId()
                                            break
                                    except Exception:
                                        sem_dataset_id = None

                                    logger.info(
                                        "SEM-EDX: SEM image dataset resolved from OMERO: image=%s image_id=%s sem_dataset_id=%s",
                                        image_name,
                                        image_id,
                                        sem_dataset_id,
                                    )

                                    txt_entry = entries_by_path.get(txt_rel)
                                    if not txt_entry:
                                        logger.warning("Text entry not found for %s, skipping", txt_rel)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)
                                        continue

                                    staged_path = txt_entry.get("staged_path") or txt_rel
                                    txt_path = upload_root / staged_path

                                    if not txt_path.exists():
                                        logger.warning("Text file not found at %s, skipping", txt_path)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)
                                        continue

                                    plot_path = None
                                    plot_rel = None
                                    if create_figures_attachments or create_figures_images:
                                        if txt_rel in plot_cache:
                                            plot_path = plot_cache.get(txt_rel)
                                            plot_rel = plot_rel_cache.get(txt_rel)
                                        else:
                                            plot_path = create_edx_spectrum_plot(txt_path)
                                            plot_cache[txt_rel] = plot_path
                                            if plot_path:
                                                plot_rel = str(PurePosixPath(txt_rel).with_name(plot_path.name))
                                                plot_rel_cache[txt_rel] = plot_rel

                                    if create_figures_images and plot_path and plot_rel and txt_rel not in imported_plots:
                                        # ------------------------------------------------------------------
                                        # Import the EDX plot PNG as a SEPARATE OMERO Image
                                        # into the SAME dataset/path as the SEM image.
                                        #
                                        # CRITICAL DETAIL:
                                        # The OMERO import pipeline can ONLY import files that exist under
                                        # upload_root (staged files). The plot is generated next to the TXT
                                        # (txt_path), which may NOT match the SEM image's staged directory.
                                        #
                                        # Therefore we MUST stage the plot PNG into the SEM image's path
                                        # under upload_root BEFORE calling _import_job_entry.
                                        #
                                        # - plot_import_rel controls dataset/path mapping (same as SEM image)
                                        # - staged_path MUST point to an existing file under upload_root
                                        # - dataset_id_override FORCES dataset selection
                                        # ------------------------------------------------------------------
                                        plot_import_rel = str(
                                            PurePosixPath(image_rel).with_name(
                                                PurePosixPath(plot_rel).name
                                            )
                                        )

                                        staged_plot_path = upload_root / plot_import_rel
                                        try:
                                            staged_plot_path.parent.mkdir(parents=True, exist_ok=True)
                                            # Copy the generated plot into the SEM image's staged directory
                                            # so that the existing import pipeline can pick it up.
                                            shutil.copy2(plot_path, staged_plot_path)
                                        except Exception as exc:
                                            logger.exception(
                                                "Failed to stage SEM-EDX plot PNG for import: src=%s dst=%s error=%s",
                                                plot_path,
                                                staged_plot_path,
                                                exc,
                                            )
                                            _append_job_error(
                                                job,
                                                f"Failed to stage SEM-EDX plot PNG for import: {staged_plot_path.name}",
                                            )
                                            imported_plots.add(txt_rel)
                                            continue

                                        logger.info(
                                            "SEM-EDX: plot staged for import: rel=%s staged=%s exists=%s",
                                            plot_import_rel,
                                            staged_plot_path,
                                            staged_plot_path.exists(),
                                        )

                                        import_entry = {
                                            "relative_path": plot_import_rel,
                                            "staged_path": plot_import_rel,
                                            "dataset_id_override": sem_dataset_id,
                                        }

                                        import_result = _import_job_entry(
                                            import_entry,
                                            upload_root,
                                            session_key,
                                            host,
                                            port,
                                            dataset_map,
                                            orphan_dataset_name,
                                        )

                                        if import_result.get("status") == "error":
                                            if import_result.get("job_error"):
                                                _append_job_error(job, import_result["job_error"])
                                            if import_result.get("job_message"):
                                                _append_job_message(job, import_result["job_message"])
                                            logger.error(
                                                "Failed to import SEM-EDX plot %s (dataset_id=%s staged=%s)",
                                                plot_import_rel,
                                                sem_dataset_id,
                                                str(staged_plot_path),
                                            )
                                        elif import_result.get("status") == "imported":
                                            _append_job_message(job, messages.imported_file(plot_import_rel))
                                            logger.info(
                                                "Imported SEM-EDX plot %s into dataset_id=%s",
                                                plot_import_rel,
                                                sem_dataset_id,
                                            )

                                        imported_plots.add(txt_rel)

                                    # IMPORTANT: Attach via OMERO API using job-service connection (NO CLI, NO user session)
                                    try:
                                        logger.info("Attaching %s to %s (Image:%d)", txt_name, image_name, image_id)
                                        _attach_txt_to_image_service(
                                            conn,
                                            image_id,
                                            txt_path,
                                            username,  # Pass username for suConn
                                            create_tables,
                                            plot_path=plot_path if create_figures_attachments else None,
                                        )

                                        # Mark as imported if not already
                                        if txt_entry.get("status") != "imported":
                                            txt_entry["status"] = "imported"
                                            job["imported_bytes"] = job.get("imported_bytes", 0) + txt_entry.get("size", 0)

                                        _append_txt_attachment_message(job, txt_name, image_name, True)
                                        logger.info("Successfully attached %s to %s", txt_name, image_name)

                                    except Exception as exc:
                                        logger.error("Failed to attach %s to %s: %s", txt_rel, image_rel, exc)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)

                                    # Save job state periodically
                                    if attachment_count % 5 == 0:
                                        _save_job(job)

                            
                            # Final save
                            _save_job(job)
                            logger.info("Completed SEM EDX attachment processing for job %s: %d/%d processed", 
                                      job_id, attachment_count, total_attachments)
                            
                        finally:
                            try:
                                conn.close()
                            except Exception as exc:
                                logger.warning("Error closing connection: %s", exc)
                except Exception:
                    logger.exception("SEM EDX txt attachment failed for job %s.", job_id)

            job = _load_job(job_id) or job
            if job.get("errors"):
                job["status"] = "error"
            else:
                job["status"] = "done"
            _save_job(job)
    except Exception as exc:
        logger.exception("Import job %s failed unexpectedly.", job_id)
        job = _load_job(job_id) or {"job_id": job_id}
        _append_job_error(job, errors.unexpected_import_failure(exc))
        job["status"] = "error"
        _save_job(job)




def _start_import_thread(job_id: str):
    job = _load_job(job_id)
    if not job:
        return
    if job.get("status") != "ready":
        return
    if job.get("import_thread_started"):
        return

    job["import_thread_started"] = True
    _save_job(job)
    worker = threading.Thread(target=_process_import_job, args=(job_id,), daemon=True)
    worker.start()


# --------------------------------------------------------------------------
# VIEWS
# --------------------------------------------------------------------------


def _normalize_sem_edx_associations(raw_associations, normalized_entries):
    if not isinstance(raw_associations, dict):
        return {}

    # ACCEPT BOTH relative_path AND staged_path, but CANONICALIZE to relative_path.
    available_paths = {}

    for entry in normalized_entries:
        rel = entry.get("relative_path")
        if rel:
            available_paths[rel] = entry

        staged = entry.get("staged_path")
        if staged:
            available_paths[staged] = entry

    normalized = {}

    for image_path, txt_paths in raw_associations.items():
        image_key = _safe_relative_path(image_path or "")
        if not image_key:
            continue
        if image_key.lower().endswith(".txt"):
            continue
        if image_key not in available_paths:
            continue
        if not isinstance(txt_paths, list):
            continue

        image_entry = available_paths.get(image_key) or {}
        image_rel = image_entry.get("relative_path") or image_key

        cleaned_txt = []

        for txt_path in txt_paths:
            txt_key = _safe_relative_path(txt_path or "")
            if not txt_key:
                continue
            if not txt_key.lower().endswith(".txt"):
                continue
            if txt_key not in available_paths:
                continue

            txt_entry = available_paths.get(txt_key) or {}
            txt_rel = txt_entry.get("relative_path") or txt_key

            if txt_rel not in cleaned_txt:
                cleaned_txt.append(txt_rel)

        if cleaned_txt:
            normalized[image_rel] = cleaned_txt

    return normalized


def _build_sem_edx_associations_from_entries(entries):
    """Server-side fallback to derive SEM-EDX TXT->image associations.

    The UI normally submits sem_edx_associations, but if that payload is missing/empty
    (e.g. browser/localStorage issues, UI state bugs), we can deterministically derive
    associations from the uploaded file list:

    - Group by directory (based on relative_path)
    - Choose ONE non-.txt file per directory as the target image (lexicographically)
    - Attach ALL .txt files in that directory to that image

    This keeps behaviour predictable and ensures TXT attachment is at least attempted.
    """

    if not isinstance(entries, list) or not entries:
        return {}

    grouped = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("relative_path")
        if not rel or not isinstance(rel, str):
            continue
        rel_norm = _safe_relative_path(rel)
        if not rel_norm:
            continue
        parent = str(PurePosixPath(rel_norm).parent)
        if parent == ".":
            parent = ""
        bucket = grouped.setdefault(parent, {"images": [], "txt": []})
        if rel_norm.lower().endswith(".txt"):
            bucket["txt"].append(rel_norm)
        else:
            bucket["images"].append(rel_norm)

    associations = {}
    for bucket in grouped.values():
        if not bucket["images"] or not bucket["txt"]:
            continue
        image_rel = sorted(bucket["images"])[0]
        txt_rels = sorted(set(bucket["txt"]))
        if txt_rels:
            associations[image_rel] = txt_rels

    return associations
