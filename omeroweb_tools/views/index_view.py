from __future__ import annotations

import hashlib
from typing import Any

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from omeroweb.decorators import login_required

from ..services.enhanced_search_service import (
    SearchQuery,
    acquisition_index_status_message,
    current_user_scope,
    default_user_settings,
    ensure_user_index_sync,
    parse_search_query,
    request_scope_sync,
    runtime_config,
    save_user_settings,
    save_query,
    saved_queries,
    saved_query_redirect_url,
    search_scope_options,
    search,
    remove_saved_query,
    sync_states_for_user,
    user_settings,
    user_settings_load_error_message,
    user_settings_save_error_message,
)
from ..services.enhanced_search_store import EnhancedSearchStoreError
from .utils import current_username, load_json_object, require_non_root_user

__all__ = ["SearchQuery"]

SAVED_QUERY_NAME_MAX_LENGTH = 120
SAVED_QUERY_NAME_REQUIRED_ERROR = "Query name is required."
SAVED_QUERY_NAME_TOO_LONG_ERROR = (
    f"Query name must be {SAVED_QUERY_NAME_MAX_LENGTH} characters or fewer."
)
SAVED_QUERY_DELETE_ERROR = (
    "Could not delete saved search query. Database is not accessible."
)
SAVED_QUERY_LOAD_ERROR = (
    "Could not load saved search queries. Database is not accessible."
)
SAVED_QUERY_SAVE_ERROR = "Could not save search query. Database is not accessible."
SAVED_QUERY_PAYLOAD_REQUIRED_ERROR = "Query payload is required."
SAVED_QUERY_PAYLOAD_INVALID_ERROR = "Saved query payload is invalid."


def _indexed_scope_storage_key(username: str) -> str:
    digest = hashlib.sha256(str(username or "").strip().encode("utf-8")).hexdigest()
    return f"omeroweb_tools:enhanced_search:indexed_scope:{digest}"


def _is_root_user(request, conn) -> bool:
    return str(current_username(request, conn) or "").strip() == "root"


def _normalize_saved_query_name(value: object) -> str:
    return " ".join(str(value or "").split())


def _normalize_saved_query_payload(value: object) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        return {}, SAVED_QUERY_PAYLOAD_REQUIRED_ERROR
    query, errors = parse_search_query(value)
    if errors:
        return {}, SAVED_QUERY_PAYLOAD_INVALID_ERROR
    return query.with_page(1).to_payload(), ""


def _parse_saved_query_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError
    query_id = int(str(value).strip())
    if query_id < 1:
        raise ValueError
    return query_id


def _load_user_settings_context(
    username: str,
    *,
    blocked_for_root: bool,
) -> tuple[dict[str, Any], bool, str, str]:
    if blocked_for_root:
        payload = default_user_settings()
        return (
            payload,
            True,
            acquisition_index_status_message(
                bool(payload.get("acquisition_metadata_enabled"))
            ),
            "info",
        )
    try:
        payload = user_settings(username)
    except EnhancedSearchStoreError:
        payload = default_user_settings()
        return payload, False, user_settings_load_error_message(), "error"
    return (
        payload,
        True,
        acquisition_index_status_message(
            bool(payload.get("acquisition_metadata_enabled"))
        ),
        "info",
    )


@login_required()
def index(request, conn=None, _url=None, **kwargs):
    return render(
        request,
        "omeroweb_tools/index.html",
        {"blocked_for_root": _is_root_user(request, conn)},
    )


@login_required()
def root_status(request, conn=None, _url=None, **kwargs):
    return JsonResponse({"is_root_user": _is_root_user(request, conn)})


@login_required()
@ensure_csrf_cookie
def enhanced_search_view(request, conn=None, _url=None, **kwargs):
    username = str(current_username(request, conn) or "").strip()
    blocked_for_root = not username or username == "root"
    (
        settings_payload,
        settings_available,
        acquisition_index_status,
        acquisition_index_status_state,
    ) = _load_user_settings_context(
        username,
        blocked_for_root=blocked_for_root,
    )
    query, query_errors = parse_search_query(request.GET)
    search_payload = {
        "results": [],
        "page": max(1, query.page),
        "page_size": runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }
    sync_states: list[dict[str, Any]] = []
    auto_sync_started = False
    auto_sync_message = ""
    if not blocked_for_root and settings_available:
        sync_states, auto_sync_started, auto_sync_message = ensure_user_index_sync(
            conn,
            username,
            settings_payload=settings_payload,
        )
    if request.GET and not query_errors and not blocked_for_root:
        search_payload = search(
            conn,
            query,
            acquisition_metadata_enabled=bool(
                settings_payload.get("acquisition_metadata_enabled")
            ),
        )

    previous_page_querystring = ""
    next_page_querystring = ""
    if search_payload["has_previous"]:
        previous_page_querystring = query.to_querystring(page=max(1, query.page - 1))
    if search_payload["has_next"]:
        next_page_querystring = query.to_querystring(page=query.page + 1)

    collapsed_sections = settings_payload.get("collapsed_sections")
    if not isinstance(collapsed_sections, list):
        collapsed_sections = []

    return render(
        request,
        "omeroweb_tools/enhanced_search.html",
        {
            "blocked_for_root": blocked_for_root,
            "search_scope_options": search_scope_options(),
            "next_page_querystring": next_page_querystring,
            "previous_page_querystring": previous_page_querystring,
            "query": query,
            "query_errors": query_errors,
            "saved_queries": [] if blocked_for_root else saved_queries(username),
            "indexed_scope_storage_key": _indexed_scope_storage_key(username),
            "search_payload": search_payload,
            "sync_states": sync_states,
            "auto_sync_started": auto_sync_started,
            "auto_sync_message": auto_sync_message,
            "user_settings": settings_payload,
            "metadata_index_collapsed": "metadata-index" in collapsed_sections,
            "saved_queries_collapsed": "saved-queries" in collapsed_sections,
            "user_settings_available": settings_available,
            "acquisition_index_status": acquisition_index_status,
            "acquisition_index_status_state": acquisition_index_status_state,
            "acquisition_index_messages": {
                "enabled": acquisition_index_status_message(True),
                "disabled": acquisition_index_status_message(False),
                "load_error": user_settings_load_error_message(),
                "save_error": user_settings_save_error_message(),
            },
            "saved_query_name_max_length": SAVED_QUERY_NAME_MAX_LENGTH,
        },
    )


@login_required()
@require_non_root_user
def start_scope_sync_view(request, conn=None, _url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    _payload, error = load_json_object(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    username = str(current_username(request, conn) or "")
    try:
        settings_payload = user_settings(username)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": user_settings_load_error_message()}, status=503)
    if not settings_payload.get("acquisition_metadata_enabled"):
        return JsonResponse(
            {
                "error": (
                    "Enable universal metadata indexing in Tools settings before "
                    "refreshing the metadata index."
                )
            },
            status=409,
        )
    current_scope = current_user_scope(conn, username)
    if current_scope is None:
        return JsonResponse(
            {"error": "Could not resolve the current OMERO user."}, status=400
        )
    started, message = request_scope_sync(
        current_scope.scope_key,
        username,
        scope_label=current_scope.label,
    )
    return JsonResponse(
        {
            "ok": started,
            "message": message,
            "sync_states": sync_states_for_user(conn, username),
        },
        status=200 if started else 409,
    )


@login_required()
@require_non_root_user
def sync_state_view(request, conn=None, _url=None, **kwargs):
    username = str(current_username(request, conn) or "")
    try:
        settings_payload = user_settings(username)
        sync_states, auto_sync_started, auto_sync_message = ensure_user_index_sync(
            conn,
            username,
            settings_payload=settings_payload,
        )
    except EnhancedSearchStoreError:
        return JsonResponse({"error": user_settings_load_error_message()}, status=503)
    return JsonResponse(
        {
            "sync_states": sync_states,
            "auto_sync_started": auto_sync_started,
            "auto_sync_message": auto_sync_message,
        }
    )


@login_required()
@require_non_root_user
def save_user_settings_view(request, conn=None, _url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_object(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    username = str(current_username(request, conn) or "")
    try:
        saved = save_user_settings(conn, username, payload)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": user_settings_save_error_message()}, status=503)
    return JsonResponse({"ok": True, **saved})


@login_required()
@require_non_root_user
def save_query_view(request, conn=None, _url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_object(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    query_name = _normalize_saved_query_name(payload.get("query_name"))
    query_payload = payload.get("query_payload")
    if not query_name:
        return JsonResponse({"error": SAVED_QUERY_NAME_REQUIRED_ERROR}, status=400)
    if len(query_name) > SAVED_QUERY_NAME_MAX_LENGTH:
        return JsonResponse({"error": SAVED_QUERY_NAME_TOO_LONG_ERROR}, status=400)
    normalized_payload, payload_error = _normalize_saved_query_payload(query_payload)
    if payload_error:
        return JsonResponse({"error": payload_error}, status=400)
    username = str(current_username(request, conn) or "")
    try:
        save_query(username, query_name, normalized_payload)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": SAVED_QUERY_SAVE_ERROR}, status=503)
    try:
        updated_saved_queries = saved_queries(username)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": SAVED_QUERY_LOAD_ERROR}, status=503)
    return JsonResponse({"ok": True, "saved_queries": updated_saved_queries})


@login_required()
@require_non_root_user
def delete_query_view(request, conn=None, _url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_object(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    try:
        query_id = _parse_saved_query_id(payload.get("query_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Query id is required."}, status=400)
    username = str(current_username(request, conn) or "")
    try:
        deleted = remove_saved_query(username, query_id)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": SAVED_QUERY_DELETE_ERROR}, status=503)
    if not deleted:
        return JsonResponse({"error": "Saved query not found."}, status=404)
    try:
        updated_saved_queries = saved_queries(username)
    except EnhancedSearchStoreError:
        return JsonResponse({"error": SAVED_QUERY_LOAD_ERROR}, status=503)
    return JsonResponse({"ok": True, "saved_queries": updated_saved_queries})


@login_required()
@require_non_root_user
def apply_saved_query_view(request, conn=None, _url=None, query_id=None, **kwargs):
    username = str(current_username(request, conn) or "")
    try:
        user_saved_queries = saved_queries(username)
    except EnhancedSearchStoreError:
        user_saved_queries = []
    for saved in user_saved_queries:
        if int(saved["id"]) != int(query_id):
            continue
        return redirect(saved_query_redirect_url(saved.get("query_payload") or {}))
    return redirect("omeroweb_tools_enhanced_search")
