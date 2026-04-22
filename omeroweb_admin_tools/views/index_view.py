import json
import logging
import os
import re
import shutil
import socket
import traceback
import uuid
from csv import Error as CsvError
from html import escape
from http.cookies import SimpleCookie
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from urllib.parse import quote
from urllib.parse import urlparse
from urllib.parse import urlencode
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

import urllib.parse
import requests

from django.http import JsonResponse
from django.http import HttpResponse
from django.shortcuts import render
from django.template.backends.django import DjangoTemplates
from django.template.response import SimpleTemplateResponse
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from omeroweb.decorators import login_required
from omero_plugin_common import process_utils
from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitize_url_for_logging,
)

from ..config import optional_log_config
from ..services.log_query import (
    fetch_loki_logs,
    fetch_internal_log_labels,
    serialize_entries,
)
from ..services.system_diagnostics import run_diagnostic_script
from ..services.system_diagnostics import serialize_scripts
from ..services.storage_quotas import (
    QuotaError,
    get_state as get_quota_state,
    import_quotas_csv,
    is_quota_enforcement_available,
    quota_csv_template,
    reconcile_quotas,
    upsert_quotas,
)
from .utils import current_username, require_root_user

logger = logging.getLogger(__name__)
subprocess = process_utils
LOG_TABLE_ROW_CAP = 5000
_SAFE_REDIRECT_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROXY_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
_PROXY_PATH_SEGMENT_SAFE_CHARS = "-._~!$&'()*+,;=:@"
_GRAFANA_PROXY_METHODS = ("GET", "HEAD", "OPTIONS", "POST")
_INTERNAL_LOG_SERVICES = frozenset({"omeroserver_internal", "omeroweb_internal"})
_VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error", "fatal"})
_INLINE_TEMPLATE_BACKEND = DjangoTemplates(
    {
        "NAME": "inline_admin_tools",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {},
    }
)


def _proxy_method_not_allowed_response(
    allowed: tuple = _PROXY_SAFE_METHODS,
) -> JsonResponse:
    response = JsonResponse(
        {"error": "Method not allowed", "allowed_methods": list(allowed)},
        status=405,
    )
    response["Allow"] = ", ".join(allowed)
    return response


def _to_int_env(name: str, default: int) -> int:
    """Return an integer environment variable using the provided default on errors."""
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%s; using %d", name, raw_value, default)
        return default


def _validated_http_url(url: str, *, allow_query: bool = False) -> str:
    """Return a normalized HTTP(S) URL or raise ValueError."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid URL")
    if not allow_query and parsed.query:
        raise ValueError("Invalid URL")
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            parsed.query if allow_query else "",
            "",
        )
    )


def _internal_service_base_url(
    url_env_name: str,
    *,
    default_host: str,
    default_port: int,
    scheme_env_name: str = "ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME",
) -> str:
    configured_url = os.environ.get(url_env_name, "").strip()
    if configured_url:
        return configured_url

    scheme = str(os.environ.get(scheme_env_name, "http") or "http").strip().lower()
    if scheme not in {"http", "https"}:
        scheme = "http"

    return urllib.parse.urlunparse(
        (
            scheme,
            f"{default_host}:{int(default_port)}",
            "",
            "",
            "",
            "",
        )
    )


def _probe_http_url(url: str, timeout_seconds: float = 2.5) -> Dict[str, object]:
    """Probe an HTTP endpoint and return availability diagnostics."""
    try:
        response = requests.get(
            _validated_http_url(url),
            timeout=timeout_seconds,
            allow_redirects=True,
        )
        status_code = int(response.status_code)
        return {"ok": 200 <= status_code < 400, "status": status_code, "error": ""}
    except (ValueError, requests.RequestException) as exc:
        logger.warning(
            "HTTP probe failed for %s: %s",
            sanitize_url_for_logging(url),
            sanitize_log_value(exc),
        )
        return {"ok": False, "status": 0, "error": "Connection failed"}


def _normalize_proxy_prefix(proxy_prefix: str) -> str:
    stripped = str(proxy_prefix or "").strip().strip("/")
    return f"/{stripped}" if stripped else ""


def _safe_redirect_segment(value: str, default: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return default
    if raw_value.startswith(("http://", "https://")):
        return default
    if "/" in raw_value or "\\" in raw_value or ".." in raw_value or ":" in raw_value:
        return default
    cleaned = _SAFE_REDIRECT_SEGMENT_RE.sub("-", raw_value).strip(".-")
    return cleaned or default


def _safe_dashboard_uid(value: str, default: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return default
    if raw_value.startswith(("http://", "https://")):
        return default
    last_segment = raw_value.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _SAFE_REDIRECT_SEGMENT_RE.sub("-", last_segment).strip(".-")
    return cleaned or default


def _normalize_proxy_request_target(subpath: str) -> Tuple[str, str]:
    raw_target = str(subpath or "").strip()
    parsed_target = urllib.parse.urlsplit(raw_target)
    if parsed_target.scheme or parsed_target.netloc:
        raise ValueError("Invalid proxy target")
    if parsed_target.query or parsed_target.fragment:
        raise ValueError("Invalid proxy target")
    decoded = urllib.parse.unquote(parsed_target.path or "")
    if "\x00" in decoded:
        raise ValueError("Invalid proxy target")
    segments: list[str] = []
    for segment in decoded.split("/"):
        if not segment or segment == ".":
            continue
        if segment == "..":
            if not segments:
                raise ValueError("Invalid proxy target")
            segments.pop()
            continue
        segments.append(
            urllib.parse.quote(segment, safe=_PROXY_PATH_SEGMENT_SAFE_CHARS)
        )
    return "/".join(segments), ""


def _normalize_proxy_query_string(query: str) -> str:
    normalized_query = str(query or "").lstrip("?")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized_query):
        raise ValueError("Invalid proxy query")
    return normalized_query


def _build_proxy_target_url(base_url: str, path: str, query: str) -> tuple[str, str]:
    normalized_path, _ignored_query = _normalize_proxy_request_target(path)
    base_parsed = urllib.parse.urlparse(_validated_http_url(base_url))
    if not base_parsed.hostname:
        raise ValueError("Invalid proxy backend")
    _ = base_parsed.port
    normalized_query = _normalize_proxy_query_string(query)
    safe_path = base_parsed.path.rstrip("/")
    if normalized_path:
        safe_path = f"{safe_path}/{normalized_path}"
    else:
        safe_path = f"{safe_path}/"
    target_url = urllib.parse.urlunparse(
        (
            base_parsed.scheme,
            base_parsed.netloc,
            safe_path,
            "",
            normalized_query,
            "",
        )
    )
    target_parsed = urllib.parse.urlparse(target_url)
    if (
        target_parsed.scheme != base_parsed.scheme
        or target_parsed.netloc != base_parsed.netloc
        or target_parsed.username
        or target_parsed.password
        or target_parsed.fragment
    ):
        raise ValueError("Invalid proxy target")
    return normalized_path, target_url


def _build_proxy_request_target(target_url: str) -> str:
    target_parsed = urllib.parse.urlparse(target_url)
    request_target = urllib.parse.urlunparse(
        (
            "",
            "",
            target_parsed.path or "/",
            "",
            target_parsed.query,
            "",
        )
    )
    if not request_target.startswith("/") or any(
        ord(char) < 32 or ord(char) == 127 for char in request_target
    ):
        raise ValueError("Invalid proxy target")
    return request_target


def _collect_proxy_headers(
    django_request,
    extra_forwarded_headers: tuple,
) -> dict[str, str]:
    forwarded_headers: dict[str, str] = {}
    for header_name in (
        "Accept",
        "Content-Type",
        "User-Agent",
        "Authorization",
        "Cookie",
        "Origin",
        "Referer",
        *extra_forwarded_headers,
    ):
        value = django_request.headers.get(header_name)
        if value:
            forwarded_headers[header_name] = value
    return forwarded_headers


def _rewrite_origin_headers(headers: dict[str, str], base_url: str) -> None:
    backend_origin = _origin_from_url(base_url)
    if not backend_origin:
        return
    if headers.get("Origin"):
        headers["Origin"] = backend_origin
    if headers.get("Referer"):
        headers["Referer"] = f"{backend_origin}/"


def _proxy_request_body(django_request) -> bytes | None:
    if django_request.method not in {"POST", "PUT", "PATCH"}:
        return None
    return django_request.body


class _ProxyBackendResponse:
    def __init__(self, raw_response, connection) -> None:
        self.status_code = int(raw_response.status)
        self.headers = getattr(raw_response, "headers", None) or raw_response.msg
        self._connection = connection
        self._raw_response = raw_response
        self._content: bytes | None = None

    @property
    def content(self) -> bytes:
        if self._content is None:
            self._content = self._raw_response.read()
        return self._content

    def close(self) -> None:
        self._connection.close()


def _send_proxy_backend_request(
    *,
    base_url: str,
    method: str,
    request_target: str,
    data: bytes | None,
    headers: dict[str, str],
    timeout_seconds: float,
) -> _ProxyBackendResponse:
    base_parsed = urllib.parse.urlparse(_validated_http_url(base_url))
    hostname = base_parsed.hostname
    if not hostname:
        raise ValueError("Invalid proxy backend")
    port = base_parsed.port
    if port is None:
        port = 443 if base_parsed.scheme == "https" else 80

    connection_class = (
        HTTPSConnection if base_parsed.scheme == "https" else HTTPConnection
    )
    connection = connection_class(hostname, port=port, timeout=timeout_seconds)
    try:
        connection.request(
            method,
            request_target,
            body=data,
            headers=headers,
        )
        return _ProxyBackendResponse(connection.getresponse(), connection)
    except Exception:
        connection.close()
        raise


def _unsupported_event_stream_response(
    normalized_path: str,
    content_type: str,
    target_url: str,
) -> HttpResponse | None:
    if normalized_path != "api/v1/notifications/live":
        return None
    if not content_type.startswith("text/event-stream"):
        return None
    logger.info(
        "Proxy suppressed unsupported event stream target=%s",
        sanitize_url_for_logging(target_url),
    )
    suppressed = HttpResponse(status=204)
    suppressed["Cache-Control"] = "no-store"
    return suppressed


def _proxy_http_request(
    django_request,
    base_url: str,
    path: str,
    query: str = "",
    *,
    proxy_prefix: str = "",
    rewrite_origin_headers: bool = False,
    extra_forwarded_headers: tuple = (),
) -> HttpResponse:
    """Proxy an HTTP request to a backend URL and return the response body."""
    try:
        normalized_path, target_url = _build_proxy_target_url(base_url, path, query)
        request_target = _build_proxy_request_target(target_url)
    except ValueError:
        return JsonResponse({"error": "Invalid URL format"}, status=400)

    forwarded_headers = _collect_proxy_headers(django_request, extra_forwarded_headers)
    if rewrite_origin_headers:
        _rewrite_origin_headers(forwarded_headers, base_url)

    response = None
    try:
        response = _send_proxy_backend_request(
            base_url=base_url,
            method=django_request.method,
            request_target=request_target,
            data=_proxy_request_body(django_request),
            headers=forwarded_headers,
            timeout_seconds=10.0,
        )
        headers = response.headers
        content_type = str(response.headers.get("Content-Type", "") or "").lower()
        suppressed = _unsupported_event_stream_response(
            normalized_path,
            content_type,
            target_url,
        )
        if suppressed is not None:
            return suppressed
        return _build_proxied_response(
            response.content,
            status_code=int(response.status_code),
            headers=headers,
            base_url=base_url,
            proxy_prefix=proxy_prefix,
        )
    except (requests.Timeout, TimeoutError) as exc:
        logger.warning(
            "Proxy backend timed out target=%s reason=%s",
            sanitize_url_for_logging(target_url),
            sanitize_log_value(str(exc) or exc.__class__.__name__),
        )
        return JsonResponse(
            {"error": "Backend timed out."},
            status=504,
        )
    except (requests.RequestException, HTTPException, OSError) as exc:
        logger.warning(
            "Proxy backend unreachable target=%s reason=%s",
            sanitize_url_for_logging(target_url),
            sanitize_log_value(exc),
        )
        return JsonResponse(
            {"error": "Backend unreachable."},
            status=502,
        )
    finally:
        if response is not None:
            response.close()


def _header_first(headers, name: str, default: str = "") -> str:
    value = None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name, default)
    if value in (None, ""):
        value = default
    return str(value or default)


def _header_values(headers, name: str) -> List[str]:
    for attr in ("get_all", "getlist"):
        getter = getattr(headers, attr, None)
        if callable(getter):
            values = getter(name)
            if values:
                return [str(value) for value in values if value]
    value = _header_first(headers, name, "")
    return [value] if value else []


def _build_proxied_response(
    payload: bytes,
    *,
    status_code: int,
    headers,
    base_url: str,
    proxy_prefix: str,
) -> HttpResponse:
    """Build a Django response from backend payload and headers."""
    content_type = _header_first(headers, "Content-Type", "application/octet-stream")
    if "text/html" in content_type and proxy_prefix:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = payload.decode("latin-1", errors="ignore")
        text = text.replace('href="/', f'href="{proxy_prefix}/')
        text = text.replace("href='/", f"href='{proxy_prefix}/")
        text = text.replace('src="/', f'src="{proxy_prefix}/')
        text = text.replace("src='/", f"src='{proxy_prefix}/")
        text = text.replace('action="/', f'action="{proxy_prefix}/')
        text = text.replace("action='/", f"action='{proxy_prefix}/")
        text = text.replace('href="login"', f'href="{proxy_prefix}/login"')
        text = text.replace("href='login'", f"href='{proxy_prefix}/login'")
        text = text.replace(base_url.rstrip("/"), proxy_prefix)

        escaped_prefix = proxy_prefix.replace('"', r"\"")
        escaped_app_url = f"{escaped_prefix}/" if escaped_prefix else "/"
        text = re.sub(
            r'"appSubUrl"\s*:\s*"[^"]*"',
            f'"appSubUrl":"{escaped_prefix}"',
            text,
        )
        text = re.sub(
            r'"appUrl"\s*:\s*"[^"]*"',
            f'"appUrl":"{escaped_app_url}"',
            text,
        )

        payload = text.encode("utf-8")
    proxied = HttpResponse(payload, status=status_code, content_type=content_type)
    for header_name in ("Cache-Control", "ETag", "Last-Modified"):
        header_value = _header_first(headers, header_name, "")
        if header_value:
            proxied[header_name] = header_value
    _copy_set_cookie_headers(headers, proxied, proxy_prefix)
    location = _header_first(headers, "Location", "")
    if location:
        proxied["Location"] = _rewrite_proxied_location(
            location, base_url, proxy_prefix
        )
    return proxied


def _cookie_path_for_proxy(original_path: str, proxy_prefix: str) -> str:
    """Return cookie path rewritten to stay within the Django proxy route."""
    normalized_prefix = str(proxy_prefix or "").rstrip("/")
    normalized_path = str(original_path or "/")

    if not normalized_prefix:
        return normalized_path
    if normalized_path == "/":
        return f"{normalized_prefix}/"
    if normalized_path.startswith("/"):
        return f"{normalized_prefix}{normalized_path}"
    return normalized_path


def _origin_from_url(url: str) -> str:
    """Return normalized origin (scheme://host[:port]) for a URL string."""
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _rewrite_proxied_location(location: str, base_url: str, proxy_prefix: str) -> str:
    normalized_prefix = _normalize_proxy_prefix(proxy_prefix)
    parsed_location = urlparse(str(location or ""))
    parsed_base = urlparse(base_url.rstrip("/"))

    if (
        parsed_location.scheme
        and parsed_location.netloc
        and (
            parsed_location.scheme != parsed_base.scheme
            or parsed_location.netloc != parsed_base.netloc
        )
    ):
        return f"{normalized_prefix}/" if normalized_prefix else "/"
    if location.startswith(base_url.rstrip("/")):
        return location.replace(base_url.rstrip("/"), normalized_prefix, 1)
    if location.startswith("/"):
        return f"{normalized_prefix}{location}" if normalized_prefix else location
    if not parsed_location.scheme:
        return (
            f"{normalized_prefix}/{location.lstrip('/')}"
            if normalized_prefix
            else f"/{location.lstrip('/')}"
        )
    return location


def _copy_set_cookie_headers(
    backend_headers,
    response: HttpResponse,
    proxy_prefix: str,
) -> None:
    """Copy backend Set-Cookie headers and rewrite path for proxied requests."""
    raw_set_cookie_headers = _header_values(backend_headers, "Set-Cookie")
    for raw_cookie in raw_set_cookie_headers:
        parsed_cookie = SimpleCookie()
        parsed_cookie.load(raw_cookie)
        for morsel in parsed_cookie.values():
            max_age: Optional[int] = None
            if morsel["max-age"]:
                try:
                    max_age = int(morsel["max-age"])
                except ValueError:
                    logger.warning(
                        "Skipping invalid cookie max-age: %s", morsel["max-age"]
                    )
            response.set_cookie(
                morsel.key,
                morsel.value,
                max_age=max_age,
                expires=morsel["expires"] or None,
                path=_cookie_path_for_proxy(morsel["path"] or "/", proxy_prefix),
                domain=morsel["domain"] or None,
                secure=bool(morsel["secure"]),
                httponly=bool(morsel["httponly"]),
                samesite=morsel["samesite"] or None,
            )


def _build_proxy_backend_urls(internal_url: str, public_url: str) -> List[str]:
    """Return ordered backend URLs used by proxy routes.

    Internal URL is always preferred. If a public URL is configured it is used as
    a fallback, which allows deployments where internal service DNS is
    unavailable from the OMERO.web container.
    """
    urls: List[str] = []
    for candidate in (internal_url, public_url):
        normalized = str(candidate or "").strip().rstrip("/")
        if not normalized or normalized in urls:
            continue
        urls.append(normalized)
    return urls


def _grafana_proxy_home_fallback_response(proxy_prefix: str) -> HttpResponse:
    """Redirect Grafana root requests to the configured default dashboard."""
    normalized_prefix = _normalize_proxy_prefix(proxy_prefix)
    dashboard_uid = _safe_dashboard_uid(
        os.environ.get(
            "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "omero-infrastructure"
        ).strip(),
        "omero-infrastructure",
    )
    dashboard_slug = _safe_redirect_segment(
        os.environ.get(
            "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server-infrastructure"
        ).strip(),
        "server-infrastructure",
    )
    dashboard_path = f"{normalized_prefix}/d/{quote(dashboard_uid, safe='')}/{quote(dashboard_slug, safe='')}"

    response = HttpResponse(status=302)
    response["Location"] = dashboard_path
    return response


def _grafana_unavailable_response(
    *,
    proxy_prefix: str,
    attempted_backends: List[str],
    status_code: int,
) -> HttpResponse:
    """Render a concise Grafana outage page for proxied dashboard requests."""
    refreshed_path = str(proxy_prefix or "").rstrip("/") + "/"
    attempted_targets = ", ".join(
        escape(urlparse(url).netloc or url) for url in attempted_backends
    )
    if not attempted_targets:
        attempted_targets = "configured Grafana endpoints"

    template = _INLINE_TEMPLATE_BACKEND.from_string(
        """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Grafana temporarily unavailable</title>
    <style>
      body {
        margin: 0;
        padding: 24px;
        background: #0b1020;
        color: #e5e7eb;
        font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      }
      .panel {
        max-width: 880px;
        margin: 24px auto;
        border: 1px solid #334155;
        border-radius: 12px;
        background: #111827;
        padding: 24px;
      }
      h1 { margin: 0 0 8px; font-size: 1.5rem; }
      p { margin: 0 0 12px; line-height: 1.5; }
      code { background: #0f172a; border-radius: 4px; padding: 2px 6px; }
      .actions { margin-top: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
      .btn {
        text-decoration: none;
        color: #111827;
        background: #38bdf8;
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 600;
      }
      .btn.secondary { background: #374151; color: #f9fafb; }
    </style>
  </head>
  <body>
    <div class="panel">
      <h1>Grafana is temporarily unavailable</h1>
      <p>The monitoring dashboard cannot be loaded right now because Grafana is not reachable from OMERO.web.</p>
      <p><strong>Upstream status:</strong> <code>{{ status_code }}</code></p>
      <p><strong>Checked endpoints:</strong> <code>{{ attempted_targets }}</code></p>
      <p>Recommended checks: ensure the Grafana container is running and healthy, then retry.</p>
      <div class="actions">
        <a class="btn" href="{{ refreshed_path }}">Retry dashboard</a>
        <a class="btn secondary" href="javascript:window.history.back()">Back</a>
      </div>
    </div>
  </body>
</html>"""
    )
    response = SimpleTemplateResponse(
        template,
        {
            "status_code": status_code,
            "attempted_targets": attempted_targets,
            "refreshed_path": refreshed_path,
        },
        status=503,
    )
    response["Cache-Control"] = "no-store"
    response["Retry-After"] = "30"
    return response.render()


def _is_internal_hostname(hostname: str) -> bool:
    """Return whether hostname points to a local/container-only endpoint."""
    lowered = str(hostname or "").strip().lower()
    return lowered in {"", "localhost", "127.0.0.1", "::1", "grafana", "prometheus"}


def _is_behind_reverse_proxy(request) -> bool:
    """Return True when the request arrived through a reverse proxy."""
    return bool(
        (request.META.get("HTTP_X_FORWARDED_PROTO") or "").strip()
        or (request.META.get("HTTP_X_FORWARDED_HOST") or "").strip()
        or (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    )


def _safe_request_host(request) -> str:
    """Return request host without port, falling back safely when host validation fails."""
    try:
        host_value = request.get_host()
    except Exception as exc:
        logger.warning("Unable to resolve request host from get_host(): %s", exc)
        host_value = (
            request.META.get("HTTP_HOST", "")
            or request.META.get("SERVER_NAME", "")
            or "localhost"
        )
    return str(host_value).split(":", 1)[0].strip() or "localhost"


def _build_public_service_url(
    internal_url: str,
    request_scheme: str,
    request_host: str,
    public_port: int,
    *,
    is_proxied: bool = False,
    forwarded_proto: str = "",
) -> str:
    """Build externally reachable service URL from request host and configured public port.

    *is_proxied*: when True the port is omitted — the reverse proxy routes to
    the correct backend on a standard port (443/80).

    *forwarded_proto*: when non-empty, overrides the scheme so URLs use ``https``
    when the client connected over TLS to a reverse proxy.
    """
    parsed = urlparse(internal_url)
    if forwarded_proto:
        scheme = forwarded_proto
    elif is_proxied:
        scheme = request_scheme
    else:
        scheme = parsed.scheme or request_scheme
    base_path = parsed.path.rstrip("/")
    host_only = str(request_host or "").strip()
    if host_only.startswith("[") and "]" in host_only:
        normalized_host = host_only
    elif ":" in host_only:
        normalized_host = f"[{host_only}]"
    else:
        normalized_host = host_only

    if is_proxied:
        public_base = f"{scheme}://{normalized_host}"
    else:
        public_base = f"{scheme}://{normalized_host}:{public_port}"

    if base_path:
        return f"{public_base}{base_path}"
    return public_base


def _unwrap_rtype_value(value, default=None):
    """Extract primitive values from OMERO rtypes and similar wrappers."""
    if value is None:
        return default
    if hasattr(value, "val"):
        return value.val
    if hasattr(value, "getValue"):
        return value.getValue()
    return value


def _safe_full_name(user_obj) -> str:
    """Return "First Last" for an OMERO experimenter-like object."""
    first_name = ""
    last_name = ""
    for getter_name, field_name in (
        ("getFirstName", "firstName"),
        ("getLastName", "lastName"),
    ):
        raw_value = None
        if hasattr(user_obj, getter_name):
            raw_value = _unwrap_rtype_value(getattr(user_obj, getter_name)(), "")
        elif hasattr(user_obj, field_name):
            raw_value = _unwrap_rtype_value(getattr(user_obj, field_name), "")
        if getter_name == "getFirstName":
            first_name = str(raw_value or "").strip()
        else:
            last_name = str(raw_value or "").strip()
    return " ".join(part for part in (first_name, last_name) if part)


def _safe_username(user_obj) -> str:
    """Return username for an OMERO experimenter-like object."""
    if hasattr(user_obj, "getOmeName"):
        return str(_unwrap_rtype_value(user_obj.getOmeName(), "") or "").strip()
    if hasattr(user_obj, "omeName"):
        return str(_unwrap_rtype_value(user_obj.omeName, "") or "").strip()
    return ""


def _safe_group_name(group_obj) -> str:
    """Return name for an OMERO group-like object."""
    if hasattr(group_obj, "getName"):
        return str(_unwrap_rtype_value(group_obj.getName(), "") or "").strip()
    if hasattr(group_obj, "name"):
        return str(_unwrap_rtype_value(group_obj.name, "") or "").strip()
    return ""


def _call_admin_listing(admin_service, method_name, arg_options=None):
    """Call admin-service listing methods with tolerant signatures."""
    if not hasattr(admin_service, method_name):
        return []
    method = getattr(admin_service, method_name)
    argument_options = arg_options or ((), (None,), (False,))
    for args in argument_options:
        try:
            result = method(*args)
            return list(result or [])
        except TypeError:
            continue
    return []


def _safe_object_id(obj):
    """Extract numeric ID for OMERO model-like objects."""
    if obj is None:
        return None
    if hasattr(obj, "getId"):
        value = _unwrap_rtype_value(obj.getId(), None)
    elif hasattr(obj, "id"):
        value = _unwrap_rtype_value(obj.id, None)
    else:
        value = None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _list_omero_group_names(conn) -> List[str]:
    """Return sorted list of OMERO group names from admin service."""
    if conn is None:
        return []
    try:
        admin_service = conn.getAdminService()
        groups = []
        for method_name in ("lookupGroups", "containedGroups"):
            groups = _call_admin_listing(admin_service, method_name)
            if groups:
                break
        return sorted(name for g in groups if (name := _safe_group_name(g)))
    except Exception:
        logger.debug("Could not list OMERO groups for quota reconciliation")
        return []


def _first_admin_listing(admin_service, method_names: tuple[str, ...]) -> list:
    for method_name in method_names:
        objects = _call_admin_listing(admin_service, method_name)
        if objects:
            return objects
    return []


def _register_admin_users(
    experimenters: list,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    users: dict[str, str] = {}
    groups_by_user: dict[str, set[str]] = {}
    for user in experimenters:
        username = _safe_username(user)
        if username:
            users[username] = _safe_full_name(user)
            groups_by_user.setdefault(username, set())
    return users, groups_by_user


def _register_admin_groups(
    experimenter_groups: list,
) -> tuple[set[str], dict[str, str], dict[str, set[str]]]:
    groups: set[str] = set()
    group_permissions: dict[str, str] = {}
    users_by_group: dict[str, set[str]] = {}
    for group in experimenter_groups:
        group_name = _safe_group_name(group)
        if group_name:
            groups.add(group_name)
            group_permissions[group_name] = _safe_group_permission_label(group)
            users_by_group.setdefault(group_name, set())
    return groups, group_permissions, users_by_group


def _admin_id_arg_options(object_id: int) -> tuple[tuple[object, ...], ...]:
    return ((object_id,), (int(object_id),), (object_id, False), (object_id, None))


def _link_user_group_memberships(
    admin_service,
    experimenters: list,
    groups: set[str],
    group_permissions: dict[str, str],
    groups_by_user: dict[str, set[str]],
    users_by_group: dict[str, set[str]],
) -> None:
    for user in experimenters:
        user_id = _safe_object_id(user)
        username = _safe_username(user)
        if user_id is None or not username:
            continue
        user_groups = _call_admin_listing(
            admin_service,
            "containedGroups",
            arg_options=_admin_id_arg_options(user_id),
        )
        for group in user_groups:
            group_name = _safe_group_name(group)
            if group_name:
                groups.add(group_name)
                groups_by_user.setdefault(username, set()).add(group_name)
                users_by_group.setdefault(group_name, set()).add(username)
                group_permissions.setdefault(
                    group_name, _safe_group_permission_label(group)
                )


def _link_group_user_memberships(
    admin_service,
    experimenter_groups: list,
    users: dict[str, str],
    groups_by_user: dict[str, set[str]],
    users_by_group: dict[str, set[str]],
) -> None:
    for group in experimenter_groups:
        group_id = _safe_object_id(group)
        group_name = _safe_group_name(group)
        if group_id is None or not group_name:
            continue
        group_users = _call_admin_listing(
            admin_service,
            "containedExperimenters",
            arg_options=_admin_id_arg_options(group_id),
        )
        for user in group_users:
            username = _safe_username(user)
            if username:
                users.setdefault(username, _safe_full_name(user))
                groups_by_user.setdefault(username, set()).add(group_name)
                users_by_group.setdefault(group_name, set()).add(username)


def _list_all_users_and_groups(conn):
    """Collect all OMERO users and groups to keep zero-usage rows visible."""
    users: dict[str, str] = {}
    groups: set[str] = set()
    group_permissions: dict[str, str] = {}
    groups_by_user: dict[str, set[str]] = {}
    users_by_group: dict[str, set[str]] = {}
    try:
        admin_service = conn.getAdminService()
        experimenters = _first_admin_listing(
            admin_service,
            ("lookupExperimenters", "containedExperimenters"),
        )
        experimenter_groups = _first_admin_listing(
            admin_service,
            ("lookupGroups", "containedGroups"),
        )
        users, groups_by_user = _register_admin_users(experimenters)
        groups, group_permissions, users_by_group = _register_admin_groups(
            experimenter_groups
        )
        _link_user_group_memberships(
            admin_service,
            experimenters,
            groups,
            group_permissions,
            groups_by_user,
            users_by_group,
        )
        _link_group_user_memberships(
            admin_service,
            experimenter_groups,
            users,
            groups_by_user,
            users_by_group,
        )
    except Exception:
        logger.exception(
            "Failed to enumerate all users/groups from OMERO admin service"
        )
    return users, groups, group_permissions, groups_by_user, users_by_group


def _permission_flag(permission_obj, method_name: str) -> bool:
    """Safely read a bool-like permission method from OMERO permissions."""
    if permission_obj is None:
        return False
    method = getattr(permission_obj, method_name, None)
    if not callable(method):
        return False
    try:
        return bool(method())
    except Exception:
        return False


def _safe_group_permission_object(group_obj):
    try:
        details = group_obj.getDetails()
        return details.getPermissions() if details is not None else None
    except Exception:
        return None


def _permission_label_from_flags(permission_obj) -> str:
    group_read = _permission_flag(permission_obj, "isGroupRead")
    group_write = _permission_flag(permission_obj, "isGroupWrite")
    group_annotate = _permission_flag(permission_obj, "isGroupAnnotate")
    if group_read and group_write:
        return "Read-write"
    if group_read and group_annotate:
        return "Read-annotate"
    if group_read:
        return "Read-only"
    return ""


def _permission_label_from_text(permission_obj) -> str:
    permission_text = str(permission_obj or "").strip().lower()
    labels = (
        ("Read-write", ("read-write", "rwrw")),
        ("Read-annotate", ("read-annotate", "rwra")),
        ("Read-only", ("read-only",)),
        ("Private", ("private",)),
    )
    for label, markers in labels:
        if any(marker in permission_text for marker in markers):
            return label
    return "Private"


def _safe_group_permission_label(group_obj) -> str:
    """Return a stable group permission name for the storage group view."""
    permission_obj = _safe_group_permission_object(group_obj)
    return _permission_label_from_flags(permission_obj) or _permission_label_from_text(
        permission_obj
    )


def _require_root_user(request, conn):
    username = current_username(request, conn)
    if username != "root":
        return JsonResponse(
            {"error": "Only root user can access admin tools data."}, status=403
        )
    return None


@login_required()
def index(request, _conn=None, _url=None, **kwargs):
    """Render the Admin tools landing page."""
    return render(
        request,
        "omeroweb_admin_tools/index.html",
        {},
    )


def _build_log_sources() -> List[Dict[str, str]]:
    """Return ordered Docker log sources for the UI."""
    return [
        {
            "key": "omeroserver",
            "label": "OMERO.server",
            "container": "omeroserver",
        },
        {
            "key": "omeroweb",
            "label": "OMERO.web",
            "container": "omeroweb",
        },
        {
            "key": "database",
            "label": "OMERO database",
            "container": "database",
        },
        {
            "key": "database_plugin",
            "label": "Plugin database",
            "container": "database_plugin",
        },
        {
            "key": "redis",
            "label": "Redis",
            "container": "redis",
        },
    ]


def _parse_since_ns(raw_value: str) -> int:
    """Parse a `since` query value into epoch nanoseconds."""
    value = raw_value.strip()
    if not value:
        raise ValueError("empty since value")
    if value.isdigit():
        return int(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp() * 1e9)


@login_required()
@require_root_user
def logs_view(request, _conn=None, _url=None, **kwargs):
    """Render the logs view."""
    log_config = optional_log_config()
    return render(
        request,
        "omeroweb_admin_tools/logs.html",
        {
            "log_config": json.dumps(asdict(log_config)) if log_config else "null",
            "log_sources": _build_log_sources(),
            "table_row_cap": LOG_TABLE_ROW_CAP,
        },
    )


def _parse_log_limits(request, log_config) -> tuple[int, int]:
    lookback_seconds = int(request.GET.get("lookback", log_config.lookback_seconds))
    max_entries = int(request.GET.get("limit", log_config.max_entries))
    return lookback_seconds, max_entries


def _parse_optional_since_ns(request) -> int | None:
    since_raw = request.GET.get("since", "").strip()
    if not since_raw:
        return None
    return _parse_since_ns(since_raw)


def _internal_log_files_from_query(values: list[str]) -> dict[str, set[str]]:
    internal_files: dict[str, set[str]] = {}
    for value in values:
        if not value or "/" not in value:
            continue
        service, filename = value.split("/", 1)
        if service in _INTERNAL_LOG_SERVICES and filename:
            internal_files.setdefault(service, set()).add(filename)
    return internal_files


def _filter_log_entries(entries, *, level: str, query: str):
    filtered_entries = entries
    if level:
        filtered_entries = [entry for entry in filtered_entries if entry.level == level]
    if not query:
        return filtered_entries
    needle = query.lower()
    return [
        entry
        for entry in filtered_entries
        if needle in entry.message.lower()
        or needle in entry.container.lower()
        or needle in entry.level.lower()
    ]


@login_required()
@require_root_user
def logs_data(request, conn=None, _url=None, **kwargs):
    """Serve log entries as JSON from the Loki backend."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    log_config = optional_log_config()
    if log_config is None:
        return JsonResponse(
            {"error": "ADMIN_TOOLS_LOKI_URL is not configured."},
            status=503,
        )
    containers = request.GET.getlist("container")
    internal_files_raw = request.GET.getlist("internal_file")
    if not containers:
        return JsonResponse({"entries": []})
    try:
        lookback_seconds, max_entries = _parse_log_limits(request, log_config)
    except ValueError:
        return JsonResponse({"error": "Invalid lookback or limit value."}, status=400)
    query = request.GET.get("query", "").strip()
    level = request.GET.get("level", "").strip().lower()
    text_query = query if len(query) >= 2 else None
    try:
        since_ns = _parse_optional_since_ns(request)
    except ValueError:
        return JsonResponse({"error": "Invalid since value."}, status=400)
    if level and level not in _VALID_LOG_LEVELS:
        return JsonResponse({"error": "Invalid log level."}, status=400)
    try:
        internal_files = _internal_log_files_from_query(internal_files_raw)
        entries = fetch_loki_logs(
            log_config,
            containers,
            lookback_seconds,
            max_entries,
            internal_files=internal_files,
            since_ns=since_ns,
            text_query=text_query,
        )
    except RuntimeError as exc:  # pragma: no cover - network errors
        logger.warning("Failed to fetch logs from Loki: %s", exc)
        return JsonResponse(
            {"error": "Failed to fetch logs."},
            status=502,
        )
    entries = _filter_log_entries(entries, level=level, query=query)
    return JsonResponse({"entries": serialize_entries(entries)})


@login_required()
def root_status(request, conn=None, _url=None, **kwargs):
    """Return whether the current user is root."""
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
@require_root_user
def internal_log_labels(request, conn=None, _url=None, **kwargs):
    """Return available filenames for an internal log compose_service."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    log_config = optional_log_config()
    if log_config is None:
        return JsonResponse(
            {"error": "ADMIN_TOOLS_LOKI_URL is not configured."},
            status=503,
        )
    service = request.GET.get("service", "")
    if service not in ("omeroserver_internal", "omeroweb_internal"):
        return JsonResponse(
            {"error": "Invalid service parameter."},
            status=400,
        )
    try:
        labels, _label_key = fetch_internal_log_labels(log_config, service)
    except Exception:
        logger.exception("Failed to fetch internal log labels for service=%s", service)
        labels = []
    return JsonResponse({"service": service, "labels": labels})


def _load_compose_service_names(compose_file: str = "docker-compose.yml") -> List[str]:
    """Return declared Docker Compose service names from the local compose file."""
    if os.path.isabs(compose_file):
        compose_path = compose_file
    else:
        compose_path = os.path.join(_REPO_ROOT, compose_file)
    if not os.path.exists(compose_path):
        logger.warning("Compose file not found at %s", compose_path)
        return []

    service_names: List[str] = []
    in_services = False
    service_pattern = re.compile(r"^  ([a-zA-Z0-9_-]+):\s*$")

    with open(compose_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith("services:"):
                in_services = True
                continue
            if in_services and line and not line.startswith(" "):
                break
            if not in_services:
                continue
            match = service_pattern.match(line)
            if match:
                service_names.append(match.group(1))

    return service_names


def _prometheus_instant_query(prometheus_base_url: str, expr: str) -> Optional[float]:
    """Execute a Prometheus instant query and return the first numeric value."""
    response = requests.get(
        f"{_validated_http_url(prometheus_base_url).rstrip('/')}/api/v1/query",
        params={"query": expr},
        timeout=5.0,
    )
    payload = response.json()
    results = payload.get("data", {}).get("result", [])
    if not results:
        return None
    value = results[0].get("value", [])
    if len(value) < 2:
        return None
    return float(value[1])


def _collect_system_metrics(prometheus_base_url: str) -> Dict[str, Optional[float]]:
    """Collect a compact set of host-level metrics for admin overview cards."""
    metrics: Dict[str, Optional[float]] = {
        "cpu_usage_percent": None,
        "memory_usage_percent": None,
        "disk_usage_percent": None,
        "network_receive_bps": None,
        "network_transmit_bps": None,
    }
    expressions = {
        "cpu_usage_percent": '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))',
        "memory_usage_percent": "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))",
        "disk_usage_percent": '100 * (1 - (node_filesystem_avail_bytes{fstype!="tmpfs",mountpoint="/"} / node_filesystem_size_bytes{fstype!="tmpfs",mountpoint="/"}))',
        "network_receive_bps": 'sum(rate(node_network_receive_bytes_total{device!="lo"}[5m]))',
        "network_transmit_bps": 'sum(rate(node_network_transmit_bytes_total{device!="lo"}[5m]))',
    }
    for metric_name, expr in expressions.items():
        try:
            metrics[metric_name] = _prometheus_instant_query(prometheus_base_url, expr)
        except Exception:
            logger.exception("Failed to fetch Prometheus metric %s", metric_name)
    return metrics


def _collect_recently_seen_services(prometheus_base_url: str) -> List[str]:
    """Return compose services that have emitted cAdvisor samples recently."""
    expr = (
        "count by (container_label_com_docker_compose_service) "
        "(max_over_time(container_last_seen"
        '{container_label_com_docker_compose_service!="",image!=""}[5m]))'
    )
    response = requests.get(
        f"{_validated_http_url(prometheus_base_url).rstrip('/')}/api/v1/query",
        params={"query": expr},
        timeout=5.0,
    )
    payload = response.json()

    if payload.get("status") != "success":
        return []

    results = payload.get("data", {}).get("result", [])
    discovered = set()
    for sample in results:
        metric = sample.get("metric", {}) or {}
        service_name = str(
            metric.get("container_label_com_docker_compose_service", "")
        ).strip()
        if service_name:
            discovered.add(service_name)
    return sorted(discovered)


def _docker_compose_json(command: List[str]) -> Optional[object]:
    """Run a docker compose JSON command and return decoded payload."""
    try:
        process = process_utils.run(
            command,
            check=True,
        )
    except (FileNotFoundError, process_utils.CalledProcessError):
        return None

    stdout = process.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to decode JSON from command: %s", " ".join(command))
        return None


class _UnixSocketHTTPConnection(HTTPConnection):
    """HTTP client connection implementation for Docker Unix sockets."""

    def __init__(self, unix_socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.unix_socket_path = unix_socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_socket_path)


def _docker_api_json(path: str, timeout_seconds: float = 3.0) -> Optional[object]:
    """Query Docker Engine API over /var/run/docker.sock and return JSON payload."""
    docker_socket = os.environ.get("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    if not os.path.exists(docker_socket):
        logger.debug("Docker socket not found at %s", docker_socket)
        return None

    connection = _UnixSocketHTTPConnection(docker_socket, timeout=timeout_seconds)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            logger.debug(
                "Docker API request failed for %s with status %d", path, response.status
            )
            return None
        payload = response.read().decode("utf-8")
        if not payload:
            return None
        return json.loads(payload)
    except PermissionError:
        logger.warning(
            "Permission denied accessing Docker socket at %s. "
            "Ensure the container user is in the docker group "
            "(check group_add GID in docker-compose.yml matches: "
            "stat -c '%%g' /var/run/docker.sock).",
            docker_socket,
        )
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Docker API request failed for %s: %s", path, exc)
        return None
    finally:
        connection.close()


def _docker_identity_diagnostics(diag: dict[str, object]) -> list[int]:
    try:
        diag["current_uid"] = os.getuid()
        current_gids = list(os.getgroups())
        diag["current_gids"] = current_gids
        import pwd

        try:
            diag["current_user"] = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            diag["current_user"] = f"uid={os.getuid()}"
        return current_gids
    except Exception as exc:
        logger.warning("Unable to resolve current user for Docker diagnostics: %s", exc)
        diag["current_user"] = "error"
        return []


def _docker_socket_diagnostics(
    diag: dict[str, object],
    docker_socket: str,
    current_gids: list[int],
) -> None:
    if not diag["socket_exists"]:
        return
    try:
        stat_info = os.stat(docker_socket)
        diag["socket_stat"] = (
            f"uid={stat_info.st_uid} gid={stat_info.st_gid} "
            f"mode={oct(stat_info.st_mode)}"
        )
        diag["socket_gid"] = int(stat_info.st_gid)
        diag["process_in_socket_group"] = int(stat_info.st_gid) in {
            int(gid) for gid in current_gids
        }
    except Exception as exc:
        logger.warning("Unable to stat Docker socket %s: %s", docker_socket, exc)
        diag["socket_stat"] = "stat unavailable"


def _docker_status_sample(container: dict) -> dict[str, str]:
    labels = container.get("Labels", {}) or {}
    service = str(labels.get("com.docker.compose.service", "")).strip()
    status = str(container.get("Status", "")).strip()
    state = str(container.get("State", "")).strip()
    parsed_health = _parse_docker_status_health(status)
    return {
        "service": service or "(no label)",
        "state": state,
        "status": status,
        "parsed_health": parsed_health or "(none)",
    }


def _docker_container_health_summary(
    containers: list,
) -> tuple[int, list[dict[str, str]]]:
    health_count = 0
    samples: list[dict[str, str]] = []
    for container in containers[:15]:
        if not isinstance(container, dict):
            continue
        sample = _docker_status_sample(container)
        if sample["parsed_health"] != "(none)":
            health_count += 1
        samples.append(sample)
    return health_count, samples


def _docker_api_diagnostics(diag: dict[str, object]) -> None:
    try:
        containers = _docker_api_json("/containers/json?all=1")
        if containers is None:
            diag["api_error"] = "API returned None (connection or permission error)"
            return
        if not isinstance(containers, list):
            diag["api_error"] = f"unexpected type: {type(containers).__name__}"
            return
        diag["api_reachable"] = True
        diag["container_count"] = len(containers)
        health_count, samples = _docker_container_health_summary(containers)
        diag["containers_with_health"] = health_count
        diag["sample_statuses"] = samples
    except Exception as exc:
        logger.warning("Docker API diagnostics failed: %s", exc)
        diag["api_error"] = "Docker API request failed"


def _diagnose_docker_health() -> Dict[str, object]:
    """Return diagnostic info about Docker socket access and health data retrieval.

    This is included in the resource monitoring API response to help debug
    cases where container health status is not being reported correctly.
    """
    docker_socket = os.environ.get("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    current_gids: List[int] = []
    diag: Dict[str, object] = {
        "socket_path": docker_socket,
        "socket_exists": os.path.exists(docker_socket),
        "socket_readable": os.access(docker_socket, os.R_OK),
        "socket_writable": os.access(docker_socket, os.W_OK),
        "current_user": "",
        "current_uid": -1,
        "current_gids": [],
        "socket_stat": "",
        "socket_gid": -1,
        "process_in_socket_group": False,
        "api_reachable": False,
        "api_error": "",
        "container_count": 0,
        "containers_with_health": 0,
        "sample_statuses": [],
    }

    current_gids = _docker_identity_diagnostics(diag)
    _docker_socket_diagnostics(diag, docker_socket, current_gids)
    _docker_api_diagnostics(diag)
    return diag


def _parse_docker_status_health(status: str) -> str:
    """Parse Docker status text and return health state when present."""
    match = re.search(r"\((healthy|unhealthy|starting)\)", str(status or "").lower())
    if match:
        return match.group(1)
    return ""


def _compose_service_from_container(container: dict) -> str:
    labels = container.get("Labels", {}) or {}
    if not isinstance(labels, dict):
        return ""
    return str(labels.get("com.docker.compose.service", "")).strip()


def _container_runtime_health(container: dict) -> tuple[str, str, str]:
    service_name = _compose_service_from_container(container)
    if not service_name:
        return "", "", ""
    state = str(container.get("State", "")).strip().lower()
    health = _parse_docker_status_health(str(container.get("Status", "")).strip())
    return service_name, state, health


def _container_id(container: dict) -> str:
    return str(container.get("Id", "")).strip()


def _has_inspected_healthcheck(inspect_payload: dict) -> bool:
    config_payload = inspect_payload.get("Config", {}) or {}
    healthcheck_payload = config_payload.get("Healthcheck")
    return (
        isinstance(healthcheck_payload, dict)
        and bool(healthcheck_payload.get("Test"))
        and healthcheck_payload.get("Test") != ["NONE"]
    )


def _inspected_health_status(inspect_payload: dict) -> str:
    state_payload = inspect_payload.get("State", {}) or {}
    state_health = state_payload.get("Health", {}) or {}
    if not isinstance(state_health, dict):
        return ""
    inspected_health = str(state_health.get("Status", "")).strip().lower()
    if inspected_health in {"healthy", "unhealthy", "starting"}:
        return inspected_health
    return ""


def _apply_container_inspect_health(
    service_name: str,
    container_id: str,
    healthcheck_config: dict[str, bool],
    runtime_health: dict[str, dict[str, str]],
) -> None:
    inspect_payload = _docker_api_json(f"/containers/{container_id}/json")
    if not isinstance(inspect_payload, dict):
        return
    if not _has_inspected_healthcheck(inspect_payload):
        return
    healthcheck_config[service_name] = True
    inspected_health = _inspected_health_status(inspect_payload)
    if inspected_health:
        runtime_health[service_name]["health"] = inspected_health


def _load_compose_health_data() -> Tuple[Dict[str, bool], Dict[str, Dict[str, str]]]:
    """Return compose healthcheck config and runtime state, preferring Docker API.

    Uses the /containers/json list endpoint directly.  The human-readable
    ``Status`` field already contains healthcheck indicators such as
    ``(healthy)``, ``(unhealthy)`` or ``(starting)`` — so individual
    ``/containers/{id}/json`` inspect calls are only made for running
    containers whose Status string does *not* contain a health parenthetical
    (to detect healthchecks that haven't produced a result yet).
    """
    containers = _docker_api_json("/containers/json?all=1")
    if not isinstance(containers, list):
        logger.warning(
            "Docker API container list unavailable; "
            "falling back to CLI for compose health data"
        )
        return _load_compose_healthcheck_config(), _load_compose_runtime_health()

    healthcheck_config: Dict[str, bool] = {}
    runtime_health: Dict[str, Dict[str, str]] = {}

    # Containers that are running but whose Status field has no health
    # parenthetical — we need to inspect these to detect healthchecks
    # that haven't produced a result yet (e.g. still in start_period).
    needs_inspect: List[Tuple[str, str]] = []  # (service_name, container_id)

    for container in containers:
        if not isinstance(container, dict):
            continue
        service_name, state, health_from_status = _container_runtime_health(container)
        if not service_name:
            continue

        if health_from_status:
            # Status field has a health indicator → container has a healthcheck.
            healthcheck_config[service_name] = True
            runtime_health[service_name] = {
                "state": state,
                "health": health_from_status,
            }
        else:
            # No health indicator in Status.  Store what we know so far and
            # queue an inspect for running containers (they might have a
            # healthcheck in start_period or without a status yet).
            if service_name not in healthcheck_config:
                healthcheck_config[service_name] = False
            runtime_health[service_name] = {"state": state, "health": ""}
            if state == "running":
                container_id = _container_id(container)
                if container_id:
                    needs_inspect.append((service_name, container_id))

    # Inspect only the small set of running containers that lacked a health
    # parenthetical — typically services without a healthcheck at all.
    for service_name, container_id in needs_inspect:
        _apply_container_inspect_health(
            service_name,
            container_id,
            healthcheck_config,
            runtime_health,
        )

    return healthcheck_config, runtime_health


def _load_compose_healthcheck_config() -> Dict[str, bool]:
    """Return whether each compose service defines a Docker healthcheck."""
    payload = _docker_compose_json(["docker", "compose", "config", "--format", "json"])
    if not isinstance(payload, dict):
        return {}
    services = payload.get("services", {}) or {}
    if not isinstance(services, dict):
        return {}

    result: Dict[str, bool] = {}
    for service_name, config in services.items():
        if not isinstance(config, dict):
            continue
        result[str(service_name)] = "healthcheck" in config
    return result


def _load_compose_runtime_health() -> Dict[str, Dict[str, str]]:
    """Return runtime state and health values reported by docker compose ps."""
    payload = _docker_compose_json(["docker", "compose", "ps", "--format", "json"])
    if not isinstance(payload, list):
        return {}

    runtime: Dict[str, Dict[str, str]] = {}
    for container in payload:
        if not isinstance(container, dict):
            continue
        service_name = str(container.get("Service", "")).strip()
        if not service_name:
            continue
        runtime[service_name] = {
            "state": str(container.get("State", "")).strip().lower(),
            "health": str(container.get("Health", "")).strip().lower(),
        }
    return runtime


def _service_name_variants(raw_candidate: str) -> set[str]:
    candidate = str(raw_candidate or "").strip().lstrip("/")
    if not candidate:
        return set()

    variants = {candidate, candidate.lower()}
    if "/" in candidate:
        tail = candidate.rsplit("/", 1)[-1]
        variants.update({tail, tail.lower()})
    if ":" in candidate:
        head = candidate.split(":", 1)[0]
        variants.update({head, head.lower()})

    container_name_match = re.match(r"^[^_]+_([^_]+)_\d+$", candidate)
    if container_name_match:
        service_candidate = container_name_match.group(1)
        variants.update({service_candidate, service_candidate.lower()})

    normalized_variants = set(variants)
    normalized_variants.update(value.replace("_", "-") for value in variants)
    normalized_variants.update(value.replace("-", "_") for value in variants)
    return normalized_variants


def _resolve_expected_service_name(
    raw_candidate: str,
    expected_lookup: dict[str, str],
) -> str:
    for variant in _service_name_variants(raw_candidate):
        direct_match = expected_lookup.get(variant)
        if direct_match:
            return direct_match
    return ""


def _target_service_candidates(target: dict[str, object]) -> tuple[str, ...]:
    raw_labels = target.get("labels", {}) or {}
    raw_discovered_labels = target.get("discoveredLabels", {}) or {}
    labels = raw_labels if isinstance(raw_labels, dict) else {}
    discovered_labels = (
        raw_discovered_labels if isinstance(raw_discovered_labels, dict) else {}
    )
    return (
        str(labels.get("container_label_com_docker_compose_service", "")).strip(),
        str(
            discovered_labels.get(
                "__meta_docker_container_label_com_docker_compose_service",
                "",
            )
        ).strip(),
        str(discovered_labels.get("__meta_docker_container_name", "")).strip(),
        str(labels.get("job", "")).strip(),
        str(target.get("scrapePool", "")).strip(),
    )


def _status_by_prometheus_target(
    active_targets: List[Dict[str, object]],
    expected_services: List[str],
) -> dict[str, str]:
    expected_lookup = {service.lower(): service for service in expected_services}
    status_by_service = {service: "unknown" for service in expected_services}
    for target in active_targets:
        health = str(target.get("health", "unknown")).lower()
        for candidate in _target_service_candidates(target):
            service_name = _resolve_expected_service_name(candidate, expected_lookup)
            if service_name:
                _apply_prometheus_target_health(status_by_service, service_name, health)
    return status_by_service


def _apply_prometheus_target_health(
    status_by_service: dict[str, str],
    service_name: str,
    health: str,
) -> None:
    current = status_by_service[service_name]
    if health == "up":
        status_by_service[service_name] = "up"
    elif current != "up" and health in {"down", "unknown"}:
        status_by_service[service_name] = health


def _mark_recently_seen_services(
    status_by_service: dict[str, str],
    recently_seen_services: Optional[List[str]],
) -> None:
    recently_seen = {
        str(service).strip().lower() for service in (recently_seen_services or [])
    }
    for service, health in list(status_by_service.items()):
        if health == "unknown" and service.lower() in recently_seen:
            status_by_service[service] = "up"


def _lower_bool_lookup(values: Optional[Dict[str, bool]]) -> dict[str, bool]:
    return {
        str(name).lower(): bool(enabled) for name, enabled in (values or {}).items()
    }


def _lower_runtime_lookup(
    values: Optional[Dict[str, Dict[str, str]]],
) -> dict[str, Dict[str, str]]:
    return {str(name).lower(): payload for name, payload in (values or {}).items()}


def _target_service_health(
    prometheus_health: str,
    state: str,
    healthcheck_state: str,
    has_healthcheck: bool,
) -> str:
    if not has_healthcheck:
        return (
            "up"
            if prometheus_health == "unknown" and state == "running"
            else prometheus_health
        )
    if state and state != "running":
        return "down"
    if healthcheck_state in {"healthy", "unhealthy", "starting"}:
        return healthcheck_state
    if prometheus_health == "unknown" and state == "running":
        return "up"
    return prometheus_health


def _target_service_entry(
    service: str,
    prometheus_health: str,
    healthcheck_lookup: dict[str, bool],
    runtime_lookup: dict[str, Dict[str, str]],
) -> dict[str, str]:
    runtime = runtime_lookup.get(service.lower(), {})
    state = str(runtime.get("state", "")).lower()
    healthcheck_state = str(runtime.get("health", "")).lower()
    has_healthcheck = healthcheck_lookup.get(service.lower(), False)
    if not has_healthcheck and healthcheck_state:
        has_healthcheck = True
    return {
        "service": service,
        "health": _target_service_health(
            prometheus_health,
            state,
            healthcheck_state,
            has_healthcheck,
        ),
        "state": state or "unknown",
        "healthcheck": healthcheck_state if has_healthcheck else "none",
    }


def _build_target_service_status(
    active_targets: List[Dict[str, object]],
    expected_services: List[str],
    recently_seen_services: Optional[List[str]] = None,
    service_healthcheck_config: Optional[Dict[str, bool]] = None,
    runtime_health_by_service: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Map expected compose services to their Prometheus target health."""
    status_by_service = _status_by_prometheus_target(active_targets, expected_services)
    _mark_recently_seen_services(status_by_service, recently_seen_services)
    healthcheck_lookup = _lower_bool_lookup(service_healthcheck_config)
    runtime_lookup = _lower_runtime_lookup(runtime_health_by_service)
    return [
        _target_service_entry(
            service,
            status_by_service.get(service, "unknown"),
            healthcheck_lookup,
            runtime_lookup,
        )
        for service in expected_services
    ]


def _public_monitoring_base_url(
    *,
    configured_public_url: str,
    internal_url: str,
    request_scheme: str,
    request_host: str,
    host_port: int,
    proxied: bool,
) -> str:
    if configured_public_url:
        return configured_public_url
    if not _is_internal_hostname(urlparse(internal_url).hostname or ""):
        return ""
    if proxied:
        return ""
    return _build_public_service_url(
        internal_url,
        request_scheme,
        request_host,
        host_port,
    )


def _monitoring_dashboard_query() -> str:
    return urlencode(
        {
            "orgId": "1",
            "from": "now-6h",
            "to": "now",
            "timezone": "browser",
            "refresh": "10s",
        }
    )


def _grafana_dashboard_urls(
    grafana_public_base_url: str,
    dashboard_query: str,
) -> dict[str, str]:
    dashboard_uid = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "omero-infrastructure"
    )
    dashboard_slug = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server-infrastructure"
    )
    dashboards = {
        "dashboard": (
            f"d/{dashboard_uid}/{dashboard_slug}",
            dashboard_uid,
            dashboard_slug,
        ),
        "database_dashboard": (
            "d/database-metrics/database",
            "database-metrics",
            "database",
        ),
        "plugin_database_dashboard": (
            "d/plugin-database-metrics/plugin-database",
            "plugin-database-metrics",
            "plugin-database",
        ),
        "redis_dashboard": ("d/redis-metrics/redis", "redis-metrics", "redis"),
    }
    urls: dict[str, str] = {}
    for prefix, (subpath, uid, slug) in dashboards.items():
        proxy_path = reverse(
            "omeroweb_admin_tools_grafana_proxy",
            kwargs={"subpath": subpath},
        )
        urls[f"{prefix}_url"] = f"/d/{uid}/{slug}?{dashboard_query}"
        urls[f"{prefix}_proxy_url"] = f"{proxy_path}?{dashboard_query}"
        urls[f"{prefix}_external_url"] = (
            f"{grafana_public_base_url.rstrip('/')}/d/{uid}/{slug}?{dashboard_query}"
            if grafana_public_base_url
            else ""
        )
    return urls


def _empty_targets_overview() -> dict[str, Any]:
    return {"active": 0, "up": 0, "down": 0, "unknown": 0, "services": []}


def _prometheus_active_targets(prometheus_base_url: str) -> list[dict[str, object]]:
    response = requests.get(
        f"{_validated_http_url(prometheus_base_url).rstrip('/')}/api/v1/targets",
        timeout=5.0,
    )
    payload = response.json()
    data_payload = payload.get("data", {}) if isinstance(payload, dict) else {}
    raw_active_targets = (
        data_payload.get("activeTargets", []) if isinstance(data_payload, dict) else []
    )
    return [target for target in raw_active_targets if isinstance(target, dict)]


def _target_counts(active_targets: list[dict[str, object]]) -> dict[str, int]:
    up_count = sum(
        1 for target in active_targets if str(target.get("health", "")).lower() == "up"
    )
    down_count = sum(
        1
        for target in active_targets
        if str(target.get("health", "")).lower() == "down"
    )
    return {
        "active": len(active_targets),
        "up": up_count,
        "down": down_count,
        "unknown": len(active_targets) - up_count - down_count,
    }


def _recently_seen_services(prometheus_base_url: str) -> list[str]:
    try:
        return _collect_recently_seen_services(prometheus_base_url)
    except Exception:
        logger.exception("Failed to fetch recently seen cAdvisor services")
        return []


def _monitoring_targets_overview(
    prometheus_base_url: str,
    expected_services: list[str],
) -> dict[str, Any]:
    targets_overview = _empty_targets_overview()
    try:
        active_targets = _prometheus_active_targets(prometheus_base_url)
        targets_overview.update(_target_counts(active_targets))
        service_healthcheck_config, runtime_health_by_service = (
            _load_compose_health_data()
        )
        recently_seen_services = _recently_seen_services(prometheus_base_url)
        all_services = sorted(set(expected_services) | set(recently_seen_services))
        targets_overview["services"] = _build_target_service_status(
            active_targets,
            all_services,
            recently_seen_services=recently_seen_services,
            service_healthcheck_config=service_healthcheck_config,
            runtime_health_by_service=runtime_health_by_service,
        )
    except Exception:
        logger.exception("Failed to fetch Prometheus targets overview")
    return targets_overview


@login_required()
@require_root_user
def resource_monitoring_view(request, _conn=None, _url=None, **kwargs):
    """Render resource monitoring dashboard."""
    return render(request, "omeroweb_admin_tools/resource_monitoring.html", {})


@login_required()
@require_root_user
def resource_monitoring_data(request, conn=None, _url=None, **kwargs):
    """Return monitoring endpoint URLs for Grafana and Prometheus dashboards."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    grafana_base_url = _internal_service_base_url(
        "ADMIN_TOOLS_GRAFANA_URL",
        default_host="grafana",
        default_port=3000,
    )
    prometheus_base_url = _internal_service_base_url(
        "ADMIN_TOOLS_PROMETHEUS_URL",
        default_host="prometheus",
        default_port=9090,
    )

    request_host = _safe_request_host(request)
    request_scheme = request.scheme
    proxied = _is_behind_reverse_proxy(request)
    grafana_public_base_url = _public_monitoring_base_url(
        configured_public_url=os.environ.get(
            "ADMIN_TOOLS_GRAFANA_PUBLIC_URL", ""
        ).strip(),
        internal_url=grafana_base_url,
        request_scheme=request_scheme,
        request_host=request_host,
        host_port=_to_int_env("GRAFANA_HOST_PORT", 3000),
        proxied=proxied,
    )
    prometheus_public_base_url = _public_monitoring_base_url(
        configured_public_url=os.environ.get(
            "ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", ""
        ).strip(),
        internal_url=prometheus_base_url,
        request_scheme=request_scheme,
        request_host=request_host,
        host_port=_to_int_env("PROMETHEUS_HOST_PORT", 9090),
        proxied=proxied,
    )
    dashboard_query = _monitoring_dashboard_query()
    dashboard_urls = _grafana_dashboard_urls(
        grafana_public_base_url,
        dashboard_query,
    )
    prometheus_targets_url = (
        f"{prometheus_public_base_url.rstrip('/')}/targets"
        if prometheus_public_base_url
        else ""
    )
    prometheus_targets_proxy_url = reverse(
        "omeroweb_admin_tools_prometheus_proxy", kwargs={"subpath": "targets"}
    )

    grafana_probe = _probe_http_url(f"{grafana_base_url.rstrip('/')}/api/health")
    prometheus_probe = _probe_http_url(f"{prometheus_base_url.rstrip('/')}/-/ready")

    expected_services = _load_compose_service_names()
    system_metrics = _collect_system_metrics(prometheus_base_url)
    targets_overview = _monitoring_targets_overview(
        prometheus_base_url,
        expected_services,
    )

    return JsonResponse(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "grafana": {
                "base_url": grafana_base_url,
                **dashboard_urls,
                "probe": grafana_probe,
            },
            "prometheus": {
                "base_url": prometheus_base_url,
                "targets_url": prometheus_targets_url,
                "targets_proxy_url": prometheus_targets_proxy_url,
                "probe": prometheus_probe,
                "targets_overview": targets_overview,
            },
            "system_metrics": system_metrics,
            "docker_diagnostics": _diagnose_docker_health(),
        }
    )


@login_required()
@require_root_user
def grafana_proxy(request, subpath: str, conn=None, _url=None, **kwargs):
    """Proxy Grafana HTTP responses through OMERO.web."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method not in _GRAFANA_PROXY_METHODS:
        return _proxy_method_not_allowed_response(allowed=_GRAFANA_PROXY_METHODS)

    grafana_base_url = _internal_service_base_url(
        "ADMIN_TOOLS_GRAFANA_URL",
        default_host="grafana",
        default_port=3000,
    )
    grafana_public_url = os.environ.get("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "")
    backend_urls = _build_proxy_backend_urls(grafana_base_url, grafana_public_url)

    try:
        subpath, forwarded_query = _normalize_proxy_request_target(subpath)
    except ValueError:
        return JsonResponse({"error": "Invalid proxy target"}, status=400)

    request_query = request.META.get("QUERY_STRING", "")
    merged_query = "&".join(part for part in (forwarded_query, request_query) if part)
    proxy_prefix = (
        request.path[: -len(subpath)].rstrip("/") if subpath else request.path
    )

    if not subpath:
        return _grafana_proxy_home_fallback_response(proxy_prefix)

    last_response = None
    for backend_url in backend_urls:
        response = _proxy_http_request(
            request,
            backend_url,
            subpath,
            merged_query,
            proxy_prefix=proxy_prefix,
            rewrite_origin_headers=True,
            extra_forwarded_headers=("X-Grafana-Csrf-Token",),
        )
        last_response = response
        if getattr(response, "status_code", 502) != 502:
            return response

    if last_response is None:
        raise RuntimeError("No Grafana backend URLs configured; cannot proxy request.")
    logger.warning(
        "Grafana proxy unavailable for path=%s after checking backends=%s",
        sanitize_log_value(subpath),
        ", ".join(sanitize_url_for_logging(url) for url in backend_urls),
    )
    return _grafana_unavailable_response(
        proxy_prefix=proxy_prefix,
        attempted_backends=backend_urls,
        status_code=int(getattr(last_response, "status_code", 502)),
    )


@login_required()
@require_root_user
def prometheus_proxy(request, subpath: str, conn=None, _url=None, **kwargs):
    """Proxy Prometheus HTTP responses through OMERO.web."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method not in _PROXY_SAFE_METHODS:
        return _proxy_method_not_allowed_response()

    prometheus_base_url = _internal_service_base_url(
        "ADMIN_TOOLS_PROMETHEUS_URL",
        default_host="prometheus",
        default_port=9090,
    )
    prometheus_public_url = os.environ.get("ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", "")
    backend_urls = _build_proxy_backend_urls(
        prometheus_base_url,
        prometheus_public_url,
    )

    try:
        subpath, forwarded_query = _normalize_proxy_request_target(subpath)
    except ValueError:
        return JsonResponse({"error": "Invalid proxy target"}, status=400)

    request_query = request.META.get("QUERY_STRING", "")
    merged_query = "&".join(part for part in (forwarded_query, request_query) if part)
    proxy_prefix = (
        request.path[: -len(subpath)].rstrip("/") if subpath else request.path
    )

    if not subpath:
        return _grafana_proxy_home_fallback_response(proxy_prefix)

    last_response = None
    for backend_url in backend_urls:
        response = _proxy_http_request(
            request,
            backend_url,
            subpath,
            merged_query,
            proxy_prefix=proxy_prefix,
        )
        last_response = response
        if getattr(response, "status_code", 502) != 502:
            return response

    if last_response is None:
        raise RuntimeError(
            "No Prometheus backend URLs configured; cannot proxy request."
        )
    return last_response


@login_required()
@require_root_user
@ensure_csrf_cookie
def storage_view(request, _conn=None, _url=None, **kwargs):
    """Render storage capacity distribution page."""
    return render(request, "omeroweb_admin_tools/storage.html", {})


_STORAGE_DISTRIBUTION_QUERY = """
    select e.id, e.omeName, g.id, g.name, sum(file.size)
    from OriginalFile file
    join file.details.owner e
    join file.details.group g
    group by e.id, e.omeName, g.id, g.name
"""


def _storage_distribution_from_rows(rows) -> dict[str, object]:
    per_user_group: list[dict[str, object]] = []
    totals_by_user: dict[str, int] = {}
    full_name_by_user: dict[str, str] = {}
    groups_by_user: dict[str, set[str]] = {}
    totals_by_group: dict[str, int] = {}
    users_by_group: dict[str, set[str]] = {}
    total_size = 0

    for row in rows:
        user_name = str(_unwrap_rtype_value(row[1], "unknown") or "unknown")
        group_name = str(_unwrap_rtype_value(row[3], "unknown") or "unknown")
        size_value = int(_unwrap_rtype_value(row[4], 0) or 0)
        per_user_group.append(
            {"username": user_name, "group": group_name, "bytes": size_value}
        )
        totals_by_user[user_name] = totals_by_user.get(user_name, 0) + size_value
        groups_by_user.setdefault(user_name, set()).add(group_name)
        totals_by_group[group_name] = totals_by_group.get(group_name, 0) + size_value
        users_by_group.setdefault(group_name, set()).add(user_name)
        total_size += size_value

    return {
        "per_user_group": per_user_group,
        "totals_by_user": totals_by_user,
        "full_name_by_user": full_name_by_user,
        "groups_by_user": groups_by_user,
        "totals_by_group": totals_by_group,
        "users_by_group": users_by_group,
        "total_size": total_size,
    }


def _query_storage_distribution(conn) -> dict[str, object]:
    service_opts = conn.SERVICE_OPTS
    if hasattr(service_opts, "setOmeroGroup"):
        service_opts.setOmeroGroup(-1)
    rows = conn.getQueryService().projection(
        _STORAGE_DISTRIBUTION_QUERY,
        None,
        service_opts,
    )
    distribution = _storage_distribution_from_rows(rows)
    _merge_known_storage_principals(conn, distribution)
    return distribution


def _merge_known_storage_principals(conn, distribution: dict[str, object]) -> None:
    totals_by_user = cast(dict[str, int], distribution["totals_by_user"])
    full_name_by_user = cast(dict[str, str], distribution["full_name_by_user"])
    groups_by_user = cast(dict[str, set[str]], distribution["groups_by_user"])
    totals_by_group = cast(dict[str, int], distribution["totals_by_group"])
    users_by_group = cast(dict[str, set[str]], distribution["users_by_group"])

    (
        all_users,
        all_groups,
        group_permissions,
        all_groups_by_user,
        all_users_by_group,
    ) = _list_all_users_and_groups(conn)
    for username, full_name in all_users.items():
        totals_by_user.setdefault(username, 0)
        groups_by_user.setdefault(username, set()).update(
            all_groups_by_user.get(username, set())
        )
        full_name_by_user[username] = full_name
    for group_name in all_groups:
        totals_by_group.setdefault(group_name, 0)
        users_by_group.setdefault(group_name, set()).update(
            all_users_by_group.get(group_name, set())
        )
        group_permissions.setdefault(group_name, "Private")

    for username in totals_by_user:
        full_name_by_user.setdefault(username, "")
    distribution["group_permissions"] = group_permissions


def _storage_disk_usage(data_root: str) -> tuple[int | None, int | None, int | None]:
    try:
        return shutil.disk_usage(data_root)
    except Exception:
        logger.warning("Could not read disk usage for data root %s", data_root)
        return None, None, None


def _storage_quota_status(known_groups: list[str]) -> dict[str, object]:
    try:
        return reconcile_quotas(known_groups)
    except Exception:
        logger.warning(
            "Quota reconciliation failed; returning storage data without quota info",
            exc_info=True,
        )
        try:
            enforcer_available = is_quota_enforcement_available()
        except Exception:
            enforcer_available = False
        return {
            "quotas_gb": {},
            "logs": [],
            "quota_enforcement_available": enforcer_available,
        }


def _storage_bytes_sort_key(item: dict[str, object]) -> int:
    value = item.get("bytes", 0)
    return int(value) if isinstance(value, (int, float, str)) else 0


def _storage_response_payload(
    distribution: dict[str, object],
    data_root: str,
    data_total: int | None,
    data_used: int | None,
    data_free: int | None,
    quota_status: dict[str, object],
) -> dict[str, object]:
    totals_by_user = cast(dict[str, int], distribution["totals_by_user"])
    full_name_by_user = cast(dict[str, str], distribution["full_name_by_user"])
    groups_by_user = cast(dict[str, set[str]], distribution["groups_by_user"])
    totals_by_group = cast(dict[str, int], distribution["totals_by_group"])
    users_by_group = cast(dict[str, set[str]], distribution["users_by_group"])
    group_permissions = cast(dict[str, str], distribution["group_permissions"])
    per_user_group = cast(
        list[dict[str, object]],
        distribution["per_user_group"],
    )
    return {
        "totals": {
            "omero_binary_bytes": distribution["total_size"],
            "data_root": data_root,
            "data_root_total_bytes": data_total,
            "data_root_used_bytes": data_used,
            "data_root_free_bytes": data_free,
        },
        "by_user": [
            {
                "username": username,
                "full_name": full_name_by_user.get(username, ""),
                "groups": sorted(groups_by_user.get(username, set())),
                "bytes": size,
            }
            for username, size in sorted(
                totals_by_user.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "by_group": [
            {
                "group": groupname,
                "users": sorted(users_by_group.get(groupname, set())),
                "permissions": group_permissions.get(groupname, "Private"),
                "bytes": size,
            }
            for groupname, size in sorted(
                totals_by_group.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "by_user_group": sorted(
            per_user_group,
            key=_storage_bytes_sort_key,
            reverse=True,
        ),
        "quotas": quota_status,
    }


@login_required()
@require_root_user
def storage_data(request, conn=None, _url=None, **kwargs):
    """Return size distribution by OMERO user and group using OriginalFile sizes."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    try:
        distribution = _query_storage_distribution(conn)
    except Exception:
        logger.exception("Failed to compute storage distribution")
        return JsonResponse({"error": "Storage query failed."}, status=500)

    data_root = os.environ.get("OMERO_DATA_DIR", "/OMERO")
    data_total, data_used, data_free = _storage_disk_usage(data_root)

    totals_by_group = cast(dict[str, int], distribution["totals_by_group"])
    quota_status = _storage_quota_status(sorted(totals_by_group.keys()))
    return JsonResponse(
        _storage_response_payload(
            distribution,
            data_root,
            data_total,
            data_used,
            data_free,
            quota_status,
        )
    )


@login_required()
@require_root_user
def storage_quota_data(request, conn=None, _url=None, **kwargs):
    """Fetch persisted quota definitions and reconciliation logs."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    try:
        state = get_quota_state()
    except Exception:
        logger.warning(
            "Could not read quota state file; using empty defaults", exc_info=True
        )
        state = {"quotas_gb": {}, "logs": []}

    try:
        known_groups = _list_omero_group_names(conn)
        reconciled = reconcile_quotas(known_groups)
    except Exception:
        logger.warning(
            "Quota reconciliation failed in quota_data view; returning partial data",
            exc_info=True,
        )
        try:
            enforcer_available = is_quota_enforcement_available()
        except Exception:
            enforcer_available = False
        reconciled = {
            "quotas_gb": state.get("quotas_gb", {}),
            "logs": state.get("logs", []),
            "quota_enforcement_available": enforcer_available,
        }

    return JsonResponse(
        {
            "quotas_gb": state.get("quotas_gb", {}),
            "logs": state.get("logs", []),
            "reconcile": reconciled,
        }
    )


def _json_payload_from_request(request) -> dict[str, object]:
    raw_body = request.body.decode("utf-8").strip()
    if not raw_body:
        return {}
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _quota_updates_from_form(request):
    if not request.POST:
        return None
    raw_updates = request.POST.get("updates")
    if raw_updates is None:
        return None
    return json.loads(raw_updates) if isinstance(raw_updates, str) else raw_updates


def _normalize_quota_updates(updates) -> list[tuple[str, object]]:
    if updates is None:
        return []
    if not isinstance(updates, list):
        raise QuotaError("Expected payload with list field 'updates'")
    normalized = []
    for item in updates:
        if not isinstance(item, dict):
            raise QuotaError("Each quota update must be an object")
        normalized.append((cast(str, item.get("group", "")), item.get("quota_gb", "")))
    return normalized


def _quota_updates_from_request(request) -> list[tuple[str, object]]:
    payload = _json_payload_from_request(request)
    updates = payload.get("updates")
    if updates is None:
        updates = _quota_updates_from_form(request)
    return _normalize_quota_updates(updates)


@login_required()
@require_root_user
def storage_quota_update(request, conn=None, _url=None, **kwargs):
    """Update group quota values from UI edits."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # ---- parse the request payload ----
    try:
        normalized = _quota_updates_from_request(request)
    except (QuotaError, ValueError, TypeError):
        logger.warning(
            "Invalid quota update payload (content_type=%s, content_length=%s)",
            sanitize_log_value(request.META.get("CONTENT_TYPE", "")),
            sanitize_log_value(request.META.get("CONTENT_LENGTH", "")),
        )
        return JsonResponse({"error": "Invalid quota update payload."}, status=400)

    # ---- persist and reconcile ----
    try:
        state = upsert_quotas(normalized, source="ui-edit")
        known_groups = _list_omero_group_names(conn)
        reconciled = reconcile_quotas(known_groups)
    except Exception:
        logger.exception("Failed to update quotas")
        return JsonResponse({"error": "Quota update failed."}, status=500)

    return JsonResponse(
        {
            "quotas_gb": state.get("quotas_gb", {}),
            "reconcile": reconciled,
        }
    )


@login_required()
@require_root_user
def storage_quota_import(request, conn=None, _url=None, **kwargs):
    """Import group quotas from a CSV upload."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field 'file'"}, status=400)
    csv_file = request.FILES["file"]

    # ---- parse CSV ----
    try:
        content = csv_file.read().decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Invalid CSV import encoding.")
        return JsonResponse({"error": "Invalid CSV import."}, status=400)

    # ---- persist and reconcile ----
    try:
        state = import_quotas_csv(content)
        known_groups = _list_omero_group_names(conn)
        reconciled = reconcile_quotas(known_groups)
    except (QuotaError, CsvError):
        logger.warning("Invalid CSV import payload.")
        return JsonResponse({"error": "Invalid CSV import."}, status=400)
    except Exception:
        logger.exception("Failed to import quotas")
        return JsonResponse({"error": "Quota import failed."}, status=500)

    return JsonResponse(
        {
            "quotas_gb": state.get("quotas_gb", {}),
            "reconcile": reconciled,
        }
    )


@login_required()
@require_root_user
def storage_quota_template(request, conn=None, _url=None, **kwargs):
    """Download quota CSV template."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    template = quota_csv_template()
    response = HttpResponse(template, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="group-quotas-template.csv"'
    return response


@login_required()
@require_root_user
@ensure_csrf_cookie
def server_database_testing_view(request, _conn=None, _url=None, **kwargs):
    """Render OMERO.server and database diagnostics page."""
    return render(
        request,
        "omeroweb_admin_tools/server_database_testing.html",
        {"diagnostic_scripts": json.dumps(serialize_scripts())},
    )


def _diagnostic_script_ids_from_request(
    request,
) -> tuple[list[str], JsonResponse | None]:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], JsonResponse({"error": "Invalid JSON payload."}, status=400)

    script_ids = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(script_ids, list) or not script_ids:
        return [], JsonResponse(
            {"error": "Payload must include non-empty 'scripts' list."},
            status=400,
        )

    normalized_script_ids = [str(script_id).strip() for script_id in script_ids]
    if any(not script_id for script_id in normalized_script_ids):
        return [], JsonResponse(
            {"error": "Payload contains invalid empty script IDs."},
            status=400,
        )
    return normalized_script_ids, None


def _request_username_or_unknown(request, conn) -> str:
    try:
        return current_username(request, conn)
    except Exception:
        return "unknown"


def _sanitized_script_id_list(script_ids: list[str]) -> str:
    return ", ".join(sanitize_log_value(script_id) for script_id in script_ids)


@login_required()
@require_root_user
def server_database_testing_run(request, conn=None, _url=None, **kwargs):
    """Execute selected diagnostics scripts and return a report."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method != "POST":
        return JsonResponse({"error": "POST method required."}, status=405)

    request_id = str(uuid.uuid4())
    normalized_script_ids, error_response = _diagnostic_script_ids_from_request(request)
    if error_response is not None:
        return error_response
    username = _request_username_or_unknown(request, conn)
    script_id_list = _sanitized_script_id_list(normalized_script_ids)
    logger.info(
        "[%s] Running diagnostics scripts requested by %s: %s",
        request_id,
        sanitize_log_value(username),
        script_id_list,
    )
    try:
        results = [
            run_diagnostic_script(script_id) for script_id in normalized_script_ids
        ]
    except Exception as exc:
        logger.error(
            "[%s] Failed to run diagnostics scripts %s: %s\n%s",
            request_id,
            script_id_list,
            sanitize_log_value(exc),
            traceback.format_exc(),
        )
        return JsonResponse(
            {
                "error": "Failed to run diagnostics due to an internal server error.",
                "request_id": request_id,
            },
            status=500,
        )

    logger.info(
        "[%s] Diagnostics scripts completed successfully. scripts=%s",
        request_id,
        script_id_list,
    )
    return JsonResponse({"results": results, "request_id": request_id})
