"""Weather, ground transport, hotels, maps and historical-prior providers.

Each one calls a real provider and reports which source answered. Nothing in
this module fabricates a value: when a provider is not configured or cannot be
reached, the caller is told so and the UI shows an unavailable state rather
than an invented reading.

Providers used here need no key (Open-Meteo, Nominatim, OSRM). Hotel search
requires Amadeus credentials; Amadeus Self-Service was decommissioned on
17 July 2026, so only a contracted Enterprise key can serve it. Ground
transport requires a Transitland key. Both return an empty list when they are
not configured, and the UI says the data is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from ..config import Settings
from ..domain.priors import DELAY_PRIORS, prior_for
from .base import NotConfigured, ProviderError, RateLimited, registry

USER_AGENT = "ReTryp/1.0"


@dataclass
class WeatherReading:
    place_code: str
    condition: str
    temp_c: float
    wind_kph: float
    precip_mm: float
    visibility_km: float | None
    provenance: str
    source: str
    fetched_at: datetime | None = None
    note: str = ""


async def get_weather(settings: Settings, place_code: str) -> WeatherReading | None:
    """Open-Meteo current conditions.

    Open-Meteo needs no key, so it is used for every place. If the call fails
    the caller gets ``None`` and shows an unavailable state; it is never
    replaced with an invented reading.
    """
    from ..domain.reference import require_place

    place = require_place(place_code)

    client = registry.client("open-meteo", ttl_seconds=settings.provider_cache_ttl_seconds)
    key = client.cache_key("weather", place_code)

    async def fetch() -> dict:
        params = {
            "latitude": place.lat,
            "longitude": place.lon,
            "current": "temperature_2m,precipitation,wind_speed_10m,weather_code,visibility",
            "wind_speed_unit": "kmh",
        }
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            if response.status_code == 429:
                raise RateLimited("Open-Meteo rate limit")
            response.raise_for_status()
            return response.json()

    try:
        payload, provenance, fetched_at = await client.get(key, fetch)
    except (ProviderError, NotConfigured):
        return None

    current = payload.get("current", {})
    return WeatherReading(
        place_code=place_code,
        condition=_weather_code_label(current.get("weather_code")),
        temp_c=float(current.get("temperature_2m", 0)),
        wind_kph=float(current.get("wind_speed_10m", 0)),
        precip_mm=float(current.get("precipitation", 0)),
        visibility_km=(float(current["visibility"]) / 1000) if current.get("visibility") is not None else None,
        provenance=provenance,
        source="Open-Meteo",
        fetched_at=fetched_at,
    )


def _weather_code_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    table = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Drizzle",
        55: "Dense drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
        81: "Rain showers", 82: "Violent rain showers", 95: "Thunderstorm",
        96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
    }
    return table.get(code, f"Weather code {code}")


# ---------------------------------------------------------------------------
# Historical delay priors
# ---------------------------------------------------------------------------

@dataclass
class DelayPriorReading:
    subject: str
    scope: str
    on_time_pct: float
    avg_delay_minutes: int
    sample: str
    source_name: str
    source_url: str
    verified_on: str
    provenance: str = "REFERENCE"
    note: str = ""


def get_delay_prior(subject: str) -> DelayPriorReading | None:
    """Route or airport punctuality aggregate.

    These are published aggregates (BTS for the US, DGCA for India,
    Eurocontrol/UK CAA for Europe). They are never per-flight history, and the
    UI says so wherever they appear. The provenance is REFERENCE because the
    figure is a real published statistic, not a live feed.
    """
    prior = prior_for(subject)
    if prior is None:
        return None
    return DelayPriorReading(
        subject=prior.subject,
        scope=prior.scope,
        on_time_pct=prior.on_time_pct,
        avg_delay_minutes=prior.avg_delay_minutes,
        sample=prior.sample,
        source_name=prior.source_name,
        source_url=prior.source_url,
        verified_on=prior.verified_on,
        provenance="REFERENCE",
        note=prior.note or "Published aggregate, not per-flight history.",
    )


def all_delay_priors() -> list[DelayPriorReading]:
    return [get_delay_prior(p.subject) for p in DELAY_PRIORS if get_delay_prior(p.subject)]


# ---------------------------------------------------------------------------
# Ground transport (GTFS)
# ---------------------------------------------------------------------------

@dataclass
class GroundOption:
    key: str
    mode: str
    provider_name: str
    from_label: str
    to_label: str
    city_code: str
    timezone: str
    pickup_utc: datetime
    dropoff_utc: datetime
    cost_minor: int
    currency: str
    provenance: str
    source: str
    note: str = ""


async def get_transfers(settings: Settings, city_code: str, after_utc: datetime) -> list[GroundOption]:
    """Transfers for a city, from real GTFS feeds.

    GTFS static and GTFS-Realtime feeds are discovered through Transitland and
    the Mobility Database. A Transitland key is required; without one this
    returns an empty list and the UI reports ground transport as unavailable
    rather than inventing a service.

    There is no official live Indian rail API. Indian rail data, when present,
    is static timetable data reported as CACHED, never live.
    """
    if not settings.transitland_api_key:
        return []
    return await _transitland_transfers(settings, city_code, after_utc)


async def _transitland_transfers(
    settings: Settings, city_code: str, after_utc: datetime
) -> list[GroundOption]:
    """Transitland GTFS stop-times for a city near a given instant.

    TODO: verify - Transitland's stops/departures response shape and free-tier
    limits against the current API docs before relying on this in production.
    """
    from ..domain.reference import require_place

    place = require_place(city_code)
    client = registry.client("transitland", ttl_seconds=settings.provider_cache_ttl_seconds)
    key = client.cache_key("transfers", city_code, after_utc.date().isoformat())

    async def fetch() -> dict:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.get(
                "https://transit.land/api/v2/rest/stops",
                params={
                    "lat": place.lat,
                    "lon": place.lon,
                    "radius": 5000,
                    "limit": 20,
                    "apikey": settings.transitland_api_key,
                },
                headers={"User-Agent": USER_AGENT},
            )
            if response.status_code == 429:
                raise RateLimited("Transitland rate limit")
            response.raise_for_status()
            return response.json()

    try:
        payload, provenance, _ = await client.get(key, fetch)
    except (ProviderError, NotConfigured):
        return []

    options: list[GroundOption] = []
    for stop in payload.get("stops") or []:
        name = stop.get("stop_name") or stop.get("name") or "Transit stop"
        options.append(
            GroundOption(
                key=f"transitland-{stop.get('onestop_id', stop.get('stop_id', 'stop'))}",
                mode="transfer",
                provider_name="Transitland (GTFS)",
                from_label=f"{place.name} ({place.code})",
                to_label=name,
                city_code=city_code,
                timezone=place.tz,
                pickup_utc=after_utc,
                dropoff_utc=after_utc,
                cost_minor=0,
                currency="EUR",
                provenance=provenance,
                source="Transitland (GTFS)",
                note="GTFS stop location. This endpoint does not quote a fare or a departure time.",
            )
        )
    return options


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------

@dataclass
class HotelOption:
    key: str
    name: str
    city_code: str
    city_name: str
    timezone: str
    address: str | None
    latitude: float | None
    longitude: float | None
    cost_minor: int
    currency: str
    refundable: bool
    provenance: str
    source: str
    note: str = ""


async def search_hotels(settings: Settings, city_code: str, nights: int = 1) -> list[HotelOption]:
    """Hotel search via Amadeus.

    Amadeus Self-Service Hotel APIs were decommissioned on 17 July 2026, so
    this path only applies to a contracted Enterprise key pointed at the
    Enterprise base URL (settings.amadeus_base_url). Without credentials the
    result is an empty list and the UI reports hotels as unavailable; it never
    invents a property or a rate.
    """
    if not (settings.amadeus_client_id and settings.amadeus_client_secret):
        return []
    try:
        return await _amadeus_hotel_search(settings, city_code, nights)
    except (ProviderError, NotConfigured):
        return []


async def _amadeus_hotel_search(settings: Settings, city_code: str, nights: int) -> list[HotelOption]:
    client = registry.client("amadeus", ttl_seconds=1800)
    key = client.cache_key("hotels", city_code, nights)

    async def fetch() -> dict:
        async with httpx.AsyncClient(timeout=15) as http:
            token_response = await http.post(
                f"{settings.amadeus_base_url}/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.amadeus_client_id,
                    "client_secret": settings.amadeus_client_secret,
                },
                headers={"User-Agent": USER_AGENT},
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]

            search = await http.get(
                f"{settings.amadeus_base_url}/v1/reference-data/locations/hotels/by-city",
                params={"cityCode": city_code},
                headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            )
            if search.status_code == 429:
                raise RateLimited("Amadeus rate limit")
            search.raise_for_status()
            return search.json()

    payload, provenance, _ = await client.get(key, fetch)
    from ..domain.reference import require_place

    place = require_place(city_code)
    hotels = payload.get("data", [])[:5]
    return [
        HotelOption(
            key=item.get("hotelId", f"amadeus-{i}"),
            name=item.get("name", "Unnamed property"),
            city_code=city_code,
            city_name=item.get("address", {}).get("cityName", city_code),
            timezone=place.tz,
            address=(item.get("address", {}).get("lines") or [None])[0],
            latitude=item.get("geoCode", {}).get("latitude"),
            longitude=item.get("geoCode", {}).get("longitude"),
            cost_minor=0,
            currency="EUR",
            refundable=False,
            provenance=provenance,
            source="Amadeus",
            note="Rate not quoted by the reference endpoint.",
        )
        for i, item in enumerate(hotels)
    ]


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

async def geocode(settings: Settings, query: str) -> dict | None:
    """Nominatim geocoding, respecting the published usage policy.

    A custom User-Agent is mandatory and results are cached for a long time,
    because the policy asks for at most one request per second and no bulk
    querying.
    """
    client = registry.client("nominatim", ttl_seconds=86400)
    key = client.cache_key("geocode", query.lower())

    async def fetch() -> dict:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": settings.nominatim_user_agent},
            )
            response.raise_for_status()
            return {"results": response.json()}

    try:
        payload, provenance, fetched_at = await client.get(key, fetch)
    except (ProviderError, NotConfigured):
        return None

    results = payload.get("results") or []
    if not results:
        return None
    first = results[0]
    return {
        "query": query,
        "latitude": float(first["lat"]),
        "longitude": float(first["lon"]),
        "label": first.get("display_name"),
        "provenance": provenance,
        "source": "Nominatim / OpenStreetMap",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


async def route(settings: Settings, origin: tuple[float, float], destination: tuple[float, float]) -> dict | None:
    """OSRM driving route between two points."""
    client = registry.client("osrm", ttl_seconds=3600)
    key = client.cache_key("route", origin, destination)
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"

    async def fetch() -> dict:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(
                f"{settings.osrm_base_url}/route/v1/driving/{coords}",
                params={"overview": "full", "geometries": "geojson"},
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return response.json()

    try:
        payload, provenance, fetched_at = await client.get(key, fetch)
    except (ProviderError, NotConfigured):
        return None

    routes = payload.get("routes") or []
    if not routes:
        return None
    first = routes[0]
    return {
        "distance_km": round(first["distance"] / 1000, 1),
        "duration_minutes": round(first["duration"] / 60),
        "geometry": first.get("geometry"),
        "provenance": provenance,
        "source": "OSRM",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


def provider_health(settings: Settings) -> list[dict]:
    """Everything the Settings screen shows about provider configuration."""
    rows = [
        {"name": "Flight schedule and status", "provider": settings.flight_provider,
         "configured": bool(settings.aerodatabox_api_key or settings.aviationstack_api_key or settings.flightaware_api_key)},
        {"name": "Aircraft positions (OpenSky)", "provider": "opensky",
         "configured": bool(settings.opensky_client_id and settings.opensky_client_secret)},
        {"name": "Ground transport (Transitland)", "provider": "transitland",
         "configured": bool(settings.transitland_api_key)},
        {"name": "Hotels (Amadeus)", "provider": "amadeus",
         "configured": bool(settings.amadeus_client_id and settings.amadeus_client_secret)},
        {"name": "Weather (Open-Meteo)", "provider": "open-meteo", "configured": True},
        {"name": "Maps (Nominatim / OSRM)", "provider": "osm", "configured": True},
    ]
    statuses = {s.name: s for s in registry.all_statuses()}
    for row in rows:
        status = statuses.get(row["provider"])
        row["circuit"] = status.circuit.value if status else "closed"
        row["last_error"] = status.last_error if status else None
    return rows
