from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
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
from ..task_names import ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME
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


class _AcquisitionSearchKwargs(TypedDict):
    """Represent acquisition search kwargs."""

    visible_group_ids: list[int] | None
    current_user_id: int
    scope_type: str
    scope_id: int
    query_text: str
    filters: dict[str, Any]
    limit: int | None
    offset: int


logger = logging.getLogger(__name__)

_SYNC_THREADS: dict[str, threading.Thread] = {}
_SYNC_THREADS_LOCK = threading.Lock()

SEARCH_SCOPE_OMERO_BUILTIN = "omero_builtin"
SEARCH_SCOPE_ACQUISITION_METADATA = "acquisition_metadata"
SEARCH_SCOPE_ALL_INDEXED = "all_indexed_scopes"
SEARCH_SCOPE_LABELS = {
    SEARCH_SCOPE_OMERO_BUILTIN: "OMERO index",
    SEARCH_SCOPE_ACQUISITION_METADATA: "Universal metadata index",
    SEARCH_SCOPE_ALL_INDEXED: "All searchable sources",
}
SEARCH_SOURCE_DISPLAY_ORDER = (
    SEARCH_SCOPE_LABELS[SEARCH_SCOPE_OMERO_BUILTIN],
    SEARCH_SCOPE_LABELS[SEARCH_SCOPE_ACQUISITION_METADATA],
)
USER_SCOPE_TYPE = "user"
USER_SCOPE_LABEL = "Your universal metadata index"
COLLAPSIBLE_SECTION_METADATA_INDEX = "metadata-index"
COLLAPSIBLE_SECTION_SAVED_QUERIES = "saved-queries"
SUPPORTED_COLLAPSIBLE_SECTIONS = (
    COLLAPSIBLE_SECTION_METADATA_INDEX,
    COLLAPSIBLE_SECTION_SAVED_QUERIES,
)
_SUPPORTED_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d--%m--%Y")
ACQUISITION_INDEXING_ENABLED_MESSAGE = (
    "Universal metadata indexing is enabled for your user account. "
    "All images you own will be indexed automatically in the background."
)
ACQUISITION_INDEXING_DISABLED_MESSAGE = (
    "Universal metadata indexing is disabled for your user account."
)
ACQUISITION_INDEXING_DISABLED_DETAIL_MESSAGE = (
    "Universal metadata indexing is disabled."
)
USER_SETTINGS_LOAD_ERROR_MESSAGE = (
    "Could not retrieve user setting. Database is not accessible."
)
USER_SETTINGS_SAVE_ERROR_MESSAGE = (
    "Could not save user setting. Database is not accessible."
)


class ScopeSyncCancelledError(RuntimeError):
    """Raised when a sync lease is cancelled or superseded."""


@dataclass(frozen=True)
class SearchQuery:
    """Represent search query."""

    query_text: str = ""
    indexed_scope: str = SEARCH_SCOPE_ALL_INDEXED
    acquisition_date_from: datetime | None = None
    acquisition_date_to: datetime | None = None
    page: int = 1

    @staticmethod
    def _display_date(value: datetime | None) -> str:
        """Handle display date."""
        if value is None:
            return ""
        return value.astimezone(timezone.utc).strftime("%d-%m-%Y")

    @property
    def acquisition_date_from_display(self) -> str:
        return self._display_date(self.acquisition_date_from)

    @property
    def acquisition_date_to_display(self) -> str:
        return self._display_date(self.acquisition_date_to)

    def to_payload(self) -> dict[str, Any]:
        """Handle to payload."""
        payload = {
            "query_text": self.query_text,
            "indexed_scope": self.indexed_scope,
            "page": self.page,
        }
        if self.acquisition_date_from is not None:
            payload["acquisition_date_from"] = (
                self.acquisition_date_from.date().isoformat()
            )
        if self.acquisition_date_to is not None:
            payload["acquisition_date_to"] = self.acquisition_date_to.date().isoformat()
        return payload

    def with_page(self, page: int) -> "SearchQuery":
        """Handle with page."""
        return SearchQuery(**{**self.__dict__, "page": max(1, int(page))})

    def to_querystring(self, *, page: int | None = None) -> str:
        """Handle to querystring."""
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
    """Run runtime config."""
    return build_enhanced_search_config()


def runtime_celery_config() -> EnhancedSearchCeleryConfig:
    """Run runtime celery config."""
    return build_enhanced_search_celery_config()


def acquisition_index_status_message(enabled: bool) -> str:
    """Handle acquisition index status message."""
    return (
        ACQUISITION_INDEXING_ENABLED_MESSAGE
        if enabled
        else ACQUISITION_INDEXING_DISABLED_MESSAGE
    )


def acquisition_index_disabled_detail_message() -> str:
    """Handle acquisition index disabled detail message."""
    return ACQUISITION_INDEXING_DISABLED_DETAIL_MESSAGE


def user_settings_load_error_message() -> str:
    """Handle user settings load error message."""
    return USER_SETTINGS_LOAD_ERROR_MESSAGE


def user_settings_save_error_message() -> str:
    """Handle user settings save error message."""
    return USER_SETTINGS_SAVE_ERROR_MESSAGE


def _default_scope_label(scope_type: str, scope_id: int) -> str:
    """Handle default scope label."""
    if scope_type == USER_SCOPE_TYPE:
        return USER_SCOPE_LABEL
    return f"{scope_type.title()} {scope_id}"


def user_scope(user_id: int, username: str) -> EnhancedSearchScope:
    """Handle user scope."""
    return EnhancedSearchScope(
        scope_type=USER_SCOPE_TYPE,
        scope_id=int(user_id),
        label=USER_SCOPE_LABEL
        if username
        else _default_scope_label(USER_SCOPE_TYPE, int(user_id)),
    )


def scope_from_key(
    scope_key: str, *, label: str | None = None
) -> EnhancedSearchScope | None:
    """Handle scope from key."""
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
    resolved_label = str(label or "").strip() or _default_scope_label(
        scope_type, scope_id
    )
    return EnhancedSearchScope(
        scope_type=scope_type, scope_id=scope_id, label=resolved_label
    )


def ensure_scope_state(
    scopes: tuple[EnhancedSearchScope, ...] | list[EnhancedSearchScope],
) -> list[dict[str, Any]]:
    """Handle ensure scope state."""
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


def current_sync_states(
    scopes: tuple[EnhancedSearchScope, ...] | list[EnhancedSearchScope],
) -> list[dict[str, Any]]:
    """Handle current sync states."""
    by_key = {
        f"{state['scope_type']}:{state['scope_id']}": state
        for state in ensure_scope_state(scopes)
    }
    merged: list[dict[str, Any]] = []
    for scope in tuple(scopes or ()):
        state = {
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
        state["current_message"] = _normalized_sync_detail_message(
            state.get("current_message")
        )
        merged.append(state)
    return merged


def _normalized_sync_detail_message(raw_message: Any) -> str:
    """Handle normalized sync detail message."""
    message = str(raw_message or "")
    if message in {
        ACQUISITION_INDEXING_DISABLED_MESSAGE,
        (
            "Universal metadata indexing is disabled for your user account. "
            "No indexed image metadata is stored for your user account."
        ),
    }:
        return ACQUISITION_INDEXING_DISABLED_DETAIL_MESSAGE
    return message


def _parse_date(raw_value: Any, *, end_of_day: bool = False) -> datetime | None:
    """Handle parse date."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00")
        except ValueError:
            for date_format in _SUPPORTED_DATE_FORMATS:
                try:
                    parsed = datetime.strptime(text, date_format)
                    break
                except ValueError:
                    continue
    if parsed is None:
        raise ValueError(f"Unsupported date value: {text!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if end_of_day and "T" not in text:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def parse_search_query(params) -> tuple[SearchQuery, list[str]]:
    """Validate parse search query."""
    errors: list[str] = []

    def read_text(name: str) -> str:
        """Return read text."""
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
    """Handle query filters."""
    return {
        "acquisition_date_from": query.acquisition_date_from,
        "acquisition_date_to": query.acquisition_date_to,
    }


def _empty_search_payload(
    *, page: int = 1, page_size: int | None = None
) -> dict[str, Any]:
    """Handle empty search payload."""
    return {
        "results": [],
        "page": page,
        "page_size": page_size or runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }


def search_scope_options() -> tuple[dict[str, str], ...]:
    """Handle search scope options."""
    return tuple(
        {"value": value, "label": SEARCH_SCOPE_LABELS[value]}
        for value in (
            SEARCH_SCOPE_OMERO_BUILTIN,
            SEARCH_SCOPE_ACQUISITION_METADATA,
            SEARCH_SCOPE_ALL_INDEXED,
        )
    )


def default_user_settings() -> dict[str, Any]:
    """Handle default user settings."""
    return {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": [],
    }


def _coerce_bool(raw_value: Any) -> bool:
    """Handle coerce bool."""
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(raw_value)


def _normalized_user_settings(
    settings_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Handle normalized user settings."""
    raw_payload = settings_payload or {}
    payload = dict(default_user_settings())
    payload["acquisition_metadata_enabled"] = _coerce_bool(
        raw_payload.get("acquisition_metadata_enabled")
    )
    raw_sections = raw_payload.get("collapsed_sections")
    if not isinstance(raw_sections, (list, tuple, set)):
        raw_sections = []
    supported = set(SUPPORTED_COLLAPSIBLE_SECTIONS)
    requested = {str(section) for section in raw_sections if str(section) in supported}
    payload["collapsed_sections"] = [
        section for section in SUPPORTED_COLLAPSIBLE_SECTIONS if section in requested
    ]
    return payload


def user_settings(username: str) -> dict[str, Any]:
    """Handle user settings."""
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
    """Handle sync states for user."""
    scope = current_user_scope(conn, username)
    if scope is None:
        return []
    return current_sync_states((scope,))


def current_user_scope(conn, username: str) -> EnhancedSearchScope | None:
    """Handle current user scope."""
    user_id = _current_user_id(conn)
    if not username or user_id is None:
        return None
    return user_scope(user_id, username)


def _current_user_id(conn) -> int | None:
    """Handle current user identifier."""
    try:
        user = conn.getUser()
        user_id = user.getId() if user is not None else None
        if user_id is None:
            return None
        return int(user_id.getValue() if hasattr(user_id, "getValue") else user_id)
    except Exception:
        return None


def _sync_state_needs_refresh(state: dict[str, Any] | None) -> bool:
    """Handle sync state needs refresh."""
    if not state:
        return True
    stale_after = timedelta(seconds=runtime_config().sync_stale_seconds)
    updated_at = _normalized_sort_datetime(state.get("updated_at"))
    if state.get("status") == "running":
        if updated_at is None:
            return True
        return (datetime.now(timezone.utc) - updated_at) >= stale_after
    last_successful_at = _normalized_sort_datetime(state.get("last_successful_at"))
    if last_successful_at is None:
        return True
    return (datetime.now(timezone.utc) - last_successful_at) >= stale_after


def ensure_user_index_sync(
    conn,
    username: str,
    *,
    settings_payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool, str]:
    """Handle ensure user index sync."""
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


def save_user_settings(
    conn, username: str, settings_payload: dict[str, Any]
) -> dict[str, Any]:
    """Store save user settings."""
    user_id = _current_user_id(conn)
    previous = user_settings(username)
    normalized = _normalized_user_settings({**previous, **(settings_payload or {})})
    with db_connect() as db_conn:
        stored = _normalized_user_settings(
            save_user_settings_row(db_conn, username, normalized)
        )
        if user_id is not None and not stored["acquisition_metadata_enabled"]:
            clear_scope_index(
                db_conn,
                USER_SCOPE_TYPE,
                user_id,
                current_message=acquisition_index_disabled_detail_message(),
            )

    sync_started = False
    sync_message = ""
    scope = current_user_scope(conn, username)
    if scope is not None and stored["acquisition_metadata_enabled"]:
        scope_states = current_sync_states((scope,))
        state = scope_states[0] if scope_states else None
        should_auto_start = not previous.get(
            "acquisition_metadata_enabled"
        ) or _sync_state_needs_refresh(state)
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
    """Handle visible group identifiers."""
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
    """Handle datetime to rtime."""
    normalized = (
        value.astimezone(timezone.utc)
        if value.tzinfo
        else value.replace(tzinfo=timezone.utc)
    )
    return rtime(int(normalized.timestamp() * 1000))


def _omero_search_created_range(query: SearchQuery):
    """Handle OMERO search created range."""
    if query.acquisition_date_from is None and query.acquisition_date_to is None:
        return None
    lower_bound = query.acquisition_date_from or datetime(
        1970, 1, 1, tzinfo=timezone.utc
    )
    upper_bound = query.acquisition_date_to or datetime.now(timezone.utc)
    return (_datetime_to_rtime(lower_bound), _datetime_to_rtime(upper_bound))


def _result_row_from_image(image) -> dict[str, Any]:
    """Handle result row from image."""
    image_row, _channels, _attributes = _document_for_image(
        image,
        runtime_config().schema_version,
    )
    return image_row


def _images_from_builtin_search_hit(hit) -> list[Any]:
    """Handle images from builtin search hit."""
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
    """Handle merge indexed sources."""
    merged = set(existing or [])
    merged.update(incoming or [])
    ordered = [source for source in SEARCH_SOURCE_DISPLAY_ORDER if source in merged]
    extras = sorted(
        source for source in merged if source not in SEARCH_SOURCE_DISPLAY_ORDER
    )
    return ordered + extras


def _normalized_sort_datetime(value: Any) -> datetime | None:
    """Handle normalized sort datetime."""
    if not isinstance(value, datetime):
        return None
    return (
        value.astimezone(timezone.utc)
        if value.tzinfo
        else value.replace(tzinfo=timezone.utc)
    )


def _merged_result_sort_key(row: dict[str, Any]) -> tuple[int, datetime, int]:
    """Handle merged result sort key."""
    acquisition_date = _normalized_sort_datetime(row.get("acquisition_date"))
    return (
        1 if acquisition_date is not None else 0,
        acquisition_date or datetime(1970, 1, 1, tzinfo=timezone.utc),
        int(row.get("image_id") or 0),
    )


def _search_omero_builtin_rows(conn, query: SearchQuery) -> list[dict[str, Any]]:
    """Handle search OMERO builtin rows."""
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
                row["indexed_sources"] = [
                    SEARCH_SCOPE_LABELS[SEARCH_SCOPE_OMERO_BUILTIN]
                ]
                results.append(row)

        if len(batch) < batch_size:
            break
        page_index += 1

    return results


def _search_acquisition_index_rows(
    *,
    visible_group_ids: list[int] | None,
    current_user_id: int,
    scope_type: str,
    scope_id: int,
    query_text: str,
    filters: dict[str, Any],
    limit: int | None,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Handle search acquisition index rows."""
    with db_connect() as db_conn:
        return search_index_rows(
            db_conn,
            visible_group_ids=visible_group_ids,
            current_user_id=current_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            query_text=query_text,
            filters=filters,
            limit=limit,
            offset=offset,
        )


def _merge_result_rows(
    acquisition_rows: list[dict[str, Any]],
    omero_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle merge result rows."""
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
    """Handle accessible images by identifier."""
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
    """Handle search."""
    if conn is None:
        logger.warning("Enhanced-search request arrived without an OMERO connection.")
        return _empty_search_payload(page=query.page)

    config = runtime_config()
    page_size = config.max_results
    page = max(1, query.page)
    offset = (page - 1) * page_size
    has_query_text = bool(str(query.query_text or "").strip())
    has_date_filter = (
        query.acquisition_date_from is not None or query.acquisition_date_to is not None
    )

    if not has_query_text and not has_date_filter:
        return _empty_search_payload(page=page, page_size=page_size)

    acquisition_rows: list[dict[str, Any]] = []
    acquisition_total_count = 0
    acquisition_scope_only = query.indexed_scope == SEARCH_SCOPE_ACQUISITION_METADATA
    should_search_omero = query.indexed_scope in (
        SEARCH_SCOPE_OMERO_BUILTIN,
        SEARCH_SCOPE_ALL_INDEXED,
    )
    should_search_acquisition = (
        query.indexed_scope
        in (
            SEARCH_SCOPE_ACQUISITION_METADATA,
            SEARCH_SCOPE_ALL_INDEXED,
        )
        and acquisition_metadata_enabled
    )
    current_user_id = _current_user_id(conn) if should_search_acquisition else None
    acquisition_kwargs: _AcquisitionSearchKwargs | None = None
    if should_search_acquisition and current_user_id is not None:
        acquisition_kwargs = {
            "visible_group_ids": _visible_group_ids(conn),
            "current_user_id": current_user_id,
            "scope_type": USER_SCOPE_TYPE,
            "scope_id": current_user_id,
            "query_text": query.query_text,
            "filters": _query_filters(query),
            "limit": page_size if acquisition_scope_only else None,
            "offset": offset if acquisition_scope_only else 0,
        }

    omero_rows: list[dict[str, Any]] = []
    if (
        acquisition_kwargs is not None
        and should_search_omero
        and not acquisition_scope_only
    ):
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="enhanced-search-source",
        ) as executor:
            acquisition_future = executor.submit(
                _search_acquisition_index_rows,
                **acquisition_kwargs,
            )
            omero_rows = _search_omero_builtin_rows(conn, query)
            acquisition_rows, acquisition_total_count = acquisition_future.result()
    else:
        if acquisition_kwargs is not None:
            acquisition_rows, acquisition_total_count = _search_acquisition_index_rows(
                **acquisition_kwargs
            )
        if should_search_omero:
            omero_rows = _search_omero_builtin_rows(conn, query)

    if acquisition_scope_only:
        total_count = acquisition_total_count
        page_rows = acquisition_rows
    else:
        merged_rows = _merge_result_rows(acquisition_rows, omero_rows)
        total_count = len(merged_rows)
        page_rows = merged_rows[offset : offset + page_size]

    if not page_rows:
        return {
            "results": [],
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "has_previous": page > 1,
            "has_next": False,
        }

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
    """Store saved queries."""
    if not username:
        return []
    with db_connect() as conn:
        return list_saved_queries(conn, username)


def save_query(username: str, query_name: str, query_payload: dict[str, Any]) -> None:
    """Store save query."""
    with db_connect() as conn:
        save_saved_query(conn, username, query_name, query_payload)


def remove_saved_query(username: str, query_id: int) -> bool:
    """Handle remove saved query."""
    with db_connect() as conn:
        return delete_saved_query(conn, username, query_id)


def saved_query_redirect_url(query_payload: dict[str, Any]) -> str:
    """Store saved query redirect URL."""
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
    """Handle admin secure flag."""
    try:
        return get_bool_env(
            "CONFIG_omero_security_ssl",
            env_file=ENV_FILE_OMEROWEB,
        )
    except Exception:
        return True


@contextmanager
def _root_connection():
    """Handle root connection."""
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
            logger.debug(
                "Failed to close root enhanced-search connection.", exc_info=True
            )


def _group_context(group_obj) -> tuple[str, bool]:
    """Handle group context."""
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
    """Handle owner name."""
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
    """Handle images for scope."""
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
    """Handle scope image rows."""
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
    """Handle document for image."""
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
    """Handle sync scope."""
    config = runtime_config()
    processed_count = 0
    try:
        with _root_connection() as admin_conn:
            images = _scope_image_rows(admin_conn, scope)
            if not images:
                with db_connect() as db_conn:
                    prune_scope_membership(
                        db_conn, scope.scope_type, scope.scope_id, run_token
                    )
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
        return {
            "status": "idle",
            "indexed_image_count": processed_count,
            "cancelled": True,
        }
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
    """Handle process sync batch."""
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
                commit=False,
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
            commit=False,
            run_token=run_token,
            indexed_image_count=processed_count,
            current_message=f"Indexed {processed_count} image(s).",
            last_cursor_image_id=last_image_id,
        )
        try:
            commit_fn = db_conn.commit
        except AttributeError:
            return processed_count
        if callable(commit_fn):
            commit_fn()
    return processed_count


def run_scope_sync_task(scope_key: str, run_token: str) -> dict[str, Any]:
    """Run run scope sync task."""
    scope = scope_from_key(scope_key)
    if scope is None:
        raise RuntimeError("Selected search scope is not valid.")
    return _sync_scope(scope, run_token)


def _start_threaded_sync(scope: EnhancedSearchScope, run_token: str) -> None:
    """Handle start threaded sync."""
    worker = threading.Thread(
        target=run_scope_sync_task,
        args=(scope.scope_key, run_token),
        daemon=True,
        name=f"enhanced-search-{scope.scope_key}",
    )
    with _SYNC_THREADS_LOCK:
        _SYNC_THREADS[scope.scope_key] = worker
    worker.start()


def _dispatch_scope_sync_task(
    scope_key: str,
    run_token: str,
    celery_config: EnhancedSearchCeleryConfig,
) -> None:
    # Import the plugin Celery app lazily so we publish on the enhanced-search
    # queue without recreating a module-load cycle. The broker connection is
    # created explicitly here because OMERO.web hosts multiple Celery apps in
    # the same long-lived web process.
    """Handle dispatch scope sync task."""
    from ..celery_app import app as enhanced_search_celery_app
    from kombu import Connection

    with Connection(celery_config.broker_url) as broker_connection:
        enhanced_search_celery_app.send_task(
            ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME,
            args=(scope_key, run_token),
            queue=celery_config.queue,
            connection=broker_connection,
        )


def request_scope_sync(
    scope_key: str,
    requested_by: str,
    *,
    scope_label: str | None = None,
) -> tuple[bool, str]:
    """Handle request scope sync."""
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
            _dispatch_scope_sync_task(scope.scope_key, run_token, celery_config)
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
