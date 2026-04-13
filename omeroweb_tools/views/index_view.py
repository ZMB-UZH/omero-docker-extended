from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from omeroweb.decorators import login_required

from ..services.enhanced_search_service import (
    SearchQuery,
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
)
from .utils import current_username, load_json_body, require_non_root_user


def _is_root_user(request, conn) -> bool:
    return str(current_username(request, conn) or "").strip() == "root"


@login_required()
def index(request, conn=None, url=None, **kwargs):
    return render(
        request,
        "omeroweb_tools/index.html",
        {"blocked_for_root": _is_root_user(request, conn)},
    )


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    return JsonResponse({"is_root_user": _is_root_user(request, conn)})


@login_required()
@ensure_csrf_cookie
def enhanced_search_view(request, conn=None, url=None, **kwargs):
    username = str(current_username(request, conn) or "")
    blocked_for_root = username == "root"
    settings_payload = (
        default_user_settings()
        if blocked_for_root
        else user_settings(username)
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
    sync_states = []
    auto_sync_started = False
    auto_sync_message = ""
    if not blocked_for_root:
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
            "search_payload": search_payload,
            "sync_states": sync_states,
            "auto_sync_started": auto_sync_started,
            "auto_sync_message": auto_sync_message,
            "user_settings": settings_payload,
        },
    )


@login_required()
@require_non_root_user
def start_scope_sync_view(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    _payload, error = load_json_body(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    username = str(current_username(request, conn) or "")
    settings_payload = user_settings(username)
    if not settings_payload.get("acquisition_metadata_enabled"):
        return JsonResponse(
            {
                "error": (
                    "Enable acquisition metadata indexing in Tools settings before "
                    "refreshing the acquisition index."
                )
            },
            status=409,
        )
    current_scope = current_user_scope(conn, username)
    if current_scope is None:
        return JsonResponse({"error": "Could not resolve the current OMERO user."}, status=400)
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
def sync_state_view(request, conn=None, url=None, **kwargs):
    username = str(current_username(request, conn) or "")
    sync_states, auto_sync_started, auto_sync_message = ensure_user_index_sync(
        conn,
        username,
        settings_payload=user_settings(username),
    )
    return JsonResponse(
        {
            "sync_states": sync_states,
            "auto_sync_started": auto_sync_started,
            "auto_sync_message": auto_sync_message,
        }
    )


@login_required()
@require_non_root_user
def save_user_settings_view(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_body(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    username = str(current_username(request, conn) or "")
    saved = save_user_settings(conn, username, payload or {})
    return JsonResponse({"ok": True, **saved})


@login_required()
@require_non_root_user
def save_query_view(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_body(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    query_name = str((payload or {}).get("query_name") or "").strip()
    query_payload = (payload or {}).get("query_payload")
    if not query_name:
        return JsonResponse({"error": "Query name is required."}, status=400)
    if not isinstance(query_payload, dict):
        return JsonResponse({"error": "Query payload is required."}, status=400)
    username = str(current_username(request, conn) or "")
    save_query(username, query_name, query_payload)
    return JsonResponse({"ok": True, "saved_queries": saved_queries(username)})


@login_required()
@require_non_root_user
def delete_query_view(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error = load_json_body(request)
    if error:
        return JsonResponse({"error": error}, status=400)
    try:
        query_id = int((payload or {}).get("query_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Query id is required."}, status=400)
    username = str(current_username(request, conn) or "")
    deleted = remove_saved_query(username, query_id)
    if not deleted:
        return JsonResponse({"error": "Saved query not found."}, status=404)
    return JsonResponse({"ok": True, "saved_queries": saved_queries(username)})


@login_required()
@require_non_root_user
def apply_saved_query_view(request, conn=None, url=None, query_id=None, **kwargs):
    username = str(current_username(request, conn) or "")
    for saved in saved_queries(username):
        if int(saved["id"]) != int(query_id):
            continue
        return redirect(saved_query_redirect_url(saved.get("query_payload") or {}))
    return redirect("omeroweb_tools_enhanced_search")
