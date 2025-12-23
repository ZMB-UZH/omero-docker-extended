import hashlib
import json
import logging
import os
import time
from math import ceil

from django.core.cache import cache
import portalocker
try:
    from django.core.cache.backends.dummy import DummyCache
except Exception:  # pragma: no cover - fallback for unexpected cache setups
    DummyCache = None

from ..constants import (
    MAJOR_ACTION_BLOCK_SECONDS,
    MAJOR_ACTION_LIMIT,
    MAJOR_ACTION_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "omp_rate_limit"
_FILE_CACHE_DIR = "/tmp/omp_rate_limit_cache"
os.makedirs(_FILE_CACHE_DIR, exist_ok=True)


def _is_dummy_cache():
    return DummyCache is not None and isinstance(cache, DummyCache)


def _file_cache_path(key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(_FILE_CACHE_DIR, f"{digest}.json")


def _file_cache_get(key):
    path = _file_cache_path(key)
    try:
        with portalocker.Lock(path, mode="a+", timeout=1) as handle:
            handle.seek(0)
            raw = handle.read()
            if not raw:
                return None
            payload = json.loads(raw)
            data = payload.get("data")
            expires_at = payload.get("expires_at")
            if expires_at is not None and time.time() > expires_at:
                handle.seek(0)
                handle.truncate()
                return None
            return data
    except Exception:
        return None


def _file_cache_set(key, value, timeout):
    path = _file_cache_path(key)
    expires_at = time.time() + timeout if timeout else None
    payload = {"data": value, "expires_at": expires_at}
    try:
        with portalocker.Lock(path, mode="a+", timeout=1) as handle:
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(payload))
            handle.flush()
    except Exception:
        return False
    return True


def _cache_get(key):
    if _is_dummy_cache():
        return _file_cache_get(key)
    return cache.get(key)


def _cache_set(key, value, timeout):
    if _is_dummy_cache():
        return _file_cache_set(key, value, timeout)
    cache.set(key, value, timeout=timeout)
    return True


def _cache_timeout_seconds():
    return max(MAJOR_ACTION_WINDOW_SECONDS, MAJOR_ACTION_BLOCK_SECONDS) * 2


def _get_user_key(request, conn=None):
    identifier = None
    if conn is not None:
        try:
            user = conn.getUser()
            if user:
                identifier = user.getName()
        except Exception:
            identifier = None

    if not identifier:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            identifier = getattr(user, "username", None) or getattr(user, "id", None)

    if not identifier:
        identifier = request.META.get("REMOTE_ADDR") or "anonymous"

    return f"{_CACHE_PREFIX}:{identifier}"


def build_rate_limit_message(remaining_seconds):
    remaining = max(0, int(ceil(remaining_seconds)))
    return (
        "You have performed more than "
        f"{MAJOR_ACTION_LIMIT} major actions in the last "
        f"{MAJOR_ACTION_WINDOW_SECONDS} sec while using this plugin. "
        f"Please try again in {remaining} sec."
    )


def check_major_action_rate_limit(request, conn=None):
    now = time.time()
    key = _get_user_key(request, conn=conn)
    try:
        data = _cache_get(key) or {}
        actions = data.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        actions = [
            ts
            for ts in actions
            if isinstance(ts, (int, float))
            and now - ts <= MAJOR_ACTION_WINDOW_SECONDS
        ]

        blocked_until = data.get("blocked_until", 0)
        if not isinstance(blocked_until, (int, float)):
            blocked_until = 0

        if now < blocked_until:
            remaining = blocked_until - now
            _cache_set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        if len(actions) >= MAJOR_ACTION_LIMIT:
            blocked_until = now + MAJOR_ACTION_BLOCK_SECONDS
            remaining = blocked_until - now
            _cache_set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        actions.append(now)
        _cache_set(
            key,
            {"actions": actions, "blocked_until": blocked_until},
            timeout=_cache_timeout_seconds(),
        )
        return True, None
    except Exception as exc:
        logger.exception("Rate limit check failed: %s", exc)
        return False, MAJOR_ACTION_BLOCK_SECONDS
