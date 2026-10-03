"""Foreign-exchange rates for display conversion.

Stored amounts keep the currency their provider quoted. When the viewer's
preferred currency differs, the API converts for display and says which rate
was used:

* LIVE - fetched from the rate source (Frankfurter, the ECB reference-rate
  API; no key required).
* CACHED - a previously fetched rate still inside its TTL, with fetch time.

There is no fallback rate table. If no rate can be fetched, the amount is shown
in the currency it was stored in, unconverted: ReTryp never applies an invented
rate to a real figure. Conversion never changes what is stored or what a plan
costs; it only changes how it is displayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from ..config import Settings
from .base import NotConfigured, ProviderError, registry

USER_AGENT = "ReTryp/1.0 (contact: ops@retryp.example)"


@dataclass(frozen=True, slots=True)
class RateSet:
    """Rates expressed as ``1 base = rate[currency]``."""

    base: str
    rates: dict[str, float]
    provenance: str
    as_of: datetime | None

    def rate_to(self, target: str) -> float | None:
        target = target.upper()
        if target == self.base:
            return 1.0
        return self.rates.get(target)


async def get_rates(settings: Settings) -> RateSet | None:
    """Return rates for the configured base currency, or ``None`` if unavailable.

    ``None`` means "do not convert". The caller then shows each amount in its
    stored currency rather than applying a rate it could not fetch.
    """
    if not settings.fx_enabled:
        return None

    base = settings.fx_base_currency.upper()
    client = registry.client(
        "fx",
        ttl_seconds=float(settings.fx_cache_ttl_seconds),
        configured=True,
        failure_threshold=2,
        reset_seconds=120.0,
    )
    key = client.cache_key("latest", base)

    async def fetch() -> dict:
        # The symbol set is the currencies the UI can display. It is a request
        # parameter, not a rate table: no value comes from it.
        symbols = [c.upper() for c in settings.fx_display_currencies if c.upper() != base]
        async with httpx.AsyncClient(
            timeout=settings.fx_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as http:
            response = await http.get(
                f"{settings.fx_base_url.rstrip('/')}/latest",
                params={"from": base, "to": ",".join(symbols)},
            )
            if response.status_code == 429:
                raise ProviderError("fx rate source rate limit", retryable=True)
            response.raise_for_status()
            return response.json()

    try:
        payload, provenance, fetched_at = await client.get(key, fetch)
    except (ProviderError, NotConfigured):
        return None

    rates = {base: 1.0}
    for code, value in (payload.get("rates") or {}).items():
        try:
            rates[code.upper()] = float(value)
        except (TypeError, ValueError):
            continue
    if len(rates) <= 1:
        return None

    as_of = fetched_at
    payload_date = payload.get("date")
    if payload_date:
        try:
            as_of = datetime.fromisoformat(str(payload_date)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return RateSet(base=base, rates=rates, provenance=provenance, as_of=as_of)
