import logging
import time
from math import ceil

from django.core.cache import cache

from ..constants import (
    MAJOR_ACTION_BLOCK_SECONDS,
    MAJOR_ACTION_LIMIT,
    MAJOR_ACTION_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "omp_rate_limit"


def _cache_timeout_seconds():
    return max(MAJOR_ACTION_WINDOW_SECONDS, MAJOR_ACTION_BLOCK_SECONDS) * 2


def _get_user_key(request):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        identifier = getattr(user, "username", None) or getattr(user, "id", None)
    else:
        identifier = "anonymous"
    return f"{_CACHE_PREFIX}:{identifier}"


def build_rate_limit_message(remaining_seconds):
    remaining = max(0, int(ceil(remaining_seconds)))
    return (
        "You have performed more than "
        f"{MAJOR_ACTION_LIMIT} major actions in the last "
        f"{MAJOR_ACTION_WINDOW_SECONDS} sec while using this plugin. "
        f"Please try again in {remaining} sec."
    )


def check_major_action_rate_limit(request):
    now = time.time()
    key = _get_user_key(request)
    try:
        data = cache.get(key) or {}
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
            cache.set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        if len(actions) >= MAJOR_ACTION_LIMIT:
            blocked_until = now + MAJOR_ACTION_BLOCK_SECONDS
            remaining = blocked_until - now
            cache.set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        actions.append(now)
        cache.set(
            key,
            {"actions": actions, "blocked_until": blocked_until},
            timeout=_cache_timeout_seconds(),
        )
        return True, None
    except Exception as exc:
        logger.exception("Rate limit check failed: %s", exc)
        return False, MAJOR_ACTION_BLOCK_SECONDS
