import hashlib
import json
import logging
import threading
import time
from math import ceil

from django.core.cache import cache
try:
    from django.core.cache.backends.dummy import DummyCache
except Exception:  # pragma: no cover - fallback for unexpected cache setups
    DummyCache = None

from ..constants import (
    MAJOR_ACTION_BLOCK_SECONDS,
    MAJOR_ACTION_LIMIT,
    MAJOR_ACTION_WINDOW_SECONDS,
)
from ..strings import errors

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "omp_rate_limit"

# ============================================================================
# IN-MEMORY FALLBACK CACHE (when Django cache is DummyCache)
# Thread-safe implementation using threading.Lock
# ============================================================================

class InMemoryCache:
    """
    Thread-safe in-memory cache as fallback when Django cache is not configured.
    
    This is more reliable and faster than file-based caching, and automatically
    handles cleanup of expired entries.
    """
    
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # Clean up expired entries every 60 seconds
    
    def _cleanup_expired(self):
        """Remove expired entries to prevent memory bloat."""
        now = time.time()
        
        # Only clean up periodically to avoid overhead
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        expired_keys = [
            key for key, (expires_at, _) in self._store.items()
            if expires_at is not None and now > expires_at
        ]
        
        for key in expired_keys:
            del self._store[key]
        
        self._last_cleanup = now
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def get(self, key):
        """Get a value from cache, returns None if not found or expired."""
        with self._lock:
            self._cleanup_expired()
            
            if key not in self._store:
                return None
            
            expires_at, value = self._store[key]
            
            # Check if expired
            if expires_at is not None and time.time() > expires_at:
                del self._store[key]
                return None
            
            return value
    
    def set(self, key, value, timeout=None):
        """Set a value in cache with optional timeout in seconds."""
        with self._lock:
            expires_at = time.time() + timeout if timeout else None
            self._store[key] = (expires_at, value)
            
            # Periodic cleanup
            self._cleanup_expired()
            
            return True
    
    def delete(self, key):
        """Delete a key from cache."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False
    
    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._store.clear()
            self._last_cleanup = time.time()


# Global in-memory cache instance
_memory_cache = InMemoryCache()


def _is_dummy_cache():
    """Check if Django is using the DummyCache (no-op cache)."""
    return DummyCache is not None and isinstance(cache, DummyCache)


def _cache_get(key):
    """
    Get value from cache, using Django cache if available, 
    otherwise fall back to in-memory cache.
    """
    if _is_dummy_cache():
        return _memory_cache.get(key)
    return cache.get(key)


def _cache_set(key, value, timeout):
    """
    Set value in cache, using Django cache if available,
    otherwise fall back to in-memory cache.
    """
    if _is_dummy_cache():
        return _memory_cache.set(key, value, timeout)
    cache.set(key, value, timeout=timeout)
    return True


def _cache_delete(key):
    """Delete a key from cache."""
    if _is_dummy_cache():
        return _memory_cache.delete(key)
    cache.delete(key)
    return True


def _cache_timeout_seconds():
    """Calculate cache timeout - should be longer than rate limit window."""
    return max(MAJOR_ACTION_WINDOW_SECONDS, MAJOR_ACTION_BLOCK_SECONDS) * 2


def _get_user_key(request, conn=None):
    """
    Generate a unique, collision-resistant cache key for rate limiting.
    ALL major actions share the SAME rate limit counter.
    
    Priority order:
    1. OMERO connection username (most reliable)
    2. Django authenticated user
    3. IP address (fallback for anonymous users)
    
    Returns:
        str: Cache key in format "omp_rate_limit:{type}:{identifier}"
    """
    identifier = None
    key_type = "ip"  # Default type
    
    # Try to get OMERO username first (most reliable)
    if conn is not None:
        try:
            user = conn.getUser()
            if user:
                username = user.getName()
                # Validate non-empty string
                if username and isinstance(username, str) and username.strip():
                    identifier = username.strip()
                    key_type = "omero"
        except Exception as e:
            logger.debug(f"Could not get OMERO user: {e}")
            identifier = None

    # Fall back to Django authenticated user
    if not identifier:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            username = getattr(user, "username", None)
            user_id = getattr(user, "id", None)
            identifier = username or user_id
            if identifier:
                identifier = str(identifier)
                key_type = "django"

    # Last resort: IP address (can be shared by multiple users behind NAT)
    if not identifier:
        identifier = request.META.get("REMOTE_ADDR", "unknown")
        if identifier == "unknown" or not identifier:
            # Try other IP headers as fallback
            identifier = (
                request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                or request.META.get("HTTP_X_REAL_IP", "")
                or "anonymous"
            )
        key_type = "ip"

    # SINGLE SHARED KEY for all major actions
    return f"{_CACHE_PREFIX}:{key_type}:{identifier}"


def build_rate_limit_message(remaining_seconds):
    """
    Build a user-friendly rate limit error message.
    
    Args:
        remaining_seconds: Time until the user can make requests again
        
    Returns:
        str: Formatted error message
    """
    remaining = max(0, int(ceil(remaining_seconds)))
    
    if remaining > 60:
        minutes = remaining // 60
        seconds = remaining % 60
        time_str = f"{minutes} minute(s) and {seconds} second(s)"
    else:
        time_str = f"{remaining} second(s)"

    return errors.rate_limit_exceeded(
        MAJOR_ACTION_LIMIT,
        MAJOR_ACTION_WINDOW_SECONDS,
        time_str,
    )


def check_major_action_rate_limit(request, conn=None):
    """
    Check if the user has exceeded the rate limit for major actions.
    
    This function implements a sliding window rate limiter:
    - Tracks timestamps of recent actions
    - Allows up to MAJOR_ACTION_LIMIT actions per MAJOR_ACTION_WINDOW_SECONDS
    - Blocks users for MAJOR_ACTION_BLOCK_SECONDS when limit is exceeded
    
    ALL major actions (save, delete, preview) share the SAME counter.
    
    Args:
        request: Django HttpRequest object
        conn: Optional OMERO connection object
        
    Returns:
        tuple: (allowed: bool, remaining_seconds: float or None)
            - If allowed=True: User can proceed, remaining_seconds=None
            - If allowed=False: User is blocked, remaining_seconds=time until unblock
    
    Thread-safety: Uses cache operations which are atomic. In-memory fallback
    uses threading.Lock for thread safety.
    """
    now = time.time()
    key = _get_user_key(request, conn=conn)
    
    logger.info(f"[RATE_LIMIT] Checking for key: {key}")
    
    try:
        # Get current state from cache
        data = _cache_get(key) or {}
        actions = data.get("actions", [])
        
        # Validate and clean actions list
        if not isinstance(actions, list):
            actions = []
        
        # Remove actions outside the time window (sliding window algorithm)
        actions = [
            ts
            for ts in actions
            if isinstance(ts, (int, float))
            and now - ts <= MAJOR_ACTION_WINDOW_SECONDS
        ]
        
        # Get blocked status
        blocked_until = data.get("blocked_until", 0)
        if not isinstance(blocked_until, (int, float)):
            blocked_until = 0

        
        logger.info(
            f"[RATE_LIMIT] Current state: {len(actions)} actions in window, "
            f"blocked_until={blocked_until:.2f}, now={now:.2f}"
        )

        # Check if user is currently in a blocked state
        if now < blocked_until:
            remaining = blocked_until - now
            logger.warning(
                f"[RATE_LIMIT] BLOCKED: {key} blocked for {remaining:.1f} more seconds"
            )
            
            # Update cache to maintain blocked state (but don't add action)
            _cache_set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        # Add the current action FIRST, then check limit
        actions.append(now)
        
        logger.info(f"[RATE_LIMIT] After adding action: {len(actions)} total actions")
        
        # Check if we've now exceeded the limit (after adding current action)
        if len(actions) > MAJOR_ACTION_LIMIT:
            # User has exceeded the limit - block them
            blocked_until = now + MAJOR_ACTION_BLOCK_SECONDS
            remaining = MAJOR_ACTION_BLOCK_SECONDS
            
            logger.warning(
                f"[RATE_LIMIT] LIMIT EXCEEDED for {key}! "
                f"Actions: {len(actions)}/{MAJOR_ACTION_LIMIT}. "
                f"Blocking for {remaining:.0f}s"
            )
            
            # Save blocked state
            _cache_set(
                key,
                {"actions": actions, "blocked_until": blocked_until},
                timeout=_cache_timeout_seconds(),
            )
            return False, remaining

        # User is within limits - allow the action
        logger.info(
            f"[RATE_LIMIT] OK: {key} allowed. "
            f"Actions: {len(actions)}/{MAJOR_ACTION_LIMIT} "
            f"({MAJOR_ACTION_LIMIT - len(actions)} remaining)"
        )
        
        # Save updated state
        _cache_set(
            key,
            {"actions": actions, "blocked_until": 0},  # Clear any old blocked state
            timeout=_cache_timeout_seconds(),
        )
        return True, None
        
    except Exception as exc:
        # Log the error but fail closed (block on error for security)
        logger.exception(f"[RATE_LIMIT] ERROR: Rate limit check failed for {key}: {exc}")
        return False, MAJOR_ACTION_BLOCK_SECONDS


def reset_rate_limit(request, conn=None):
    """
    Reset rate limit for a specific user (admin function).
    
    Args:
        request: Django HttpRequest object
        conn: Optional OMERO connection object
        
    Returns:
        bool: True if reset successful, False otherwise
    """
    try:
        key = _get_user_key(request, conn=conn)
        _cache_delete(key)
        logger.info(f"Rate limit reset for {key}")
        return True
    except Exception as exc:
        logger.exception(f"Failed to reset rate limit: {exc}")
        return False


def get_rate_limit_status(request, conn=None):
    """
    Get current rate limit status for a user (debugging/monitoring function).
    
    Args:
        request: Django HttpRequest object
        conn: Optional OMERO connection object
        
    Returns:
        dict: Status information including actions count and blocked status
    """
    try:
        now = time.time()
        key = _get_user_key(request, conn=conn)
        data = _cache_get(key) or {}
        actions = data.get("actions", [])
        
        if not isinstance(actions, list):
            actions = []
        
        # Filter to current window
        actions = [
            ts for ts in actions
            if isinstance(ts, (int, float))
            and now - ts <= MAJOR_ACTION_WINDOW_SECONDS
        ]
        
        blocked_until = data.get("blocked_until", 0)
        if not isinstance(blocked_until, (int, float)):
            blocked_until = 0
        
        is_blocked = now < blocked_until
        remaining = max(0, blocked_until - now) if is_blocked else 0
        
        return {
            "key": key,
            "actions_count": len(actions),
            "limit": MAJOR_ACTION_LIMIT,
            "window_seconds": MAJOR_ACTION_WINDOW_SECONDS,
            "remaining_actions": max(0, MAJOR_ACTION_LIMIT - len(actions)),
            "is_blocked": is_blocked,
            "blocked_until": blocked_until if is_blocked else None,
            "remaining_block_time": remaining if is_blocked else 0,
        }
    except Exception as exc:
        logger.exception(f"Failed to get rate limit status: {exc}")
        return {"error": str(exc)}
