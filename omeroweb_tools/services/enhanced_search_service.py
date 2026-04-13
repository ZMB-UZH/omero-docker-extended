from __future__ import annotations

import logging
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import omero
from django.urls import reverse
from omero.gateway import BlitzGateway

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_bool_env, get_env
from omero_plugin_common.logging_utils import sanitize_log_value
from omero_plugin_common.omero_helpers import get_id, get_owner_id, get_text

from ..config import (
    EnhancedSearchCeleryConfig,
    EnhancedSearchRuntimeConfig,
    EnhancedSearchScope,
    build_enhanced_search_celery_config,
    build_enhanced_search_config,
)
from .acquisition_metadata import extract_search_document
from .enhanced_search_store import (
    EnhancedSearchStoreError,
    connect as db_connect,
    delete_saved_query,
    ensure_sync_state_rows,
    list_saved_queries,
    list_sync_states,
    mark_sync_complete,
    mark_sync_error,
    prune_orphan_documents,
    prune_scope_membership,
    save_saved_query,
    search_index_rows,
    try_start_scope_sync,
    update_sync_progress,
    upsert_search_document,
)


logger = logging.getLogger(__name__)

_SYNC_THREADS: dict[str, threading.Thread] = {}
_SYNC_THREADS_LOCK = threading.Lock()


@dataclass(frozen=True)
class SearchQuery:
    scope_key: str = ""
    query_text: str = ""
    instrument_model: str = ""
    instrument_manufacturer: str = ""
    objective_model: str = ""
    detector_model: str = ""
    image_name: str = ""
    dataset_name: str = ""
    project_name: str = ""
    objective_magnification_min: float | None = None
    objective_magnification_max: float | None = None
    objective_na_min: float | None = None
    objective_na_max: float | None = None
    pixel_size_x_um_min: float | None = None
    pixel_size_x_um_max: float | None = None
    pixel_size_y_um_min: float | None = None
    pixel_size_y_um_max: float | None = None
    z_step_um_min: float | None = None
    z_step_um_max: float | None = None
    detector_gain_min: float | None = None
    detector_gain_max: float | None = None
    acquisition_date_from: datetime | None = None
    acquisition_date_to: datetime | None = None
    channel_label: str = ""
    channel_excitation_nm_min: float | None = None
    channel_excitation_nm_max: float | None = None
    channel_emission_nm_min: float | None = None
    channel_emission_nm_max: float | None = None
    page: int = 1

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "scope_key": self.scope_key,
            "query_text": self.query_text,
            "instrument_model": self.instrument_model,
            "instrument_manufacturer": self.instrument_manufacturer,
            "objective_model": self.objective_model,
            "detector_model": self.detector_model,
            "image_name": self.image_name,
            "dataset_name": self.dataset_name,
            "project_name": self.project_name,
            "channel_label": self.channel_label,
            "page": self.page,
        }
        for key in (
            "objective_magnification_min",
            "objective_magnification_max",
            "objective_na_min",
            "objective_na_max",
            "pixel_size_x_um_min",
            "pixel_size_x_um_max",
            "pixel_size_y_um_min",
            "pixel_size_y_um_max",
            "z_step_um_min",
            "z_step_um_max",
            "detector_gain_min",
            "detector_gain_max",
            "channel_excitation_nm_min",
            "channel_excitation_nm_max",
            "channel_emission_nm_min",
            "channel_emission_nm_max",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.acquisition_date_from is not None:
            payload["acquisition_date_from"] = self.acquisition_date_from.date().isoformat()
        if self.acquisition_date_to is not None:
            payload["acquisition_date_to"] = self.acquisition_date_to.date().isoformat()
        return payload

    def with_page(self, page: int) -> "SearchQuery":
        return SearchQuery(**{**self.__dict__, "page": max(1, int(page))})

    def to_querystring(self, *, page: int | None = None) -> str:
        payload = self.to_payload()
        if page is not None:
            payload["page"] = max(1, int(page))
        return urlencode(
            {
                key: value
                for key, value in payload.items()
                if value not in (None, "", [])
            },
            doseq=True,
        )


def runtime_config() -> EnhancedSearchRuntimeConfig:
    return build_enhanced_search_config()


def runtime_celery_config() -> EnhancedSearchCeleryConfig:
    return build_enhanced_search_celery_config()


def configured_scopes() -> tuple[EnhancedSearchScope, ...]:
    return runtime_config().scopes


def scope_map() -> dict[str, EnhancedSearchScope]:
    return {scope.scope_key: scope for scope in configured_scopes()}


def ensure_scope_state() -> list[dict[str, Any]]:
    config = runtime_config()
    if not config.scopes:
        return []
    with db_connect() as conn:
        ensure_sync_state_rows(
            conn,
            [scope.to_dict() for scope in config.scopes],
            config.schema_version,
        )
        return list_sync_states(conn)


def _scope_state(scope: EnhancedSearchScope) -> dict[str, Any] | None:
    for state in ensure_scope_state():
        if (
            state.get("scope_type") == scope.scope_type
            and int(state.get("scope_id")) == scope.scope_id
        ):
            return state
    return None


def current_sync_states() -> list[dict[str, Any]]:
    by_key = {
        f"{state['scope_type']}:{state['scope_id']}": state
        for state in ensure_scope_state()
    }
    merged: list[dict[str, Any]] = []
    for scope in configured_scopes():
        merged.append(
            {
                "scope_type": scope.scope_type,
                "scope_id": scope.scope_id,
                "scope_key": scope.scope_key,
                "scope_label": scope.label,
                "status": "idle",
                "requested_by": "",
                "indexed_image_count": 0,
                "current_message": "",
                "last_error": "",
                "last_started_at": None,
                "last_finished_at": None,
                "last_successful_at": None,
                "updated_at": None,
                **(by_key.get(scope.scope_key) or {}),
            }
        )
    return merged


def _parse_float(raw_value: Any) -> float | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {text}") from exc


def _parse_date(raw_value: Any, *, end_of_day: bool = False) -> datetime | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(f"{text}T00:00:00")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if end_of_day and "T" not in text:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def _validate_numeric_bounds(
    *,
    field_label: str,
    minimum: float | None,
    maximum: float | None,
    errors: list[str],
) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        errors.append(f"{field_label} minimum cannot be greater than maximum.")


def parse_search_query(params) -> tuple[SearchQuery, list[str]]:
    errors: list[str] = []

    def read_text(name: str) -> str:
        return str(params.get(name) or "").strip()

    def read_float(name: str) -> float | None:
        try:
            return _parse_float(params.get(name))
        except ValueError as exc:
            errors.append(str(exc))
            return None

    page = 1
    try:
        raw_page = int(str(params.get("page") or "1").strip())
        page = max(1, raw_page)
    except (TypeError, ValueError):
        errors.append("Invalid page value.")

    try:
        acquisition_date_from = _parse_date(params.get("acquisition_date_from"))
    except ValueError:
        acquisition_date_from = None
        errors.append("Invalid acquisition start date.")
    try:
        acquisition_date_to = _parse_date(
            params.get("acquisition_date_to"),
            end_of_day=True,
        )
    except ValueError:
        acquisition_date_to = None
        errors.append("Invalid acquisition end date.")

    if (
        acquisition_date_from is not None
        and acquisition_date_to is not None
        and acquisition_date_from > acquisition_date_to
    ):
        errors.append("Acquisition start date cannot be after the end date.")

    scope_key = read_text("scope_key")
    if scope_key and scope_key not in scope_map():
        errors.append("Selected search scope is not enabled.")
        scope_key = ""

    query = SearchQuery(
        scope_key=scope_key,
        query_text=read_text("query_text"),
        instrument_model=read_text("instrument_model"),
        instrument_manufacturer=read_text("instrument_manufacturer"),
        objective_model=read_text("objective_model"),
        detector_model=read_text("detector_model"),
        image_name=read_text("image_name"),
        dataset_name=read_text("dataset_name"),
        project_name=read_text("project_name"),
        objective_magnification_min=read_float("objective_magnification_min"),
        objective_magnification_max=read_float("objective_magnification_max"),
        objective_na_min=read_float("objective_na_min"),
        objective_na_max=read_float("objective_na_max"),
        pixel_size_x_um_min=read_float("pixel_size_x_um_min"),
        pixel_size_x_um_max=read_float("pixel_size_x_um_max"),
        pixel_size_y_um_min=read_float("pixel_size_y_um_min"),
        pixel_size_y_um_max=read_float("pixel_size_y_um_max"),
        z_step_um_min=read_float("z_step_um_min"),
        z_step_um_max=read_float("z_step_um_max"),
        detector_gain_min=read_float("detector_gain_min"),
        detector_gain_max=read_float("detector_gain_max"),
        acquisition_date_from=acquisition_date_from,
        acquisition_date_to=acquisition_date_to,
        channel_label=read_text("channel_label"),
        channel_excitation_nm_min=read_float("channel_excitation_nm_min"),
        channel_excitation_nm_max=read_float("channel_excitation_nm_max"),
        channel_emission_nm_min=read_float("channel_emission_nm_min"),
        channel_emission_nm_max=read_float("channel_emission_nm_max"),
        page=page,
    )

    for label, minimum, maximum in (
        (
            "Objective magnification",
            query.objective_magnification_min,
            query.objective_magnification_max,
        ),
        ("Objective NA", query.objective_na_min, query.objective_na_max),
        ("Pixel size X", query.pixel_size_x_um_min, query.pixel_size_x_um_max),
        ("Pixel size Y", query.pixel_size_y_um_min, query.pixel_size_y_um_max),
        ("Z step", query.z_step_um_min, query.z_step_um_max),
        ("Detector gain", query.detector_gain_min, query.detector_gain_max),
        (
            "Channel excitation",
            query.channel_excitation_nm_min,
            query.channel_excitation_nm_max,
        ),
        (
            "Channel emission",
            query.channel_emission_nm_min,
            query.channel_emission_nm_max,
        ),
    ):
        _validate_numeric_bounds(
            field_label=label,
            minimum=minimum,
            maximum=maximum,
            errors=errors,
        )

    return query, errors


def _query_filters(query: SearchQuery) -> dict[str, Any]:
    return {
        "instrument_model": query.instrument_model,
        "instrument_manufacturer": query.instrument_manufacturer,
        "objective_model": query.objective_model,
        "detector_model": query.detector_model,
        "image_name": query.image_name,
        "dataset_name": query.dataset_name,
        "project_name": query.project_name,
        "objective_magnification_min": query.objective_magnification_min,
        "objective_magnification_max": query.objective_magnification_max,
        "objective_na_min": query.objective_na_min,
        "objective_na_max": query.objective_na_max,
        "pixel_size_x_um_min": query.pixel_size_x_um_min,
        "pixel_size_x_um_max": query.pixel_size_x_um_max,
        "pixel_size_y_um_min": query.pixel_size_y_um_min,
        "pixel_size_y_um_max": query.pixel_size_y_um_max,
        "z_step_um_min": query.z_step_um_min,
        "z_step_um_max": query.z_step_um_max,
        "detector_gain_min": query.detector_gain_min,
        "detector_gain_max": query.detector_gain_max,
        "acquisition_date_from": query.acquisition_date_from,
        "acquisition_date_to": query.acquisition_date_to,
        "channel_label": query.channel_label,
        "channel_excitation_nm_min": query.channel_excitation_nm_min,
        "channel_excitation_nm_max": query.channel_excitation_nm_max,
        "channel_emission_nm_min": query.channel_emission_nm_min,
        "channel_emission_nm_max": query.channel_emission_nm_max,
    }


def _empty_search_payload(*, page: int = 1, page_size: int | None = None) -> dict[str, Any]:
    return {
        "results": [],
        "page": page,
        "page_size": page_size or runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }


def _current_user_id(conn) -> int | None:
    try:
        user = conn.getUser()
        user_id = user.getId() if user is not None else None
        if user_id is None:
            return None
        return int(user_id.getValue() if hasattr(user_id, "getValue") else user_id)
    except Exception:
        return None


def _visible_group_ids(conn) -> list[int] | None:
    try:
        admin_service = conn.getAdminService()
        user_id = _current_user_id(conn)
        if user_id is None:
            return None
        groups = admin_service.containedGroups(user_id)
    except Exception:
        logger.debug("Failed to resolve visible groups for search.", exc_info=True)
        return None

    group_ids: list[int] = []
    for group in groups or []:
        group_id = get_id(group)
        if group_id is None:
            continue
        try:
            group_ids.append(int(group_id))
        except (TypeError, ValueError):
            continue
    return sorted(set(group_ids))


def search(conn, query: SearchQuery) -> dict[str, Any]:
    if conn is None:
        logger.warning("Enhanced-search request arrived without an OMERO connection.")
        return _empty_search_payload(page=query.page)

    config = runtime_config()
    page_size = config.max_results
    page = max(1, query.page)
    offset = (page - 1) * page_size
    selected_scope = scope_map().get(query.scope_key) if query.scope_key else None

    with db_connect() as db_conn:
        rows, total_count = search_index_rows(
            db_conn,
            visible_group_ids=_visible_group_ids(conn),
            current_user_id=_current_user_id(conn),
            scope_filter=(
                (selected_scope.scope_type, selected_scope.scope_id)
                if selected_scope is not None
                else None
            ),
            query_text=query.query_text,
            filters=_query_filters(query),
            limit=page_size,
            offset=offset,
        )

    image_ids = [row["image_id"] for row in rows]
    accessible: dict[int, Any] = {}
    if image_ids:
        try:
            accessible = {
                int(get_id(image)): image
                for image in conn.getObjects("Image", ids=image_ids)
                if get_id(image) is not None
            }
        except TypeError:
            accessible = {
                int(get_id(image)): image
                for image in conn.getObjects("Image", obj_ids=image_ids)
                if get_id(image) is not None
            }
        except Exception:
            logger.debug("Image rehydration failed during search.", exc_info=True)
            accessible = {}

    results = []
    webindex = reverse("webindex")
    for row in rows:
        image = accessible.get(int(row["image_id"]))
        if image is None:
            continue
        try:
            current_name = str(get_text(image.getName()) or "")
        except Exception:
            current_name = ""
        results.append(
            {
                **row,
                "image_name": current_name or row["image_name"],
                "image_url": f"{webindex}?show=image-{row['image_id']}",
                "dataset_url": (
                    f"{webindex}?show=dataset-{row['dataset_id']}"
                    if row.get("dataset_id")
                    else ""
                ),
                "project_url": (
                    f"{webindex}?show=project-{row['project_id']}"
                    if row.get("project_id")
                    else ""
                ),
            }
        )

    return {
        "results": results,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "has_previous": page > 1,
        "has_next": (offset + page_size) < total_count,
    }


def saved_queries(username: str) -> list[dict[str, Any]]:
    if not username:
        return []
    with db_connect() as conn:
        return list_saved_queries(conn, username)


def save_query(username: str, query_name: str, query_payload: dict[str, Any]) -> None:
    with db_connect() as conn:
        save_saved_query(conn, username, query_name, query_payload)


def remove_saved_query(username: str, query_id: int) -> bool:
    with db_connect() as conn:
        return delete_saved_query(conn, username, query_id)


def saved_query_redirect_url(query_payload: dict[str, Any]) -> str:
    target = reverse("omeroweb_tools_enhanced_search")
    query_string = urlencode(
        {
            key: value
            for key, value in (query_payload or {}).items()
            if value not in (None, "", [])
        },
        doseq=True,
    )
    return f"{target}?{query_string}" if query_string else target


def _admin_secure_flag() -> bool:
    try:
        return get_bool_env(
            "CONFIG_omero_security_ssl",
            env_file=ENV_FILE_OMEROWEB,
        )
    except Exception:
        return True


@contextmanager
def _root_connection():
    root_password = str(os.environ.get("ROOTPASS") or "").strip()
    if not root_password:
        raise RuntimeError("ROOTPASS is missing; enhanced-search indexing cannot run.")

    host = get_env("OMEROHOST", env_file=ENV_FILE_OMEROWEB)
    port = int(get_env("OMERO_PORT", env_file=ENV_FILE_OMEROWEB))
    conn = BlitzGateway(
        "root",
        root_password,
        host=host,
        port=port,
        secure=_admin_secure_flag(),
    )
    if not conn.connect():
        raise RuntimeError("Failed to connect as root for enhanced-search indexing.")
    try:
        conn.SERVICE_OPTS.setOmeroGroup("-1")
    except Exception:
        logger.debug("Failed to set root search session to all groups.", exc_info=True)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            logger.debug("Failed to close root enhanced-search connection.", exc_info=True)


def _group_context(group_obj) -> tuple[str, bool]:
    group_name = ""
    group_can_read = False
    if group_obj is None:
        return group_name, group_can_read
    try:
        group_name = str(get_text(group_obj.getName()) or "")
    except Exception:
        group_name = ""
    try:
        details = group_obj.getDetails()
        permissions = details.getPermissions() if details else None
        group_can_read = bool(permissions and permissions.isGroupRead())
    except Exception:
        group_can_read = False
    return group_name, group_can_read


def _owner_name(image) -> str:
    try:
        owner = image.getOwner()
    except Exception:
        owner = None
    if owner is None:
        return ""
    for attr_name in ("getName", "getOmeName", "getFirstName"):
        getter = getattr(owner, attr_name, None)
        if not callable(getter):
            continue
        try:
            value = str(get_text(getter()) or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    owner_id = get_id(owner)
    return str(owner_id) if owner_id is not None else ""


def _images_for_scope(admin_conn, scope: EnhancedSearchScope) -> list[Any]:
    if scope.scope_type == "project":
        project = admin_conn.getObject("Project", scope.scope_id)
        if project is None:
            return []
        images: list[Any] = []
        for dataset in list(project.listChildren() or []):
            images.extend(list(dataset.listChildren() or []))
        return images

    if scope.scope_type == "dataset":
        dataset = admin_conn.getObject("Dataset", scope.scope_id)
        if dataset is None:
            return []
        return list(dataset.listChildren() or [])

    try:
        admin_conn.SERVICE_OPTS.setOmeroGroup(str(scope.scope_id))
    except Exception:
        logger.debug("Failed to scope root search connection to group.", exc_info=True)
    try:
        return list(admin_conn.getObjects("Image"))
    except Exception:
        logger.debug("Group-scoped image listing failed.", exc_info=True)
        return []


def _scope_image_rows(
    admin_conn,
    scope: EnhancedSearchScope,
    *,
    resume_after_image_id: int | None,
) -> list[Any]:
    images = _images_for_scope(admin_conn, scope)
    deduped = []
    seen: set[int] = set()
    cap = runtime_config().scope_image_cap
    for image in images:
        image_id = get_id(image)
        if image_id is None:
            continue
        try:
            image_id = int(image_id)
        except (TypeError, ValueError):
            continue
        if resume_after_image_id is not None and image_id <= resume_after_image_id:
            continue
        if image_id in seen:
            continue
        seen.add(image_id)
        deduped.append(image)
        if len(deduped) >= cap:
            break
    return sorted(deduped, key=lambda image: int(get_id(image) or 0))


def _document_for_image(
    image,
    schema_version: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    document, context = extract_search_document(image)
    group = None
    try:
        details = image.getDetails()
        group = details.getGroup() if details else None
    except Exception:
        group = None

    group_name, group_can_read = _group_context(group)
    group_id = get_id(group)
    owner_id = get_owner_id(image)

    image_row = {
        "image_id": int(get_id(image)),
        "group_id": int(group_id) if group_id is not None else 0,
        "group_name": group_name,
        "group_can_read": group_can_read,
        "owner_id": int(owner_id) if owner_id is not None else None,
        "owner_name": _owner_name(image),
        "image_name": str(get_text(image.getName()) or ""),
        "dataset_id": context["dataset_id"],
        "dataset_name": context["dataset_name"],
        "project_id": context["project_id"],
        "project_name": context["project_name"],
        "schema_version": schema_version,
        "acquisition_date": document.acquisition_date,
        "instrument_manufacturer": document.instrument_manufacturer,
        "instrument_model": document.instrument_model,
        "objective_model": document.objective_model,
        "objective_magnification": document.objective_magnification,
        "objective_na": document.objective_na,
        "detector_model": document.detector_model,
        "detector_binning": document.detector_binning,
        "detector_gain": document.detector_gain,
        "pixel_size_x_um": document.pixel_size_x_um,
        "pixel_size_y_um": document.pixel_size_y_um,
        "z_step_um": document.z_step_um,
        "channel_summary": document.channel_summary,
        "search_document": document.search_document,
    }
    channels = [
        {
            "channel_index": channel.channel_index,
            "label": channel.label,
            "excitation_nm": channel.excitation_nm,
            "emission_nm": channel.emission_nm,
        }
        for channel in document.channels
    ]
    attributes = [
        {
            "attribute_key": attribute.attribute_key,
            "attribute_text": attribute.attribute_text,
            "attribute_numeric": attribute.attribute_numeric,
        }
        for attribute in document.attributes
    ]
    return image_row, channels, attributes


def _sync_scope(
    scope: EnhancedSearchScope,
    run_token: str,
    *,
    resume_after_image_id: int | None,
) -> dict[str, Any]:
    config = runtime_config()
    processed_count = 0
    try:
        with _root_connection() as admin_conn:
            images = _scope_image_rows(
                admin_conn,
                scope,
                resume_after_image_id=resume_after_image_id,
            )
            if not images and resume_after_image_id is None:
                with db_connect() as db_conn:
                    prune_scope_membership(db_conn, scope.scope_type, scope.scope_id, run_token)
                    prune_orphan_documents(db_conn)
                    mark_sync_complete(
                        db_conn,
                        scope.scope_type,
                        scope.scope_id,
                        run_token=run_token,
                        indexed_image_count=0,
                        current_message="No images found for this scope.",
                    )
                return {"status": "idle", "indexed_image_count": 0}

            batch: list[Any] = []
            for image in images:
                batch.append(image)
                if len(batch) < config.batch_size:
                    continue
                processed_count = _process_sync_batch(
                    scope,
                    run_token,
                    batch,
                    processed_count,
                    config.schema_version,
                )
                batch = []
            if batch:
                processed_count = _process_sync_batch(
                    scope,
                    run_token,
                    batch,
                    processed_count,
                    config.schema_version,
                )

        with db_connect() as db_conn:
            stale_membership_count = prune_scope_membership(
                db_conn,
                scope.scope_type,
                scope.scope_id,
                run_token,
            )
            pruned_docs = prune_orphan_documents(db_conn)
            mark_sync_complete(
                db_conn,
                scope.scope_type,
                scope.scope_id,
                run_token=run_token,
                indexed_image_count=processed_count,
                current_message=(
                    f"Indexed {processed_count} image(s). "
                    f"Removed {stale_membership_count} stale scope links and "
                    f"{pruned_docs} orphaned search rows."
                ),
            )
        return {"status": "idle", "indexed_image_count": processed_count}
    except Exception as exc:
        logger.error(
            "Enhanced-search sync failed for %s: %s",
            scope.scope_key,
            sanitize_log_value(exc),
            exc_info=True,
        )
        with db_connect() as db_conn:
            mark_sync_error(
                db_conn,
                scope.scope_type,
                scope.scope_id,
                run_token=run_token,
                error_text="Enhanced-search indexing failed. Check server logs for details.",
                indexed_image_count=processed_count,
            )
        raise
    finally:
        with _SYNC_THREADS_LOCK:
            _SYNC_THREADS.pop(scope.scope_key, None)


def _process_sync_batch(
    scope: EnhancedSearchScope,
    run_token: str,
    images: list[Any],
    processed_count: int,
    schema_version: int,
) -> int:
    last_image_id = None
    with db_connect() as db_conn:
        for image in images:
            image_row, channels, attributes = _document_for_image(image, schema_version)
            last_image_id = image_row["image_id"]
            upsert_search_document(
                db_conn,
                image_row=image_row,
                channels=channels,
                attributes=attributes,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                run_token=run_token,
            )
            processed_count += 1
        update_sync_progress(
            db_conn,
            scope.scope_type,
            scope.scope_id,
            run_token=run_token,
            indexed_image_count=processed_count,
            current_message=f"Indexed {processed_count} image(s)…",
            last_cursor_image_id=last_image_id,
        )
    return processed_count


def _resume_cursor_for_scope(scope: EnhancedSearchScope) -> int | None:
    state = _scope_state(scope)
    if not state:
        return None
    last_cursor = state.get("last_cursor_image_id")
    if last_cursor in (None, ""):
        return None
    try:
        return int(last_cursor)
    except (TypeError, ValueError):
        return None


def run_scope_sync_task(scope_key: str, run_token: str) -> dict[str, Any]:
    scope = scope_map().get(scope_key)
    if scope is None:
        raise RuntimeError("Selected search scope is not enabled.")
    return _sync_scope(
        scope,
        run_token,
        resume_after_image_id=_resume_cursor_for_scope(scope),
    )


def _start_threaded_sync(scope: EnhancedSearchScope, run_token: str) -> None:
    worker = threading.Thread(
        target=run_scope_sync_task,
        args=(scope.scope_key, run_token),
        daemon=True,
        name=f"enhanced-search-{scope.scope_key}",
    )
    with _SYNC_THREADS_LOCK:
        _SYNC_THREADS[scope.scope_key] = worker
    worker.start()


def request_scope_sync(scope_key: str, requested_by: str) -> tuple[bool, str]:
    scope = scope_map().get(scope_key)
    if scope is None:
        return False, "Selected search scope is not enabled."

    config = runtime_config()
    run_token = uuid.uuid4().hex
    try:
        with db_connect() as conn:
            started = try_start_scope_sync(
                conn,
                scope.scope_type,
                scope.scope_id,
                scope.label,
                config.schema_version,
                requested_by,
                run_token,
                config.sync_stale_seconds,
            )
    except EnhancedSearchStoreError:
        return False, "Could not schedule enhanced-search indexing."

    if not started:
        return False, "Indexing is already running for this scope."

    celery_config = runtime_celery_config()
    if celery_config.enabled:
        try:
            from ..tasks import run_enhanced_search_scope_sync

            run_enhanced_search_scope_sync.apply_async(
                args=(scope.scope_key, run_token),
                queue=celery_config.queue,
            )
            return True, "Indexing started."
        except Exception as exc:
            logger.error(
                "Failed to dispatch enhanced-search sync task for %s: %s",
                scope.scope_key,
                sanitize_log_value(exc),
                exc_info=True,
            )
            with db_connect() as conn:
                mark_sync_error(
                    conn,
                    scope.scope_type,
                    scope.scope_id,
                    run_token=run_token,
                    error_text="Enhanced-search worker dispatch failed.",
                    indexed_image_count=0,
                )
            return False, "Could not dispatch enhanced-search indexing."

    _start_threaded_sync(scope, run_token)
    return True, "Indexing started."
