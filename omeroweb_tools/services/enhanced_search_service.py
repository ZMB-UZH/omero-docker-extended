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

from django.urls import reverse
from omero.gateway import BlitzGateway
from omero.rtypes import rtime

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
    clear_scope_index,
    connect as db_connect,
    delete_saved_query,
    ensure_sync_state_rows,
    list_saved_queries,
    list_sync_states,
    load_user_settings as load_user_settings_row,
    mark_sync_complete,
    mark_sync_error,
    prune_orphan_documents,
    prune_scope_membership,
    save_user_settings as save_user_settings_row,
    save_saved_query,
    search_index_rows,
    sync_run_is_active,
    try_start_scope_sync,
    update_sync_progress,
    upsert_search_document,
)
from .search_query_builder import build_omero_fulltext_query


logger = logging.getLogger(__name__)

_SYNC_THREADS: dict[str, threading.Thread] = {}
_SYNC_THREADS_LOCK = threading.Lock()

SEARCH_SCOPE_OMERO_BUILTIN = "omero_builtin"
SEARCH_SCOPE_ACQUISITION_METADATA = "acquisition_metadata"
SEARCH_SCOPE_ALL_INDEXED = "all_indexed_scopes"
SEARCH_SCOPE_LABELS = {
    SEARCH_SCOPE_OMERO_BUILTIN: "OMERO index",
    SEARCH_SCOPE_ACQUISITION_METADATA: "Acquisition metadata",
    SEARCH_SCOPE_ALL_INDEXED: "All indexed scopes",
}
USER_SCOPE_TYPE = "user"
USER_SCOPE_LABEL = "Your acquisition metadata"


class ScopeSyncCancelledError(RuntimeError):
    """Raised when a sync lease is cancelled or superseded."""


@dataclass(frozen=True)
class SearchQuery:
    query_text: str = ""
    indexed_scope: str = SEARCH_SCOPE_ALL_INDEXED
    acquisition_date_from: datetime | None = None
    acquisition_date_to: datetime | None = None
    page: int = 1

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "query_text": self.query_text,
            "indexed_scope": self.indexed_scope,
            "page": self.page,
        }
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


def _default_scope_label(scope_type: str, scope_id: int) -> str:
    if scope_type == USER_SCOPE_TYPE:
        return USER_SCOPE_LABEL
    return f"{scope_type.title()} {scope_id}"


def user_scope(user_id: int, username: str) -> EnhancedSearchScope:
    return EnhancedSearchScope(
        scope_type=USER_SCOPE_TYPE,
        scope_id=int(user_id),
        label=USER_SCOPE_LABEL if username else _default_scope_label(USER_SCOPE_TYPE, int(user_id)),
    )


def scope_from_key(scope_key: str, *, label: str | None = None) -> EnhancedSearchScope | None:
    raw_scope_key = str(scope_key or "").strip()
    if ":" not in raw_scope_key:
        return None
    scope_type, raw_scope_id = raw_scope_key.split(":", 1)
    scope_type = scope_type.strip().lower()
    if scope_type != USER_SCOPE_TYPE:
        return None
    try:
        scope_id = int(str(raw_scope_id).strip())
    except (TypeError, ValueError):
        return None
    resolved_label = str(label or "").strip() or _default_scope_label(scope_type, scope_id)
    return EnhancedSearchScope(scope_type=scope_type, scope_id=scope_id, label=resolved_label)


def ensure_scope_state(scopes: tuple[EnhancedSearchScope, ...] | list[EnhancedSearchScope]) -> list[dict[str, Any]]:
    normalized_scopes = tuple(scopes or ())
    if not normalized_scopes:
        return []
    with db_connect() as conn:
        ensure_sync_state_rows(
            conn,
            [scope.to_dict() for scope in normalized_scopes],
            runtime_config().schema_version,
        )
        return list_sync_states(conn)


def current_sync_states(scopes: tuple[EnhancedSearchScope, ...] | list[EnhancedSearchScope]) -> list[dict[str, Any]]:
    by_key = {
        f"{state['scope_type']}:{state['scope_id']}": state
        for state in ensure_scope_state(scopes)
    }
    merged: list[dict[str, Any]] = []
    for scope in tuple(scopes or ()):
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


def parse_search_query(params) -> tuple[SearchQuery, list[str]]:
    errors: list[str] = []

    def read_text(name: str) -> str:
        return str(params.get(name) or "").strip()

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

    indexed_scope = read_text("indexed_scope") or SEARCH_SCOPE_ALL_INDEXED
    if indexed_scope not in SEARCH_SCOPE_LABELS:
        errors.append("Selected indexed scope is not supported.")
        indexed_scope = SEARCH_SCOPE_ALL_INDEXED

    query = SearchQuery(
        query_text=read_text("query_text"),
        indexed_scope=indexed_scope,
        acquisition_date_from=acquisition_date_from,
        acquisition_date_to=acquisition_date_to,
        page=page,
    )

    return query, errors


def _query_filters(query: SearchQuery) -> dict[str, Any]:
    return {
        "acquisition_date_from": query.acquisition_date_from,
        "acquisition_date_to": query.acquisition_date_to,
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


def search_scope_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {"value": value, "label": SEARCH_SCOPE_LABELS[value]}
        for value in (
            SEARCH_SCOPE_OMERO_BUILTIN,
            SEARCH_SCOPE_ACQUISITION_METADATA,
            SEARCH_SCOPE_ALL_INDEXED,
        )
    )


def default_user_settings() -> dict[str, Any]:
    return {"acquisition_metadata_enabled": False}


def _coerce_bool(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(raw_value)


def _normalized_user_settings(settings_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(default_user_settings())
    payload["acquisition_metadata_enabled"] = _coerce_bool(
        (settings_payload or {}).get("acquisition_metadata_enabled")
    )
    return payload


def user_settings(username: str) -> dict[str, Any]:
    if not username:
        return default_user_settings()
    with db_connect() as conn:
        return _normalized_user_settings(
            load_user_settings_row(
                conn,
                username,
                defaults=default_user_settings(),
            )
        )


def sync_states_for_user(conn, username: str) -> list[dict[str, Any]]:
    scope = current_user_scope(conn, username)
    if scope is None:
        return []
    return current_sync_states((scope,))


def current_user_scope(conn, username: str) -> EnhancedSearchScope | None:
    user_id = _current_user_id(conn)
    if not username or user_id is None:
        return None
    return user_scope(user_id, username)


def _current_user_id(conn) -> int | None:
    try:
        user = conn.getUser()
        user_id = user.getId() if user is not None else None
        if user_id is None:
            return None
        return int(user_id.getValue() if hasattr(user_id, "getValue") else user_id)
    except Exception:
        return None


def _sync_state_needs_refresh(state: dict[str, Any] | None) -> bool:
    if not state:
        return True
    if state.get("status") == "running":
        return False
    last_successful_at = _normalized_sort_datetime(state.get("last_successful_at"))
    if last_successful_at is None:
        return True
    stale_after = timedelta(seconds=runtime_config().sync_stale_seconds)
    return (datetime.now(timezone.utc) - last_successful_at) >= stale_after


def ensure_user_index_sync(
    conn,
    username: str,
    *,
    settings_payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool, str]:
    scope = current_user_scope(conn, username)
    if scope is None:
        return [], False, ""

    states = current_sync_states((scope,))
    normalized_settings = _normalized_user_settings(settings_payload)
    if not normalized_settings.get("acquisition_metadata_enabled"):
        return states, False, ""

    state = states[0] if states else None
    if not _sync_state_needs_refresh(state):
        return states, False, ""

    started, message = request_scope_sync(
        scope.scope_key,
        username,
        scope_label=scope.label,
    )
    return sync_states_for_user(conn, username), started, message


def save_user_settings(conn, username: str, settings_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalized_user_settings(settings_payload)
    user_id = _current_user_id(conn)
    previous = user_settings(username)
    with db_connect() as db_conn:
        stored = _normalized_user_settings(
            save_user_settings_row(db_conn, username, normalized)
        )
        if user_id is not None and not stored["acquisition_metadata_enabled"]:
            clear_scope_index(
                db_conn,
                USER_SCOPE_TYPE,
                user_id,
                current_message="Acquisition metadata indexing is disabled for your account.",
            )

    sync_started = False
    sync_message = ""
    scope = current_user_scope(conn, username)
    if scope is not None and stored["acquisition_metadata_enabled"]:
        scope_states = current_sync_states((scope,))
        state = scope_states[0] if scope_states else None
        should_auto_start = (
            not previous.get("acquisition_metadata_enabled")
            or _sync_state_needs_refresh(state)
        )
        if should_auto_start:
            sync_started, sync_message = request_scope_sync(
                scope.scope_key,
                username,
                scope_label=scope.label,
            )

    return {
        "user_settings": stored,
        "sync_started": sync_started,
        "sync_message": sync_message,
        "sync_states": sync_states_for_user(conn, username),
    }


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


def _datetime_to_rtime(value: datetime):
    normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return rtime(int(normalized.timestamp() * 1000))


def _omero_search_created_range(query: SearchQuery):
    if query.acquisition_date_from is None and query.acquisition_date_to is None:
        return None
    lower_bound = query.acquisition_date_from or datetime(1970, 1, 1, tzinfo=timezone.utc)
    upper_bound = query.acquisition_date_to or datetime.now(timezone.utc)
    return (_datetime_to_rtime(lower_bound), _datetime_to_rtime(upper_bound))


def _result_row_from_image(image) -> dict[str, Any]:
    image_row, _channels, _attributes = _document_for_image(
        image,
        runtime_config().schema_version,
    )
    return image_row


def _images_from_builtin_search_hit(hit) -> list[Any]:
    omero_class = str(getattr(hit, "OMERO_CLASS", "") or "").lower()
    if omero_class == "image":
        return [hit]
    if omero_class == "dataset":
        try:
            return list(hit.listChildren() or [])
        except Exception:
            return []
    if omero_class == "project":
        images: list[Any] = []
        try:
            for dataset in list(hit.listChildren() or []):
                images.extend(list(dataset.listChildren() or []))
        except Exception:
            return []
        return images
    return []


def _merge_indexed_sources(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for source in incoming:
        if source not in merged:
            merged.append(source)
    return merged


def _normalized_sort_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _merged_result_sort_key(row: dict[str, Any]) -> tuple[int, datetime, int]:
    acquisition_date = _normalized_sort_datetime(row.get("acquisition_date"))
    return (
        1 if acquisition_date is not None else 0,
        acquisition_date or datetime(1970, 1, 1, tzinfo=timezone.utc),
        int(row.get("image_id") or 0),
    )


def _search_omero_builtin_rows(conn, query: SearchQuery) -> list[dict[str, Any]]:
    if not query.query_text:
        return []

    fulltext_query = build_omero_fulltext_query(query.query_text)
    if not fulltext_query:
        return []

    created = _omero_search_created_range(query)
    object_types = ["Image"] if created is not None else ["Project", "Dataset", "Image"]
    batch_size = min(max(runtime_config().max_results * 2, 100), 500)
    results: list[dict[str, Any]] = []
    seen_image_ids: set[int] = set()
    page_index = 0
    search_kwargs = {
        "created": created,
        "batchSize": batch_size,
        "page": 0,
        "searchGroup": "-1",
        "useAcquisitionDate": created is not None,
        "rawQuery": True,
    }

    while True:
        try:
            batch = conn.searchObjects(
                object_types,
                fulltext_query,
                **{**search_kwargs, "page": page_index},
            )
        except Exception:
            if search_kwargs["searchGroup"] is None:
                logger.debug("OMERO built-in search failed.", exc_info=True)
                break
            logger.debug(
                "OMERO built-in all-group search failed; retrying current context.",
                exc_info=True,
            )
            search_kwargs["searchGroup"] = None
            continue

        if not batch:
            break

        for hit in batch:
            for image in _images_from_builtin_search_hit(hit):
                image_id = get_id(image)
                if image_id is None:
                    continue
                try:
                    image_id = int(image_id)
                except (TypeError, ValueError):
                    continue
                if image_id in seen_image_ids:
                    continue
                seen_image_ids.add(image_id)
                row = _result_row_from_image(image)
                row["indexed_sources"] = [SEARCH_SCOPE_LABELS[SEARCH_SCOPE_OMERO_BUILTIN]]
                results.append(row)

        if len(batch) < batch_size:
            break
        page_index += 1

    return results


def _merge_result_rows(
    acquisition_rows: list[dict[str, Any]],
    omero_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}

    for row in acquisition_rows:
        image_id = int(row["image_id"])
        merged[image_id] = {
            **row,
            "indexed_sources": [SEARCH_SCOPE_LABELS[SEARCH_SCOPE_ACQUISITION_METADATA]],
        }

    for row in omero_rows:
        image_id = int(row["image_id"])
        existing = merged.get(image_id)
        if existing is None:
            merged[image_id] = row
            continue
        existing["indexed_sources"] = _merge_indexed_sources(
            existing.get("indexed_sources") or [],
            row.get("indexed_sources") or [],
        )
        for key, value in row.items():
            if key == "indexed_sources":
                continue
            if existing.get(key) in (None, "") and value not in (None, ""):
                existing[key] = value

    return sorted(
        merged.values(),
        key=_merged_result_sort_key,
        reverse=True,
    )


def _accessible_images_by_id(conn, image_ids: list[int]) -> dict[int, Any]:
    if not image_ids:
        return {}
    try:
        return {
            int(get_id(image)): image
            for image in conn.getObjects("Image", ids=image_ids)
            if get_id(image) is not None
        }
    except TypeError:
        return {
            int(get_id(image)): image
            for image in conn.getObjects("Image", obj_ids=image_ids)
            if get_id(image) is not None
        }
    except Exception:
        logger.debug("Image rehydration failed during search.", exc_info=True)
        return {}


def search(
    conn,
    query: SearchQuery,
    *,
    acquisition_metadata_enabled: bool,
) -> dict[str, Any]:
    if conn is None:
        logger.warning("Enhanced-search request arrived without an OMERO connection.")
        return _empty_search_payload(page=query.page)

    config = runtime_config()
    page_size = config.max_results
    page = max(1, query.page)
    offset = (page - 1) * page_size

    acquisition_rows: list[dict[str, Any]] = []
    if (
        query.indexed_scope in (
            SEARCH_SCOPE_ACQUISITION_METADATA,
            SEARCH_SCOPE_ALL_INDEXED,
        )
        and acquisition_metadata_enabled
    ):
        with db_connect() as db_conn:
            acquisition_rows, _unused_total = search_index_rows(
                db_conn,
                visible_group_ids=_visible_group_ids(conn),
                current_user_id=_current_user_id(conn),
                query_text=query.query_text,
                filters=_query_filters(query),
                limit=None,
                offset=0,
            )

    omero_rows: list[dict[str, Any]] = []
    if query.indexed_scope in (
        SEARCH_SCOPE_OMERO_BUILTIN,
        SEARCH_SCOPE_ALL_INDEXED,
    ):
        omero_rows = _search_omero_builtin_rows(conn, query)

    merged_rows = _merge_result_rows(acquisition_rows, omero_rows)
    total_count = len(merged_rows)
    page_rows = merged_rows[offset : offset + page_size]

    accessible = _accessible_images_by_id(
        conn,
        [int(row["image_id"]) for row in page_rows],
    )

    results = []
    webindex = reverse("webindex")
    for row in page_rows:
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
                "thumbnail_url": reverse("render_thumbnail", args=(row["image_id"],)),
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
    try:
        return list(
            admin_conn.getObjects(
                "Image",
                opts={"owner": scope.scope_id, "group": "-1"},
            )
        )
    except Exception:
        logger.debug("User-scoped image listing failed.", exc_info=True)
        return []


def _scope_image_rows(
    admin_conn,
    scope: EnhancedSearchScope,
) -> list[Any]:
    images = _images_for_scope(admin_conn, scope)
    deduped = []
    seen: set[int] = set()
    for image in images:
        image_id = get_id(image)
        if image_id is None:
            continue
        try:
            image_id = int(image_id)
        except (TypeError, ValueError):
            continue
        if image_id in seen:
            continue
        seen.add(image_id)
        deduped.append(image)
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
) -> dict[str, Any]:
    config = runtime_config()
    processed_count = 0
    try:
        with _root_connection() as admin_conn:
            images = _scope_image_rows(admin_conn, scope)
            if not images:
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
    except ScopeSyncCancelledError:
        logger.info(
            "Enhanced-search sync lease cancelled for %s.",
            scope.scope_key,
        )
        return {"status": "idle", "indexed_image_count": processed_count, "cancelled": True}
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
            if not sync_run_is_active(
                db_conn,
                scope.scope_type,
                scope.scope_id,
                run_token=run_token,
            ):
                raise ScopeSyncCancelledError(
                    f"Sync lease is no longer active for {scope.scope_key}."
                )
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


def run_scope_sync_task(scope_key: str, run_token: str) -> dict[str, Any]:
    scope = scope_from_key(scope_key)
    if scope is None:
        raise RuntimeError("Selected search scope is not valid.")
    return _sync_scope(scope, run_token)


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


def request_scope_sync(
    scope_key: str,
    requested_by: str,
    *,
    scope_label: str | None = None,
) -> tuple[bool, str]:
    scope = scope_from_key(scope_key, label=scope_label)
    if scope is None:
        return False, "Selected search scope is not valid."

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
