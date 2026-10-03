"""Flight schedule providers.

Interchangeable implementations behind one interface:

* ``AviationStackProvider`` - scheduled services by airport and date.
* ``AeroDataBoxProvider`` - airport departure boards for any pair.
* ``FlightAwareAeroAPIProvider`` - paid per query.

There is no demo provider. With no key configured the factory returns a
provider that reports itself as unconfigured, and the caller surfaces a
"schedule provider required" state. ReTryp never invents a flight.

Schedule data is real; a schedule API sells no fares, so every replacement
flight is priced as a planning estimate and the note says so.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from ..config import Settings
from ..domain.enums import SegmentType
from ..domain.itineraries import Itinerary
from ..domain.options import OptionSegment
from ..domain.reference import PLACES, require_place
from ..domain.timeutil import zone_for
from .base import NotConfigured, ProviderError, RateLimited, registry

USER_AGENT = "ReTryp/1.0 (+https://retryp.example)"

# AeroDataBox caps a departure window at 12 hours. Anything longer is rejected
# with HTTP 400, so every request stays inside this bound. A day is walked in
# chunks of that size so an evening long-haul bank is not cut off.
WINDOW_HOURS = 12
WINDOW_CHUNK_HOURS = 12
DAY_HOURS = 24

# A schedule API has no fare feed, so a replacement flight is priced as an
# estimate. The figure is a planning allowance, never a quote.
ESTIMATED_FARE_MINOR = 14_000


@dataclass(slots=True)
class ConnectionCandidates:
    """Hub itineraries found for one pair, with the calls the search spent.

    ``itineraries`` are already timed against the hub's minimum connection
    time; ``calls_spent`` lets the caller account for a metered plan.
    """

    itineraries: list[Itinerary] = field(default_factory=list)
    hubs_tried: list[str] = field(default_factory=list)
    calls_spent: int = 0


# A provider may expose how much of its metered allowance is left. Both hooks
# are optional: a provider without a meter simply has no budget to respect.
def _budget_available(provider: object, *, needed: int) -> bool:
    check = getattr(provider, "budget_available", None)
    if callable(check):
        return bool(check(needed=needed))
    return True


async def _connections_via(
    provider: object,
    *,
    origin: str,
    destination: str,
    depart_after_utc: datetime,
    max_hubs: int,
    direct: list[OptionSegment],
) -> ConnectionCandidates:
    """Hub itineraries for a pair, fetching legs through ``provider``.

    Each hub costs one call in each direction. ``max_hubs`` caps how many are
    tried, and the provider's own budget is checked before spending, so a
    metered plan is never drained by one search.
    """
    result = ConnectionCandidates()
    if max_hubs <= 0:
        return result

    origin_iata = _iata_for(origin)
    destination_iata = _iata_for(destination)
    if not origin_iata or not destination_iata:
        return result

    from ..domain import itineraries as itinerary_mod

    hubs = [
        code
        for code in itinerary_mod.hub_candidates(origin_iata, destination_iata)
        if code != destination_iata
    ][:max_hubs]
    if not hubs or not _budget_available(provider, needed=2 * len(hubs)):
        return result

    search = getattr(provider, "search_pair_only", None)
    if search is None:
        return result

    for hub in hubs:
        try:
            first = await search(origin=origin_iata, destination=hub, depart_after_utc=depart_after_utc)
            second = await search(
                origin=hub, destination=destination_iata, depart_after_utc=depart_after_utc
            )
        except (ProviderError, NotConfigured):
            break
        result.calls_spent += 2
        result.hubs_tried.append(hub)
        result.itineraries.extend(
            itinerary_mod.flight_itineraries(
                origin_iata, destination_iata, hub, first, second
            )
        )
    return result


def _iata_for(code: str) -> str | None:
    """The IATA code to query for a place, only for real airports."""
    place = PLACES.get(code)
    if place is None or place.kind != "airport":
        return None
    return code if len(code) == 3 else None


def _markets_for(code: str) -> set[str]:
    """The city market a destination code stands for.

    A station or satellite airport maps to its city, so asking for BER matches
    an arrival at Berlin Brandenburg Airport station as well as the airport.
    """
    place = PLACES.get(code)
    return {place.market} if place else set()


def _carrier_code(designator: str) -> str:
    """The airline code at the start of a flight designator.

    An IATA code is two characters and may contain a digit - ``6E2369`` is
    IndiGo, ``B62220`` is JetBlue, ``U24584`` is easyJet - so taking only the
    letters turns ``6E`` into ``E``. A three-letter designator is an ICAO-style
    form such as ``DLH759``.
    """
    text = (designator or "").upper().strip()
    if len(text) >= 2 and text[:2].isalnum() and text[2:3].isdigit():
        return text[:2]
    if len(text) >= 3 and text[:3].isalpha() and text[3:4].isdigit():
        return text[:3]
    letters = "".join(ch for ch in text if ch.isalpha())
    return letters[:2] or (text[:2] if text[:2] else "??")


def _within_schedule_window(day: date, tz) -> bool:
    """Whether ``flightsFuture`` will accept ``day`` for an airport in ``tz``.

    The endpoint documents its window as tomorrow through the next seven days,
    counted in the airport's local calendar, and rejects any other date with a
    validation error. The window is evaluated here so an out-of-range date is
    never sent.
    """
    today = datetime.now(timezone.utc).astimezone(tz).date()
    return today < day <= today + timedelta(days=7)


class FlightProvider(Protocol):
    name: str

    async def status(self, *, service_number: str, on_date: str) -> dict:
        """Return a normalised status dict for one flight on one date."""
        ...

    async def search(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Return bookable options after a given instant."""
        ...

    async def search_pair_only(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Direct options for one exact pair, with no fallback search.

        Used when timing a connection through a hub, where only the pair's own
        services are relevant and a missing answer should stay missing.
        """
        ...

    async def find_connections(
        self,
        *,
        origin: str,
        destination: str,
        depart_after_utc: datetime,
        max_hubs: int,
    ) -> ConnectionCandidates:
        """Direct options plus up-to-two-leg itineraries through a hub.

        One call answers the direct pair; further calls, capped by ``max_hubs``,
        time a connection through a hub. A provider that cannot separate the two
        legs returns the direct options with no itineraries.
        """
        ...


@dataclass
class UnconfiguredFlightProvider:
    """The provider used when no schedule key is set.

    It is not a demo source. It answers every call with ``NotConfigured`` so
    the API can tell the traveller that a schedule provider is required,
    instead of returning invented flights.
    """

    name: str = "unconfigured"
    configured: bool = False
    reason: str = (
        "No flight schedule provider is configured. Set FLIGHT_PROVIDER and the "
        "matching API key to search real services."
    )

    async def status(self, *, service_number: str, on_date: str) -> dict:
        raise NotConfigured(self.reason)

    async def search(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        raise NotConfigured(self.reason)

    async def search_pair_only(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        raise NotConfigured(self.reason)

    async def find_connections(
        self,
        *,
        origin: str,
        destination: str,
        depart_after_utc: datetime,
        max_hubs: int,
    ) -> ConnectionCandidates:
        raise NotConfigured(self.reason)


class _RateGate:
    """Spaces bursts of calls to a provider.

    This is politeness, not the plan limit. AviationStack's free plan is
    metered over a long period (one hundred calls a month), which no wait can
    escape, so the budget is tracked separately and calls stop before it runs
    out. What the gate guards against is hammering the endpoint with several
    requests in the same instant when a journey build searches a few legs.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            remaining = self._interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_call = time.monotonic()


# One gate per provider process-wide, because the limit is per key.
_aviationstack_gate = _RateGate(min_interval_seconds=1.0)


class AeroDataBoxProvider:
    """AeroDataBox via RapidAPI.

    TODO: verify - free-tier request volume and endpoint shapes change; confirm
    against the current RapidAPI listing before relying on this in production.
    """

    name = "aerodatabox"

    def __init__(self, api_key: str, host: str = "aerodatabox.p.rapidapi.com") -> None:
        if not api_key:
            raise NotConfigured("AERODATABOX_API_KEY is not set")
        self._host = host
        self._headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host,
            "User-Agent": USER_AGENT,
        }

    async def status(self, *, service_number: str, on_date: str) -> dict:
        client = registry.client("aerodatabox", ttl_seconds=300)
        url = f"https://{self._host}/flights/number/{service_number}/{on_date}"

        async def fetch() -> dict:
            async with httpx.AsyncClient(timeout=15) as http:
                response = await http.get(url, headers=self._headers)
                if response.status_code == 429:
                    from .base import RateLimited

                    raise RateLimited("AeroDataBox rate limit")
                response.raise_for_status()
                return response.json()

        value, provenance, fetched_at = await client.get(client.cache_key(service_number, on_date), fetch)
        return _normalise_aerodatabox(value, provenance, fetched_at)

    async def search_pair_only(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Same as :meth:`search`; AeroDataBox has no pair-only endpoint."""
        return await self.search(
            origin=origin, destination=destination, depart_after_utc=depart_after_utc
        )

    async def find_connections(
        self,
        *,
        origin: str,
        destination: str,
        depart_after_utc: datetime,
        max_hubs: int,
    ) -> ConnectionCandidates:
        """Direct services plus hub itineraries, within a hub budget."""
        direct = await self.search(
            origin=origin, destination=destination, depart_after_utc=depart_after_utc
        )
        return await _connections_via(
            self,
            origin=origin,
            destination=destination,
            depart_after_utc=depart_after_utc,
            max_hubs=max_hubs,
            direct=direct,
        )

    async def search(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Real schedules for any pair, read from the origin's departure board.

        AeroDataBox has no origin/destination endpoint, so this calls the
        airport departures window and keeps the rows whose arrival airport
        matches the destination market. The API caps one window at 12 hours, so
        a full day is walked in 12-hour chunks: without that, a long-haul bank
        that departs in the evening of the origin's local day falls outside the
        window and the pair looks unserved. Schedules are real; fares are not
        sold here, so every option is priced as an estimate and says so.
        """
        client = registry.client("aerodatabox", ttl_seconds=300)
        origin_iata = _iata_for(origin)
        destination_markets = _markets_for(destination)
        if not origin_iata or not destination_markets:
            return []

        day_start = depart_after_utc
        local_start = day_start.astimezone(zone_for(origin_iata))
        cache_key = client.cache_key(
            "search", origin_iata, local_start.date().isoformat(), local_start.hour
        )

        async def fetch() -> list[dict]:
            return await self._departures_day(origin_iata, day_start)

        try:
            rows, provenance, fetched_at = await client.get(cache_key, fetch, allow_stale=True)
        except (ProviderError, NotConfigured):
            return []

        from ..domain import graph

        options: list[OptionSegment] = []
        for row in rows:
            arrival_code = (row.get("arrival", {}).get("airport", {}) or {}).get("iata")
            if not arrival_code or arrival_code not in PLACES:
                continue
            if require_place(arrival_code).market not in destination_markets:
                continue
            option = _option_from_aerodatabox(row, provenance, fetched_at, fallback_origin=origin_iata)
            if option is None or option.departure_utc < depart_after_utc:
                continue
            options.append(option)
            graph.record_live_pair(origin_iata, arrival_code)

        options.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
        return options

    async def _departures_day(self, origin_iata: str, start: datetime) -> list[dict]:
        """A 24-hour departure board, walked in the API's 12-hour chunk size.

        The endpoint reads its window as the airport's **local** wall clock, so
        a UTC instant is converted to the origin's zone before formatting. Each
        chunk boundary is converted from the same UTC base, which keeps the walk
        correct across a DST change rather than adding hours to a local time.

        A chunk that fails does not lose the rest: the rows already collected
        are returned, so a transient error on one window still answers.
        """
        tz = zone_for(origin_iata)
        rows: list[dict] = []
        for offset in range(0, DAY_HOURS, WINDOW_CHUNK_HOURS):
            chunk_start = (start + timedelta(hours=offset)).astimezone(tz)
            chunk_end = (start + timedelta(hours=offset + WINDOW_CHUNK_HOURS)).astimezone(tz)
            try:
                rows += await self._departures_window(
                    origin_iata,
                    chunk_start.replace(tzinfo=None),
                    chunk_end.replace(tzinfo=None),
                )
            except RateLimited:
                raise
            except ProviderError:
                continue
        return rows

    async def _departures_window(
        self, origin_iata: str, start: datetime, end: datetime
    ) -> list[dict]:
        """One airport departure window. The API caps a window at 12 hours."""
        url = (
            f"https://{self._host}/flights/airports/iata/{origin_iata}/"
            f"{start:%Y-%m-%dT%H:%M}/{end:%Y-%m-%dT%H:%M}"
        )
        params = {"direction": "Departure", "withLeg": "true", "withCancelled": "false"}
        async with httpx.AsyncClient(timeout=25) as http:
            response = await http.get(url, headers=self._headers, params=params)
            if response.status_code == 429:
                from .base import RateLimited

                raise RateLimited("AeroDataBox rate limit")
            if response.status_code == 400:
                # Window too long or no data for the range: not retryable.
                raise ProviderError("AeroDataBox rejected the window", retryable=False)
            response.raise_for_status()
            return response.json().get("departures") or []


class AviationStackProvider:
    """AviationStack scheduled services.

    ``/flights`` answers an exact origin/destination pair from the real-time
    board, which the free plan serves. ``flightsFuture`` returns a published
    schedule for one airport, but the free plan restricts it, so it is only
    tried as a fallback and a restriction is reported rather than hidden.

    The free plan is metered over a long period — the response carries
    ``x-quota-limit`` and ``x-quota-remaining`` and the allowance is a hundred
    calls a month, not a hundred a minute. Every call therefore records the
    remaining budget, a journey build spends only a few calls, and calls stop
    with a clear reason once the meter is nearly empty instead of the app
    looking empty for no stated cause.

    TODO: verify - the paid plans change both the quota and the endpoint shape;
    confirm against the current AviationStack pricing before relying on this
    at volume.
    """

    name = "aviationstack"

    def __init__(self, api_key: str, base_url: str = "http://api.aviationstack.com/v1") -> None:
        if not api_key:
            raise NotConfigured("AVIATIONSTACK_API_KEY is not set")
        self._key = api_key
        self._base = base_url

    def _client(self, ttl_seconds: float):
        return registry.client("aviationstack", ttl_seconds=ttl_seconds)

    def quota(self) -> tuple[int | None, int | None]:
        """``(limit, remaining)`` as last reported by the provider."""
        client = registry.client("aviationstack", ttl_seconds=1800)
        return client.quota_limit, client.quota_remaining

    def budget_available(self, *, needed: int) -> bool:
        """Whether the meter can cover ``needed`` more calls.

        Unknown quota (no call made yet this process) counts as available: the
        first call is what discovers the meter, and refusing it would deadlock.
        """
        _, remaining = self.quota()
        if remaining is None:
            return True
        return remaining >= needed

    async def _get(self, url: str, params: dict) -> dict:
        """One metered GET, recording the quota headers it returns."""
        await _aviationstack_gate.wait()
        async with httpx.AsyncClient(timeout=25) as http:
            response = await http.get(url, params=params, headers={"User-Agent": USER_AGENT})
            self._client(1800).note_quota(
                response.headers.get("x-quota-limit"),
                response.headers.get("x-quota-remaining"),
            )
            if response.status_code == 429:
                raise RateLimited("AviationStack rate limit")
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                error = payload["error"]
                code = error.get("code") if isinstance(error, dict) else None
                message = error.get("message") if isinstance(error, dict) else error
                # A plan that does not include a function is a permanent
                # answer, not a transient failure: keep it off the breaker.
                raise ProviderError(str(message), retryable=code != "function_access_restricted")
            return payload

    async def status(self, *, service_number: str, on_date: str) -> dict:
        client = self._client(300)
        url = f"{self._base}/flights"
        params = {"access_key": self._key, "flight_iata": service_number, "flight_date": on_date}

        async def fetch() -> dict:
            return await self._get(url, params)

        value, provenance, fetched_at = await client.get(
            client.cache_key(service_number, on_date), fetch
        )
        return _normalise_aviationstack(value, provenance, fetched_at)

    async def search(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Direct services between the two places, asked for as an exact pair.

        The provider is queried for ``dep_iata``/``arr_iata`` together, so every
        row it returns is a direct service on that pair by construction. That is
        preferred over reading the origin's whole departure board and hoping the
        leg appears in it. If the pair query answers with nothing (for example a
        date outside the real-time window), the departure board is tried as a
        fallback so a future date can still be recovered.
        """
        direct = await self._search_direct_pair(origin, destination, depart_after_utc)
        if direct:
            return direct
        return await self._search_departures(origin, destination, depart_after_utc)

    async def search_pair_only(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Direct services for one pair, without the schedule fallback.

        This is used when timing a connection through a hub, where each leg is
        an exact pair and a leg the real-time board cannot answer should simply
        not appear. It spends at most one metered call, and none at all when the
        answer is already cached.
        """
        return await self._search_direct_pair(origin, destination, depart_after_utc)

    async def find_connections(
        self,
        *,
        origin: str,
        destination: str,
        depart_after_utc: datetime,
        max_hubs: int,
    ) -> ConnectionCandidates:
        """Direct services plus itineraries through a hub, within a budget.

        One metered call answers the direct pair. Each hub then costs one more
        call on the origin-to-hub and one on the hub-to-destination leg, so the
        total is bounded by ``1 + 2 * max_hubs`` and no further. Hubs are taken
        from the connectivity graph, busiest first, and only those that leave a
        feasible connection are returned.
        """
        direct = await self._search_direct_pair(origin, destination, depart_after_utc)
        return await _connections_via(
            self,
            origin=origin,
            destination=destination,
            depart_after_utc=depart_after_utc,
            max_hubs=max_hubs,
            direct=direct,
        )

    async def _search_direct_pair(
        self, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """``GET /flights?dep_iata=&arr_iata=`` - the exact pair, direct only."""
        origin_iata = _iata_for(origin)
        destination_iata = _iata_for(destination)
        if not origin_iata or not destination_iata or origin_iata == destination_iata:
            return []

        client = self._client(1800)
        day = depart_after_utc.astimezone(zone_for(origin_iata)).date().isoformat()
        cache_key = client.cache_key("direct", origin_iata, destination_iata, day)

        async def fetch() -> dict:
            return await self._direct_pair_payload(origin_iata, destination_iata)

        try:
            payload, provenance, fetched_at = await client.get(cache_key, fetch, allow_stale=True)
        except (ProviderError, NotConfigured):
            return []

        return self._direct_options_from_payload(
            payload, provenance, fetched_at, origin_iata, destination_iata, day, depart_after_utc
        )

    async def _direct_pair_payload(self, origin_iata: str, destination_iata: str) -> dict:
        """One ``GET /flights`` call for the exact pair, direct services only."""
        return await self._get(
            f"{self._base}/flights",
            {
                "access_key": self._key,
                "dep_iata": origin_iata,
                "arr_iata": destination_iata,
                "limit": 100,
            },
        )

    def _direct_options_from_payload(
        self,
        payload: dict,
        provenance: str,
        fetched_at: datetime | None,
        origin_iata: str,
        destination_iata: str,
        day: str,
        depart_after_utc: datetime,
    ) -> list[OptionSegment]:
        from ..domain import graph

        all_options: list[OptionSegment] = []
        for row in payload.get("data") or []:
            # The real-time endpoint answers for one date; a stale row for
            # another day must not be offered for this departure.
            if row.get("flight_date") and row["flight_date"] != day:
                continue
            option = _option_from_aviationstack(row, provenance, fetched_at)
            if option is None:
                continue
            if option.origin_code != origin_iata or option.destination_code != destination_iata:
                continue
            if option.departure_utc < depart_after_utc:
                continue
            all_options.append(option)
            graph.record_live_pair(origin_iata, destination_iata)

        return _collapse_codeshares(all_options)

    async def _search_departures(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Scheduled services from the origin whose arrival matches the pair.

        The schedule covers the origin's local day, so a full day is requested
        and the rows are filtered to the destination's city market. Any row
        whose scheduled departure is before the requested instant is dropped.
        """
        client = self._client(1800)
        origin_iata = _iata_for(origin)
        destination_markets = _markets_for(destination)
        if not origin_iata or not destination_markets:
            return []

        local_start = depart_after_utc.astimezone(zone_for(origin_iata))
        day = local_start.date()
        cache_key = client.cache_key("schedule", origin_iata, day.isoformat())

        # flightsFuture only accepts tomorrow..+7 days; asking for today or the
        # far future is a validation error, so the date parameter is omitted
        # (the endpoint's default window) rather than sent invalid.
        in_window = _within_schedule_window(day, zone_for(origin_iata))
        params = {
            "access_key": self._key,
            "iataCode": origin_iata,
            "type": "departure",
        }
        if in_window:
            params["date"] = day.isoformat()

        async def fetch() -> dict:
            return await self._get(f"{self._base}/flightsFuture", params)

        # The date the endpoint actually served: its own day when the window
        # was honoured, otherwise whatever default window it answered with.
        served_day = day.isoformat() if in_window else None

        try:
            payload, provenance, fetched_at = await client.get(cache_key, fetch, allow_stale=True)
        except (ProviderError, NotConfigured):
            return []

        from ..domain import graph

        options: list[OptionSegment] = []
        for row in payload.get("data") or []:
            # When the requested day was outside the endpoint's window the
            # default window answered instead, so each row is pinned to the
            # day the caller asked for rather than the day it was published.
            if served_day and (row.get("date") or "") != served_day:
                continue
            arrival = row.get("arrival") or {}
            arrival_code = (arrival.get("iataCode") or "").upper()
            if not arrival_code or arrival_code not in PLACES:
                continue
            if require_place(arrival_code).market not in destination_markets:
                continue
            option = _option_from_flights_future(
                row, provenance, fallback_origin=origin_iata, fallback_date=day
            )
            if option is None or option.departure_utc < depart_after_utc:
                continue
            options.append(option)
            graph.record_live_pair(origin_iata, arrival_code)

        options.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
        return options


class FlightAwareAeroAPIProvider:
    """FlightAware AeroAPI. Paid per query.

    TODO: verify - per-query pricing tiers before enabling by default.
    """

    name = "flightaware"

    def __init__(self, api_key: str, base_url: str = "https://aeroapi.flightaware.com/aeroapi") -> None:
        if not api_key:
            raise NotConfigured("FLIGHTAWARE_API_KEY is not set")
        self._base = base_url
        self._headers = {"x-apikey": api_key, "User-Agent": USER_AGENT}

    async def status(self, *, service_number: str, on_date: str) -> dict:
        client = registry.client("flightaware", ttl_seconds=300)
        url = f"{self._base}/flights/{service_number}"

        async def fetch() -> dict:
            async with httpx.AsyncClient(timeout=15) as http:
                response = await http.get(url, headers=self._headers)
                if response.status_code == 429:
                    from .base import RateLimited

                    raise RateLimited("AeroAPI rate limit")
                response.raise_for_status()
                return response.json()

        value, provenance, fetched_at = await client.get(client.cache_key(service_number, on_date), fetch)
        return _normalise_flightaware(value, provenance, fetched_at)

    async def search_pair_only(
        self, *, origin: str, destination: str, depart_after_utc: datetime
    ) -> list[OptionSegment]:
        """Same as :meth:`search`; AeroAPI has no pair-only endpoint."""
        return await self.search(
            origin=origin, destination=destination, depart_after_utc=depart_after_utc
        )

    async def find_connections(
        self,
        *,
        origin: str,
        destination: str,
        depart_after_utc: datetime,
        max_hubs: int,
    ) -> ConnectionCandidates:
        """Direct services plus hub itineraries, within a hub budget."""
        direct = await self.search(
            origin=origin, destination=destination, depart_after_utc=depart_after_utc
        )
        return await _connections_via(
            self,
            origin=origin,
            destination=destination,
            depart_after_utc=depart_after_utc,
            max_hubs=max_hubs,
            direct=direct,
        )

    async def search(self, *, origin: str, destination: str, depart_after_utc: datetime) -> list[OptionSegment]:
        """Scheduled departures for a pair.

        AeroAPI's scheduled-departures endpoint returns the origin's board; the
        destination filter is applied here the same way as the other providers.

        TODO: verify - the scheduled departures endpoint path and page size
        against the current AeroAPI docs before relying on this in production.
        """
        client = registry.client("flightaware", ttl_seconds=1800)
        origin_iata = _iata_for(origin)
        destination_markets = _markets_for(destination)
        if not origin_iata or not destination_markets:
            return []

        local_start = depart_after_utc.astimezone(zone_for(origin_iata))
        cache_key = client.cache_key("scheduled", origin_iata, local_start.date().isoformat())

        async def fetch() -> dict:
            async with httpx.AsyncClient(timeout=25) as http:
                response = await http.get(
                    f"{self._base}/airports/{origin_iata}/flights/scheduled_departures",
                    params={"start": local_start.replace(tzinfo=None).isoformat()},
                    headers=self._headers,
                )
                if response.status_code == 429:
                    raise RateLimited("AeroAPI rate limit")
                response.raise_for_status()
                return response.json()

        try:
            payload, provenance, _ = await client.get(cache_key, fetch, allow_stale=True)
        except (ProviderError, NotConfigured):
            return []

        from ..domain import graph

        options: list[OptionSegment] = []
        for row in payload.get("scheduled_departures") or payload.get("flights") or []:
            destination_code = (row.get("destination") or "").upper()
            if destination_code not in PLACES:
                continue
            if require_place(destination_code).market not in destination_markets:
                continue
            option = _option_from_flightaware(row, provenance, fallback_origin=origin_iata)
            if option is None or option.departure_utc < depart_after_utc:
                continue
            options.append(option)
            graph.record_live_pair(origin_iata, destination_code)

        options.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
        return options


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _parse_aerodatabox_time(value: str | None) -> datetime | None:
    """AeroDataBox returns "2026-09-28 20:25Z"; accept it or an ISO string."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _option_from_aerodatabox(
    row: dict,
    provenance: str,
    fetched_at: datetime | None,
    *,
    fallback_origin: str | None = None,
) -> OptionSegment | None:
    """One departure row as an option, or ``None`` if it is unusable.

    Uses the revised time when the airline has published one, so a disrupted
    flight shows its real expected departure rather than its schedule. A
    departure-board row omits its own airport - it is implied by the query -
    so ``fallback_origin`` supplies it.
    """
    departure = row.get("departure", {}) or {}
    arrival = row.get("arrival", {}) or {}
    origin_code = (departure.get("airport") or {}).get("iata") or fallback_origin
    destination_code = (arrival.get("airport") or {}).get("iata")
    number_block = row.get("number") or ""
    airline = (row.get("airline") or {})

    scheduled_departure = _parse_aerodatabox_time((departure.get("scheduledTime") or {}).get("utc"))
    revised_departure = _parse_aerodatabox_time((departure.get("revisedTime") or {}).get("utc"))
    scheduled_arrival = _parse_aerodatabox_time((arrival.get("scheduledTime") or {}).get("utc"))
    revised_arrival = _parse_aerodatabox_time((arrival.get("revisedTime") or {}).get("utc"))

    departure_utc = revised_departure or scheduled_departure
    arrival_utc = revised_arrival or scheduled_arrival
    if not (origin_code and destination_code and departure_utc and arrival_utc):
        return None
    if arrival_utc <= departure_utc:
        return None

    carrier = _carrier_code(number_block)
    service = "".join(ch for ch in number_block if ch.isdigit()) or number_block

    from ..domain.geo import distance_between_places

    try:
        distance = distance_between_places(origin_code, destination_code)
    except KeyError:
        distance = None

    return OptionSegment(
        key=f"live:{origin_code}-{destination_code}:{number_block}:{departure_utc.isoformat()}",
        segment_type=SegmentType.FLIGHT,
        carrier_code=carrier,
        service_number=number_block or service,
        origin_code=origin_code,
        destination_code=destination_code,
        departure_utc=departure_utc,
        arrival_utc=arrival_utc,
        cost_minor=ESTIMATED_FARE_MINOR,
        currency="EUR",
        refundable=False,
        terminal=departure.get("terminal"),
        gate=departure.get("gate"),
        distance_km=round(distance, 1) if distance else None,
        note=(
            f"Live schedule from AeroDataBox ({airline.get('name') or carrier}). "
            "Fare is a planning estimate, not a booking quote."
        ),
        provenance=provenance,
    )


def _normalise_aerodatabox(payload: dict, provenance: str, fetched_at: datetime | None) -> dict:
    records = payload if isinstance(payload, list) else [payload]
    first = records[0] if records else {}
    departure = first.get("departure", {}) or {}
    arrival = first.get("arrival", {}) or {}
    return {
        "service_number": first.get("number"),
        "origin": (departure.get("airport") or {}).get("iata"),
        "destination": (arrival.get("airport") or {}).get("iata"),
        "scheduled_departure_utc": (departure.get("scheduledTime") or {}).get("utc"),
        "scheduled_arrival_utc": (arrival.get("scheduledTime") or {}).get("utc"),
        "estimated_departure_utc": (departure.get("revisedTime") or {}).get("utc"),
        "estimated_arrival_utc": (arrival.get("revisedTime") or {}).get("utc"),
        "status": first.get("status"),
        "terminal": departure.get("terminal"),
        "gate": departure.get("gate"),
        "provenance": provenance,
        "source": "AeroDataBox",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


def _parse_aviationstack_time(value: str | None) -> datetime | None:
    """AviationStack returns ISO 8601 with an offset, or null."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _option_from_aviationstack(
    row: dict, provenance: str, fetched_at: datetime | None
) -> OptionSegment | None:
    """One AviationStack row as an option, or ``None`` if unusable."""
    departure = row.get("departure") or {}
    arrival = row.get("arrival") or {}
    origin_code = departure.get("iata")
    destination_code = arrival.get("iata")
    flight = row.get("flight") or {}
    number_block = flight.get("iata") or ""
    airline = (row.get("airline") or {}).get("name") or ""

    departure_utc = (
        _parse_aviationstack_time(departure.get("estimated"))
        or _parse_aviationstack_time(departure.get("scheduled"))
    )
    arrival_utc = (
        _parse_aviationstack_time(arrival.get("estimated"))
        or _parse_aviationstack_time(arrival.get("scheduled"))
    )
    if not (origin_code and destination_code and departure_utc and arrival_utc):
        return None
    if arrival_utc <= departure_utc:
        return None

    carrier = _carrier_code(number_block)
    raw_status = (row.get("flight_status") or "").lower()
    note_status = {
        "cancelled": "This service is shown as cancelled by the provider.",
        "active": "In the air at the time of query.",
        "landed": "Already landed at the time of query.",
    }.get(raw_status, "")

    from ..domain.geo import distance_between_places

    try:
        distance = distance_between_places(origin_code, destination_code)
    except KeyError:
        distance = None

    codeshared = (flight.get("codeshared") or {}) if isinstance(flight.get("codeshared"), dict) else {}
    # The marketing number is what the traveller books, but a codeshare row is
    # a duplicate of the operating service, so the operator is carried through
    # to let the search collapse the pair into one row.
    operating_number = (codeshared.get("flight_iata") or "").upper() or None
    operating_carrier = (codeshared.get("airline_iata") or "").upper() or None

    return OptionSegment(
        key=f"live:{origin_code}-{destination_code}:{number_block}:{departure_utc.isoformat()}",
        segment_type=SegmentType.FLIGHT,
        carrier_code=carrier,
        service_number=number_block,
        origin_code=origin_code,
        destination_code=destination_code,
        departure_utc=departure_utc,
        arrival_utc=arrival_utc,
        cost_minor=ESTIMATED_FARE_MINOR,
        currency="EUR",
        refundable=False,
        terminal=departure.get("terminal"),
        gate=departure.get("gate"),
        distance_km=round(distance, 1) if distance else None,
        note=(
            f"Live schedule from AviationStack ({airline or carrier}). "
            "Fare is a planning estimate, not a booking quote."
            + (f" {note_status}" if note_status else "")
        ),
        provenance=provenance,
        operating_carrier=operating_carrier,
        operating_number=operating_number,
        stale_when_landed=raw_status == "landed",
    )


def _collapse_codeshares(options: list[OptionSegment]) -> list[OptionSegment]:
    """Fold the marketing rows of one physical service into a single option.

    A provider publishes one row per codeshare, so a single IndiGo departure
    can appear four times under partner marketing numbers. Every row that names
    the same operating flight and departure is one physical service, so the
    group is kept once and the marketing numbers are named in the note. A row
    that is itself the operator is preferred over its marketing copies, and a
    finished journey never outranks a service still to run.
    """
    def identity(option: OptionSegment) -> str:
        # A marketing row names its operator; an operator's own row is its own
        # operator, so both reduce to the same flight number.
        return option.operating_number or option.service_number

    def key(option: OptionSegment) -> tuple:
        return (identity(option), option.departure_utc, option.origin_code, option.destination_code)

    grouped: dict[tuple, list[OptionSegment]] = {}
    order: list[tuple] = []
    for option in options:
        group = grouped.get(key(option))
        if group is None:
            grouped[key(option)] = group = []
            order.append(key(option))
        group.append(option)

    collapsed: list[OptionSegment] = []
    for group_key in order:
        group = grouped[group_key]
        group.sort(key=lambda o: (o.operating_number is not None, o.stale_when_landed))
        primary = group[0]
        partners = sorted(
            {o.service_number for o in group if o.service_number != primary.service_number}
        )
        note = primary.note + (f" Also marketed as {', '.join(partners)}." if partners else "")
        collapsed.append(replace(primary, note=note))

    collapsed.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return collapsed


def _normalise_aviationstack(payload: dict, provenance: str, fetched_at: datetime | None) -> dict:
    rows = payload.get("data") or []
    first = rows[0] if rows else {}
    departure = first.get("departure") or {}
    arrival = first.get("arrival") or {}
    return {
        "service_number": (first.get("flight") or {}).get("iata"),
        "origin": (departure.get("iata")),
        "destination": (arrival.get("iata")),
        "scheduled_departure_utc": departure.get("scheduled"),
        "scheduled_arrival_utc": arrival.get("scheduled"),
        "estimated_departure_utc": departure.get("estimated"),
        "estimated_arrival_utc": arrival.get("estimated"),
        "status": first.get("flight_status"),
        "terminal": departure.get("terminal"),
        "gate": departure.get("gate"),
        "provenance": provenance,
        "source": "AviationStack",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


def _schedule_row_date(row: dict, fallback: date | None) -> date | None:
    """The calendar date a schedule row is published for."""
    raw = (row.get("date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return fallback


def _parse_naive_local(
    value: str | None, tz, *, on_date: date | None = None
) -> datetime | None:
    """Parse a provider's wall-clock time as a local time in a known zone.

    AviationStack's schedule endpoint returns a bare local time with no offset
    ("2026-10-05 00:50:00"). ``scheduledTime`` also carries no date of its own,
    so the row's date is combined with the wall clock before the airport's IANA
    zone is attached. Without that, a row whose local clock crosses midnight is
    placed on the wrong day.
    """
    if not value:
        return None
    text = value.strip().replace("T", " ")
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        # The formats above carry no date; splice in the row's.
        if on_date is not None:
            parsed = datetime.combine(on_date, parsed.time())
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz).astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def _option_from_flights_future(
    row: dict,
    provenance: str,
    *,
    fallback_origin: str | None = None,
    fallback_date: date | None = None,
) -> OptionSegment | None:
    """One ``flightsFuture`` schedule row as an option, or ``None``.

    The schedule endpoint returns no status and no revised time - it is the
    published timetable - so the scheduled time is used. A codeshared row
    carries the operating carrier; the marketing flight number is kept so the
    traveller sees the flight they would actually book.

    ``scheduledTime`` carries no date. It is a wall-clock time on the row's own
    ``date`` in the named airport's timezone, so the date is combined before
    converting to UTC. Assuming the caller's UTC date instead shifts any row
    whose local clock crosses midnight.
    """
    departure = row.get("departure") or {}
    arrival = row.get("arrival") or {}
    flight = row.get("flight") or {}
    airline = row.get("airline") or {}

    origin_code = (departure.get("iataCode") or "").upper() or fallback_origin
    destination_code = (arrival.get("iataCode") or "").upper()
    number_block = (flight.get("iataNumber") or "").upper()
    if not (origin_code and destination_code and number_block):
        return None

    try:
        origin_tz = zone_for(origin_code)
        destination_tz = zone_for(destination_code)
    except Exception:  # noqa: BLE001 - unknown zone, row is unusable
        return None

    row_date = _schedule_row_date(row, fallback_date)
    if row_date is None:
        return None

    departure_utc = _parse_naive_local(departure.get("scheduledTime"), origin_tz, on_date=row_date)
    arrival_utc = _parse_naive_local(
        arrival.get("scheduledTime"), destination_tz, on_date=row_date
    )
    if arrival_utc and departure_utc and arrival_utc <= departure_utc:
        # An overnight arrival is published on the day it lands, so a next-day
        # row is valid; only a non-positive duration is not.
        return None
    if not (departure_utc and arrival_utc):
        return None

    carrier = _carrier_code(number_block)

    from ..domain.geo import distance_between_places

    try:
        distance = distance_between_places(origin_code, destination_code)
    except KeyError:
        distance = None

    return OptionSegment(
        key=f"live:{origin_code}-{destination_code}:{number_block}:{departure_utc.isoformat()}",
        segment_type=SegmentType.FLIGHT,
        carrier_code=carrier,
        service_number=number_block,
        origin_code=origin_code,
        destination_code=destination_code,
        departure_utc=departure_utc,
        arrival_utc=arrival_utc,
        cost_minor=ESTIMATED_FARE_MINOR,
        currency="EUR",
        refundable=False,
        terminal=departure.get("terminal"),
        gate=departure.get("gate") or None,
        distance_km=round(distance, 1) if distance else None,
        note=(
            f"Live schedule from AviationStack ({airline.get('name') or carrier}). "
            "Fare is a planning estimate, not a booking quote."
        ),
        provenance=provenance,
    )


def _option_from_flightaware(
    row: dict, provenance: str, *, fallback_origin: str | None = None
) -> OptionSegment | None:
    """One AeroAPI scheduled-departure row as an option, or ``None``."""
    origin_code = (row.get("origin") or fallback_origin or "").upper()
    destination_code = (row.get("destination") or "").upper()
    ident = (row.get("ident") or "").upper()
    if not (origin_code and destination_code and ident):
        return None

    departure_utc = _parse_aerodatabox_time(row.get("scheduled_out"))
    arrival_utc = _parse_aerodatabox_time(row.get("scheduled_in"))
    if not (departure_utc and arrival_utc) or arrival_utc <= departure_utc:
        return None

    carrier = _carrier_code(ident)

    from ..domain.geo import distance_between_places

    try:
        distance = distance_between_places(origin_code, destination_code)
    except KeyError:
        distance = None

    return OptionSegment(
        key=f"live:{origin_code}-{destination_code}:{ident}:{departure_utc.isoformat()}",
        segment_type=SegmentType.FLIGHT,
        carrier_code=carrier,
        service_number=ident,
        origin_code=origin_code,
        destination_code=destination_code,
        departure_utc=departure_utc,
        arrival_utc=arrival_utc,
        cost_minor=ESTIMATED_FARE_MINOR,
        currency="EUR",
        refundable=False,
        distance_km=round(distance, 1) if distance else None,
        note=(
            "Live schedule from FlightAware AeroAPI. "
            "Fare is a planning estimate, not a booking quote."
        ),
        provenance=provenance,
    )


def _normalise_flightaware(payload: dict, provenance: str, fetched_at: datetime | None) -> dict:
    flights = payload.get("scheduled_departures") or payload.get("flights") or []

    first = flights[0] if flights else payload
    return {
        "service_number": first.get("ident"),
        "origin": first.get("origin"),
        "destination": first.get("destination"),
        "scheduled_departure_utc": first.get("scheduled_out"),
        "scheduled_arrival_utc": first.get("scheduled_in"),
        "estimated_departure_utc": first.get("estimated_out"),
        "estimated_arrival_utc": first.get("estimated_in"),
        "status": first.get("status"),
        "terminal": first.get("terminal_origin"),
        "gate": first.get("gate_origin"),
        "provenance": provenance,
        "source": "FlightAware AeroAPI",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_flight_provider(settings: Settings) -> FlightProvider:
    """Pick the configured schedule provider, or an unconfigured placeholder.

    There is no demo fallback: with no key the caller gets
    :class:`UnconfiguredFlightProvider`, which raises ``NotConfigured`` so the
    UI can ask for a provider key instead of showing invented flights.
    """
    preference = (settings.flight_provider or "").lower()

    named = {
        "aerodatabox": (settings.aerodatabox_api_key, AeroDataBoxProvider),
        "aviationstack": (settings.aviationstack_api_key, AviationStackProvider),
        "flightaware": (settings.flightaware_api_key, FlightAwareAeroAPIProvider),
    }

    if preference in named:
        key, factory = named[preference]
        if key:
            return factory(key)

    # Auto-detect: use whichever key is present, in the documented order.
    for name in ("aerodatabox", "aviationstack", "flightaware"):
        key, factory = named[name]
        if key:
            return factory(key)

    return UnconfiguredFlightProvider()


def active_provider_name(settings: Settings) -> str:
    return build_flight_provider(settings).name


def schedule_provider_available(settings: Settings) -> bool:
    """Whether a real schedule provider is configured."""
    return build_flight_provider(settings).name != "unconfigured"


def airport_label(code: str) -> str:
    place = require_place(code)
    return f"{place.name} ({code})"
