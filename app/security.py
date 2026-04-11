"""
Security utilities (rate limiting, IP detection)
"""
from __future__ import annotations

import time
from typing import Optional

from flask import abort, current_app, request
from flask_login import current_user

from app.extensions import cache


def _get_client_ip() -> Optional[str]:
    """Resolve client IP address with proxy headers support."""
    if current_app.config.get('RATE_LIMIT_TRUST_PROXY_HEADERS', False):
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            # X-Forwarded-For can be a comma-separated list. Use the first hop.
            ip = forwarded.split(',')[0].strip()
            if ip:
                return ip
        real_ip = request.headers.get('X-Real-IP', '').strip()
        if real_ip:
            return real_ip
    return request.remote_addr


def _incr_with_ttl(key: str, ttl_seconds: int) -> int:
    """Increment a counter with TTL, using Redis if available."""
    redis_client = current_app.extensions.get('redis_client')
    if redis_client is not None:
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, ttl_seconds)
            return int(count)
        except Exception as exc:
            current_app.logger.warning(f'Redis unavailable for rate limiting; falling back to cache: {exc}')

    # Fallback to Flask-Caching (best-effort, non-atomic).
    count = cache.get(key) or 0
    count += 1
    cache.set(key, count, timeout=ttl_seconds)
    return int(count)


def enforce_rate_limit() -> None:
    """Apply per-IP and per-user rate limits."""
    if not current_app.config.get('RATE_LIMIT_ENABLED', True):
        return

    endpoint = request.endpoint or ''
    if endpoint in current_app.config.get('RATE_LIMIT_EXEMPT_ENDPOINTS', ()):
        return

    window = int(current_app.config.get('RATE_LIMIT_WINDOW_SECONDS', 60))
    per_ip = int(current_app.config.get('RATE_LIMIT_PER_IP', 180))
    per_user = int(current_app.config.get('RATE_LIMIT_PER_USER', 120))
    bucket = int(time.time()) // max(1, window)

    if per_ip > 0:
        ip = _get_client_ip()
        if ip:
            key = f'rl:ip:{ip}:{bucket}'
            if _incr_with_ttl(key, window) > per_ip:
                abort(429)

    if per_user > 0 and current_user.is_authenticated:
        key = f'rl:user:{current_user.id}:{bucket}'
        if _incr_with_ttl(key, window) > per_user:
            abort(429)
