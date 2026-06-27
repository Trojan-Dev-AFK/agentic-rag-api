"""Runtime request controls backed by Redis (rate limits and idempotency cache)."""

from __future__ import annotations

import hashlib
import json

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_redis_client: Redis | None = None


def _get_redis_client() -> Redis:
    """Return a process-level Redis client for runtime controls."""
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    return _redis_client


def cache_key_hash(raw: str) -> str:
    """Return a short deterministic hash for long cache key payloads."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def rate_limit_exceeded(*, key: str, limit: int, window_seconds: int) -> bool:
    """Return True when a key exceeds the configured request budget in the window."""
    if limit <= 0 or window_seconds <= 0:
        return False

    try:
        client = _get_redis_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        return count > limit
    except Exception as exc:
        # Fail open to preserve API availability if Redis is transiently unavailable.
        logger.warning("Rate limiter unavailable — allowing request", extra={"key": key}, exc_info=exc)
        return False


async def idempotency_get(*, key: str) -> tuple[str, str] | None:
    """Return cached (response, conversation_id) for an idempotency key when available."""
    try:
        client = _get_redis_client()
        raw = await client.get(key)
        if not raw:
            return None
        payload = json.loads(raw)
        response = payload.get("response")
        conversation_id = payload.get("conversation_id")
        if not isinstance(response, str) or not isinstance(conversation_id, str):
            return None
        return response, conversation_id
    except Exception as exc:
        logger.warning("Idempotency read unavailable — bypassing cache", extra={"key": key}, exc_info=exc)
        return None


async def idempotency_set(*, key: str, response: str, conversation_id: str, ttl_seconds: int) -> None:
    """Cache idempotent response payload for a bounded time window."""
    if ttl_seconds <= 0:
        return

    try:
        client = _get_redis_client()
        payload = json.dumps({"response": response, "conversation_id": conversation_id})
        await client.setex(key, ttl_seconds, payload)
    except Exception as exc:
        logger.warning("Idempotency write unavailable — continuing", extra={"key": key}, exc_info=exc)


async def cache_get_text(*, key: str) -> str | None:
    """Get cached text payload by key."""
    try:
        client = _get_redis_client()
        return await client.get(key)
    except Exception as exc:
        logger.warning("Cache read unavailable — bypassing", extra={"key": key}, exc_info=exc)
        return None


async def cache_set_text(*, key: str, value: str, ttl_seconds: int) -> None:
    """Set cached text payload with TTL."""
    if ttl_seconds <= 0:
        return
    try:
        client = _get_redis_client()
        await client.setex(key, ttl_seconds, value)
    except Exception as exc:
        logger.warning("Cache write unavailable — continuing", extra={"key": key}, exc_info=exc)


async def cache_get_json(*, key: str) -> dict | list | None:
    """Get cached JSON payload by key."""
    raw = await cache_get_text(key=key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


async def cache_set_json(*, key: str, payload: dict | list, ttl_seconds: int) -> None:
    """Set cached JSON payload with TTL."""
    await cache_set_text(key=key, value=json.dumps(payload), ttl_seconds=ttl_seconds)


async def cache_delete_prefix(*, prefix: str) -> int:
    """Delete all cache keys with a given prefix and return deleted count."""
    deleted = 0
    try:
        client = _get_redis_client()
        keys: list[str] = []
        async for key in client.scan_iter(match=f"{prefix}*"):
            keys.append(key)
        if keys:
            deleted = int(await client.delete(*keys))
    except Exception as exc:
        logger.warning("Cache invalidation unavailable — continuing", extra={"prefix": prefix}, exc_info=exc)
    return deleted


def token_session_cache_key(*, jti: str) -> str:
    """Build cache key for token-session validation state."""
    return f"cache:token-session:{jti}"


async def token_session_cache_get(*, jti: str) -> str | None:
    """Get cached user_id for a valid token session by jti."""
    return await cache_get_text(key=token_session_cache_key(jti=jti))


async def token_session_cache_set(*, jti: str, user_id: str, ttl_seconds: int) -> None:
    """Cache valid token-session user mapping for short TTL."""
    await cache_set_text(key=token_session_cache_key(jti=jti), value=user_id, ttl_seconds=ttl_seconds)


async def token_session_cache_delete(*, jti: str) -> None:
    """Remove token-session cache entry immediately (logout/revoke path)."""
    try:
        client = _get_redis_client()
        await client.delete(token_session_cache_key(jti=jti))
    except Exception as exc:
        logger.warning("Token-session cache delete unavailable", extra={"jti": jti}, exc_info=exc)


async def redis_ping() -> bool:
    """Return True when Redis responds to a ping."""
    try:
        client = _get_redis_client()
        return bool(await client.ping())
    except Exception:
        return False
