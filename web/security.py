"""Rate limiting, security headers and payload limits.

The threat model for a simulator is unusual: the expensive resource is CPU,
not a database. A single request asking for a long run at a fine timestep can
cost more than thousands of page views, so the simulation endpoint is bounded
by total integration steps as well as by request rate.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from flask import jsonify, request


@dataclass
class _Bucket:
    tokens: float
    last: float


class RateLimiter:
    """Token bucket keyed by client and endpoint.

    In-process and therefore per-worker: it is a guard against casual abuse
    and runaway clients, not a substitute for an edge rate limiter in front of
    a public deployment. That limitation is stated rather than implied.
    """

    def __init__(self, per_minute: int, burst: int) -> None:
        self.rate = per_minute / 60.0
        self.burst = float(burst)
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _client(self) -> str:
        # request.remote_addr only. X-Forwarded-For is attacker controlled
        # unless a trusted proxy is configured, and trusting it blindly would
        # let anyone bypass the limit with a spoofed header.
        return request.remote_addr or "unknown"

    def _sweep(self, now: float) -> None:
        """Drop idle buckets so the table cannot grow without bound."""
        if now - self._last_sweep < 300.0:
            return
        stale = [k for k, b in self._buckets.items() if now - b.last > 900.0]
        for k in stale:
            del self._buckets[k]
        self._last_sweep = now

    def check(self, scope: str, cost: float = 1.0) -> float | None:
        """Consume `cost` tokens. Returns None if allowed, else retry seconds."""
        now = time.monotonic()
        key = (self._client(), scope)
        with self._lock:
            self._sweep(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.burst, last=now)
                self._buckets[key] = bucket

            elapsed = now - bucket.last
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
            bucket.last = now

            if bucket.tokens < cost:
                deficit = cost - bucket.tokens
                return max(1.0, deficit / self.rate)
            bucket.tokens -= cost
            return None


def too_many_requests(retry_after: float):
    response = jsonify({
        "error": "rate_limited",
        "message": "Too many requests. Please wait a moment and try again.",
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(int(retry_after))
    return response


def build_csp(analytics_origin: str | None = None) -> str:
    """Content Security Policy for this deployment.

    Everything is same origin. The only way an external origin enters the
    policy is when the operator has explicitly enabled analytics AND supplied
    a script URL, and then only that one origin is added, to script-src alone.
    """
    script = "script-src 'self'"
    connect = "connect-src 'self'"
    if analytics_origin:
        script += f" {analytics_origin}"
        connect += f" {analytics_origin}"
    return "; ".join([
        "default-src 'self'",
        script,
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        connect,
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    ])


CSP = "; ".join([
    "default-src 'self'",
    # No inline script and no external script. Everything the page runs is
    # served from this origin as a file, which makes the policy meaningful
    # rather than decorative.
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
])


def apply_security_headers(response, https: bool = False, csp: str | None = None):
    response.headers.setdefault("Content-Security-Policy", csp or CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), interest-cohort=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if https:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response
