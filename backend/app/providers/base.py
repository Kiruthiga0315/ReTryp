"""Provider plumbing: caching, backoff, circuit breaking, provenance.

Every external call goes through ``ResilientClient``. The rules:

* A cache hit inside the TTL is served as ``CACHED`` with its fetch time.
* On failure the circuit opens after ``FAILURE_THRESHOLD`` consecutive
  errors and half-opens after ``RESET_SECONDS``.
* On failure the caller falls back to a stored cached reading, and the
  provenance says so. Nothing is invented.

No API key is ever returned to, or read by, the frontend.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


class ProviderError(RuntimeError):
    """Raised when a provider cannot serve a request."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class RateLimited(ProviderError):
    def __init__(self, message: str = "provider rate limit reached") -> None:
        super().__init__(message, retryable=True)


class NotConfigured(ProviderError):
    """Raised when the provider has no credentials. Never retried."""

    def __init__(self, message: str = "provider is not configured") -> None:
        super().__init__(message, retryable=False)


def _as_int(value: str | None, fallback: int | None) -> int | None:
    """A provider header as an int, keeping the previous value if unusable."""
    if value is None:
        return fallback
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _is_retryable(exc: Exception) -> bool:
    """A provider error is retried unless it says otherwise or is a 4xx.

    A client error (400/401/403/404) will not succeed on a retry, so retrying
    it only delays the caller. 408 and 429 are the exceptions: they are
    transient by definition.
    """
    explicit = getattr(exc, "retryable", None)
    if explicit is False:
        return False
    # A per-minute quota cannot be waited out inside a single request, and the
    # caller is blocked for the whole wait. Fail fast and let the circuit
    # breaker and the cache handle the next call.
    if isinstance(exc, RateLimited):
        return False
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int) and 400 <= status < 500 and status not in (408, 429):
        return False
    return True


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CacheEntry(Generic[T]):
    value: T
    stored_at: float
    fetched_at: datetime


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_seconds: float = 60.0
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at is not None and time.monotonic() - self.opened_at >= self.reset_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # half-open: allow a single probe

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == CircuitState.HALF_OPEN or self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


@dataclass
class ProviderStatus:
    name: str
    configured: bool
    circuit: CircuitState
    failures: int
    last_error: str | None = None
    last_success_at: datetime | None = None


@dataclass
class ResilientClient:
    """Wraps one provider's fetch call with cache, retry and a breaker."""

    name: str
    ttl_seconds: float = 900.0
    max_attempts: int = 3
    base_backoff_seconds: float = 0.4
    configured: bool = True
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    _cache: dict[str, CacheEntry] = field(default_factory=dict)
    # Keys that recently failed with a non-retryable error, so a repeat call
    # fails at once instead of making the caller wait out the rate gate again.
    _failed: dict[str, float] = field(default_factory=dict)
    negative_ttl_seconds: float = 120.0
    last_error: str | None = None
    last_success_at: datetime | None = None
    # The provider's own accounting of the remaining calls, read from its
    # response headers. A metered plan answers a fixed number of calls for a
    # long period (AviationStack's free plan allows 100 a month), so the
    # caller needs to know the budget before spending it, not after.
    quota_limit: int | None = None
    quota_remaining: int | None = None

    def note_quota(self, limit: str | None, remaining: str | None) -> None:
        """Record the provider's quota headers, when it sends them."""
        self.quota_limit = _as_int(limit, self.quota_limit)
        self.quota_remaining = _as_int(remaining, self.quota_remaining)

    def cache_key(self, *parts: Any) -> str:
        return "|".join(str(p) for p in parts)

    def peek_cache(self, key: str) -> CacheEntry | None:
        return self._cache.get(key)

    def fresh_cache(self, key: str) -> CacheEntry | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at > self.ttl_seconds:
            return None
        return entry

    async def get(
        self,
        key: str,
        fetch: Callable[[], Awaitable[T]],
        *,
        allow_stale: bool = True,
    ) -> tuple[T, str, datetime | None]:
        """Return ``(value, provenance, fetched_at)``.

        Provenance is LIVE or CACHED. Deciding what to do when neither is
        available is the caller's job, because only the caller knows whether a
        value can be left unavailable.
        """
        fresh = self.fresh_cache(key)
        if fresh is not None:
            return fresh.value, "CACHED", fresh.fetched_at

        failed_at = self._failed.get(key)
        if failed_at is not None and time.monotonic() - failed_at < self.negative_ttl_seconds:
            raise ProviderError(f"{self.name} recently failed for this query", retryable=False)

        if not self.configured:
            raise NotConfigured(f"{self.name} is not configured")

        if not self.breaker.allow():
            stale = self.peek_cache(key)
            if stale is not None and allow_stale:
                return stale.value, "CACHED", stale.fetched_at
            raise ProviderError(f"{self.name} circuit is open", retryable=True)

        last_exc: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                value = await fetch()
            except NotConfigured:
                raise
            except Exception as exc:  # noqa: BLE001 - provider boundary
                last_exc = exc
                self.breaker.record_failure()
                self.last_error = str(exc)
                if not _is_retryable(exc):
                    self._failed[key] = time.monotonic()
                    break
                if attempt < self.max_attempts - 1:
                    # Exponential backoff with full jitter.
                    delay = self.base_backoff_seconds * (2**attempt)
                    await asyncio.sleep(random.uniform(0, delay))
                continue

            now = datetime.now(timezone.utc)
            self._cache[key] = CacheEntry(value=value, stored_at=time.monotonic(), fetched_at=now)
            self._failed.pop(key, None)
            self.breaker.record_success()
            self.last_success_at = now
            self.last_error = None
            return value, "LIVE", now

        stale = self.peek_cache(key)
        if stale is not None and allow_stale:
            return stale.value, "CACHED", stale.fetched_at
        raise ProviderError(f"{self.name} failed: {last_exc}", retryable=True)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            configured=self.configured,
            circuit=self.breaker.state,
            failures=self.breaker.failures,
            last_error=self.last_error,
            last_success_at=self.last_success_at,
        )


class ProviderRegistry:
    """Keeps one resilient client per provider so state survives requests."""

    def __init__(self) -> None:
        self._clients: dict[str, ResilientClient] = {}

    def client(
        self,
        name: str,
        *,
        ttl_seconds: float,
        configured: bool = True,
        failure_threshold: int = 3,
        reset_seconds: float = 60.0,
    ) -> ResilientClient:
        existing = self._clients.get(name)
        if existing is not None:
            return existing
        client = ResilientClient(
            name=name,
            ttl_seconds=ttl_seconds,
            configured=configured,
            breaker=CircuitBreaker(
                failure_threshold=failure_threshold, reset_seconds=reset_seconds
            ),
        )
        self._clients[name] = client
        return client

    def all_statuses(self) -> list[ProviderStatus]:
        return [c.status() for c in self._clients.values()]


registry = ProviderRegistry()


def demote(provenance: str, requested: str) -> str:
    """Never let a lower-trust source masquerade as a higher one."""
    order = {"LIVE": 4, "CACHED": 3, "REFERENCE": 2, "SIMULATED": 1, "UNAVAILABLE": 0}
    return provenance if order.get(provenance, 0) <= order.get(requested, 0) else requested
