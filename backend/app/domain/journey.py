"""Journey builder: compose a trip from searchable transport, then run the
same detection and recovery pipeline the live feeds feed into.

The builder is the entry point to ReTryp. A traveller picks an origin and a
destination, is offered the services real sources can answer for, chooses the
mode and a reason for travel, and the trip is persisted and checked. Every
option carries its provenance, so a provider's scheduled flight is badged
``LIVE`` and a published DELFI/GTFS.de train is badged ``REFERENCE``.

Honesty rules enforced here:

* A leg is only offered when a real source can answer for it: the configured
  schedule provider, the published GTFS rail timetable, or a timed connection
  through a hub the reference data knows. Nothing is modelled or invented.
* Place search is served from the downloaded OurAirports artifact plus the
  curated rail stations. Nothing is fabricated.
* With no schedule provider configured, flight search returns an empty leg
  with a note saying a provider key is required, never a placeholder flight.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import rail
from .enums import SegmentType
from .geo import distance_between_places
from .options import OptionSegment
from .reference import CURATED_PLACES, PLACES, Place, require_place, route_airlines
from .timeutil import ensure_utc, zone_for

# ---------------------------------------------------------------------------
# Reasons for travel
# ---------------------------------------------------------------------------

REASONS: tuple[dict[str, str], ...] = (
    {"code": "business", "label": "Business"},
    {"code": "customer_meeting", "label": "Customer meeting"},
    {"code": "conference", "label": "Conference"},
    {"code": "leisure", "label": "Leisure"},
    {"code": "family", "label": "Family visit"},
    {"code": "medical", "label": "Medical"},
    {"code": "other", "label": "Other"},
)

REASON_CODES = {reason["code"] for reason in REASONS}

# ---------------------------------------------------------------------------
# Which datasets can answer for a pair
# ---------------------------------------------------------------------------

# The published GTFS timetable in this build covers German rail between these
# city markets. It is a real timetable, so it can answer for any date inside
# its validity window.
RAIL_CITIES = {"FRA", "BER"}


@dataclass(frozen=True, slots=True)
class LegOptions:
    """The answer to "how can I get from A to B", plus its honesty metadata."""

    origin: str
    destination: str
    date: str
    options: list[OptionSegment]
    sources: list[str]
    provenance: str
    notes: list[str] = field(default_factory=list)
    # Concrete two-hop routes the connectivity graph can offer for a pair with
    # no direct service, when no timed itinerary could be built.
    connections: list[dict] = field(default_factory=list)
    # Timed two-leg itineraries through a hub. These are listed alongside
    # direct services, not only when a direct service is missing, so a traveller
    # can compare a connection on cost or arrival.
    itineraries: list[dict] = field(default_factory=list)


def search_places(query: str, limit: int = 10) -> list[dict]:
    """Text search across airports and rail stations, for the pickers."""
    q = query.strip().lower()
    if not q:
        return []
    hits: list[tuple[int, Place]] = []
    for place in PLACES.values():
        code = place.code.lower()
        name = place.name.lower()
        city = place.city.lower()
        if code == q:
            rank = 0
        elif code.startswith(q):
            rank = 1
        elif city.startswith(q):
            rank = 2
        elif name.startswith(q):
            rank = 3
        elif q in city or q in name:
            rank = 4
        else:
            continue
        hits.append((rank, place))
    # Cities first (multi-modal), then rail stations, then airports last.
    kind_order = {"city": 0, "rail": 1, "bus": 2, "airport": 3}
    hits.sort(key=lambda t: (t[0], kind_order.get(t[1].kind, 4), t[1].city, t[1].code))
    return [_place_payload(p) for _, p in hits[:limit]]


def _place_payload(place: Place) -> dict:
    return {
        "code": place.code,
        "name": place.name,
        "city": place.city,
        "country": place.country,
        "timezone": place.tz,
        "kind": place.kind,
        "is_city": place.kind == "city",
        "provenance": "CURATED" if place.code in CURATED_PLACES else "REFERENCE",
    }


def _flight_options(origin: str, destination: str, after_utc: datetime) -> list[OptionSegment]:
    """Deprecated: authored catalogue flights are no longer used.

    Kept as an empty seam so callers keep a single code path; the schedule
    provider is the only flight source.
    """
    return []


def _rail_options(origin: str, destination: str, after_utc: datetime) -> list[OptionSegment]:
    """Real DELFI/GTFS.de timetabled services, badged REFERENCE."""
    if not rail.RAIL_LOADED:
        return []
    return rail.rail_options_between(origin, destination, after_utc, limit=10)


def search_options(
    origin: str,
    destination: str,
    *,
    on_date: date | None = None,
    after_utc: datetime | None = None,
) -> LegOptions:
    """Every service the datasets can offer for a leg, synchronously.

    Used where the caller cannot await (the journey builder's server-side
    re-resolution). Live providers are only reachable through the async
    :func:`search_options_live`; this variant answers from the online/offline
    datasets and the connectivity graph.
    """
    return _collect(
        origin,
        destination,
        on_date=on_date,
        after_utc=after_utc,
        live_options=None,
    )


async def search_options_live(
    origin: str,
    destination: str,
    *,
    on_date: date | None = None,
    after_utc: datetime | None = None,
) -> LegOptions:
    """Option search that also asks a configured live schedule provider.

    Any pair works when a provider key is present: the provider's departures
    are filtered to the destination and merged with the timetabled rail. With
    no key this behaves exactly like :func:`search_options`.
    """
    from ..config import get_settings

    settings = get_settings()
    live: list[OptionSegment] = []
    provider_name: str | None = None
    live_itineraries: list[dict] = []
    from ..providers.flights import build_flight_provider

    provider = build_flight_provider(settings)
    if provider.name != "unconfigured":
        provider_name = provider.name
        day = on_date or datetime.now(timezone.utc).date()
        tz = zone_for(origin)
        window_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
        if after_utc:
            window_start = max(window_start, ensure_utc(after_utc))
        try:
            live = await provider.search(
                origin=origin, destination=destination, depart_after_utc=window_start
            )
        except Exception:  # noqa: BLE001 - provider boundary, degrade to datasets
            live = []

        # Ask for hub connections as well, so the two lists can be compared.
        # The provider caps how many hubs it will call for, and its own budget
        # is respected, so this cannot drain a metered plan.
        if settings.connection_search_hubs > 0:
            try:
                candidates = await provider.find_connections(
                    origin=origin,
                    destination=destination,
                    depart_after_utc=window_start,
                    max_hubs=settings.connection_search_hubs,
                )
            except Exception:  # noqa: BLE001 - provider boundary
                candidates = None
            if candidates is not None and candidates.itineraries:
                from . import itineraries as itinerary_mod

                live_itineraries = [
                    itinerary_mod.itinerary_payload(it) for it in candidates.itineraries
                ]

    # Live Indian Railways telemetry via RailRadar API if configured
    if settings.railradar_enabled:
        from ..providers.railradar import RailRadarProvider

        rr = RailRadarProvider(settings)
        try:
            day = on_date or datetime.now(timezone.utc).date()
            tz = zone_for(origin)
            rr_window = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
            if after_utc:
                rr_window = max(rr_window, ensure_utc(after_utc))
            rr_trains = await rr.search_trains_between(origin, destination, rr_window)
            if rr_trains:
                live = (live or []) + rr_trains
                provider_name = (
                    f"{provider_name} + RailRadar"
                    if provider_name
                    else "RailRadar (Indian Railways)"
                )
        except Exception:
            pass

    return _collect(
        origin,
        destination,
        on_date=on_date,
        after_utc=after_utc,
        live_options=live,
        provider_name=provider_name,
        live_itineraries=live_itineraries,
    )


def _bus_options(origin: str, destination: str, after_utc: datetime) -> list[OptionSegment]:
    from .bus import BUS_LOADED, bus_options_between

    if not BUS_LOADED:
        return []
    return bus_options_between(origin, destination, after_utc, limit=10)


def _collect(
    origin: str,
    destination: str,
    *,
    on_date: date | None,
    after_utc: datetime | None,
    live_options: list[OptionSegment] | None,
    provider_name: str | None = None,
    live_itineraries: list[dict] | None = None,
    connection_note: str | None = None,
) -> LegOptions:
    """Merge every source into one leg answer, deduped and badged."""
    origin_place = require_place(origin)
    destination_place = require_place(destination)
    day = on_date or datetime.now(timezone.utc).date()

    if origin_place.market == destination_place.market:
        return LegOptions(
            origin=origin,
            destination=destination,
            date=day.isoformat(),
            options=[],
            sources=[],
            provenance="UNAVAILABLE",
            notes=["Origin and destination are in the same city."],
        )

    # Start the window at local midnight on the requested day.
    tz = zone_for(origin)
    window_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    window_end = window_start + timedelta(days=1)
    lower_bound = max(window_start, ensure_utc(after_utc) if after_utc else window_start)

    options: list[OptionSegment] = []
    options += live_options or []
    
    # Use market codes (city level) for alternative ground transport 
    # so searching between airports still shows buses/trains between their respective cities
    orig_market = origin_place.market if origin_place.market else origin
    dest_market = destination_place.market if destination_place.market else destination
    
    options += _rail_options(orig_market, dest_market, lower_bound)
    options += _bus_options(orig_market, dest_market, lower_bound)

    options = [o for o in options if lower_bound <= o.departure_utc < window_end]
    options.sort(key=lambda o: (o.departure_utc, o.segment_type.value))  # type: ignore[arg-type]

    # Prefer LIVE trains over REFERENCE timetable when the same train number exists
    live_train_numbers = {
        o.service_number.split()[0]
        for o in options
        if o.segment_type.value == "train" and o.provenance == "LIVE"
    }
    filtered_options = []
    for o in options:
        if o.segment_type.value == "train" and o.provenance == "REFERENCE":
            if any(num in o.service_number for num in live_train_numbers):
                continue
        filtered_options.append(o)
    options = filtered_options

    # The timetable artifact groups a daily train by duration signature, so the
    # same service can appear more than once for a day. Keep one row per
    # service and departure time.
    deduped: list[OptionSegment] = []
    seen: set[tuple[str, str]] = set()
    for option in options:
        marker = (option.service_number, option.departure_utc.isoformat())
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(option)
    options = deduped

    sources: list[str] = []
    notes: list[str] = []
    has_live_flights = any(o.provenance in {"LIVE", "CACHED"} and o.segment_type.value == "flight" for o in options)
    has_live_trains = any(o.provenance == "LIVE" and o.segment_type.value == "train" for o in options)
    has_ref_trains = any(o.provenance == "REFERENCE" and o.segment_type.value == "train" for o in options)
    has_buses = any(o.segment_type.value == "bus" for o in options)

    if has_live_flights:
        sources.append(f"Live flight schedule provider ({provider_name or 'configured provider'})")
        notes.append("Flight times are the provider's published schedule. Fares are planning estimates.")
    if has_live_trains:
        sources.append("RailRadar API (Indian Railways Live Telemetry)")
        notes.append("Live Indian Railways train times and running delays via api.railradar.in.")
    if has_ref_trains:
        sources.append("Indian Railways & European Timetables")
        notes.append("Rail times are from published timetables. Fares are estimates, not booking quotes.")
    if has_buses:
        sources.append("12Go Asia Multi-Modal API (Live Bus & Ground Transport)")
        notes.append("Real-time bus schedules via 12Go Asia API and state transport corporations.")

    connections: list[dict] = []
    itineraries: list[dict] = list(live_itineraries or [])
    if live_itineraries:
        notes.append(
            connection_note
            or "Connecting itineraries through a hub are timed against the minimum "
            "connection time at that hub; each leg is badged with its source."
        )
    if not options:

        from . import graph

        connections = graph.suggest_bridges(origin, destination)
        # If the reference data can bridge the pair, time the connection for
        # the traveller instead of only naming the hub. These are complete
        # two-leg itineraries, each leg badged with its own provenance.
        from . import itineraries as itinerary_mod

        if not itineraries:
            found = itinerary_mod.connectable_itineraries(origin, destination, day)
            itineraries = [itinerary_mod.itinerary_payload(it) for it in found]
        if itineraries:
            notes.append(
                "No direct service is published for this pair on this date. These "
                "itineraries through a hub are timed against the minimum connection "
                "time at the hub; each leg is badged with its source."
            )
        elif connections:
            notes.append(
                "No direct service is published for this pair. Connecting routes "
                "through a hub are listed below."
            )
        else:
            notes.append("No service is available for this pair from the configured sources.")

    if any(o.provenance in {"LIVE", "CACHED"} for o in options):
        # A live answer that only produced finished journeys is not a live
        # answer, so the leg badge tracks what the rows actually show.
        if any(o.provenance == "LIVE" and not o.stale_when_landed for o in options):
            provenance = "LIVE"
        else:
            provenance = "CACHED"
    elif any(o.provenance == "REFERENCE" for o in options):
        provenance = "REFERENCE"
    else:
        provenance = "UNAVAILABLE"

    return LegOptions(
        origin=origin,
        destination=destination,
        date=day.isoformat(),
        options=options,
        sources=sources,
        provenance=provenance,
        notes=notes,
        connections=connections,
        itineraries=itineraries,
    )


async def transfer_options(city: str, after_utc: datetime) -> list[OptionSegment]:
    """Airport-to-hotel transfers for a city, from real GTFS feeds.

    Requires a Transitland key. With none configured this returns an empty
    list; the caller reports ground transport as unavailable rather than
    inventing a service.
    """
    from ..config import get_settings
    from ..providers.data import get_transfers

    settings = get_settings()
    rides = await get_transfers(settings, city, after_utc)
    return [
        OptionSegment(
            key=ride.key,
            segment_type=SegmentType.TRANSFER,
            carrier_code="TRF",
            service_number=ride.provider_name,
            origin_code=city,
            destination_code=city,
            departure_utc=ensure_utc(ride.pickup_utc),
            arrival_utc=ensure_utc(ride.dropoff_utc),
            cost_minor=ride.cost_minor,
            currency=ride.currency,
            refundable=False,
            note=ride.note,
            provenance=ride.provenance,
        )
        for ride in rides
    ]


def new_reference() -> str:
    """A short, human-quotable trip reference, unique per trip."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "RTY-" + "".join(secrets.choice(alphabet) for _ in range(6))


def dataset_coverage() -> dict:
    """What the loaded datasets can actually answer for.

    The builder shows this when a pair has no service, so the reader sees the
    real extent of the data instead of a hard-coded example. Flight coverage is
    not a fixed list - it is whatever the configured schedule provider returns
    - so it is described rather than enumerated.
    """
    from ..config import get_settings
    from ..providers.flights import active_provider_name, schedule_provider_available

    settings = get_settings()
    return {
        "flight_provider": active_provider_name(settings),
        "flight_provider_configured": schedule_provider_available(settings),
        "rail_pairs": _rail_market_pairs() if rail.RAIL_LOADED else [],
        "rail_source": rail.META.get("publisher") if rail.RAIL_LOADED else None,
        "rail_valid_from": rail.META.get("valid_from") if rail.RAIL_LOADED else None,
        "rail_valid_to": rail.META.get("valid_to") if rail.RAIL_LOADED else None,
    }


def _rail_market_pairs() -> list[dict]:
    """Rail coverage as city pairs, with the stations each pair covers.

    The timetable answers for several station pairs within Frankfurt and
    Berlin, but that is one line a traveller cares about, so the stations are
    listed under a single market pair rather than repeated per combination.
    """
    markets: dict[tuple[str, str], set[str]] = {}
    for origin, destination in rail.RAIL_PAIRS:
        a = PLACES.get(origin)
        b = PLACES.get(destination)
        if a is None or b is None:
            continue
        markets.setdefault((a.market, b.market), set()).update({a.name, b.name})

    return [
        {
            "origin": origin,
            "destination": destination,
            "origin_name": origin,
            "destination_name": destination,
            "label": f"{origin} \u2013 {destination}",
            "detail": " \u00b7 ".join(sorted(stations)),
        }
        for (origin, destination), stations in sorted(markets.items())
    ]


def journey_notes(origin: str, destination: str) -> dict:
    """Coverage summary the builder screen shows before anything is chosen."""
    from ..providers.flights import active_provider_name, schedule_provider_available
    from ..config import get_settings

    settings = get_settings()
    return {
        "reasons": list(REASONS),
        "coverage": {
            "rail_cities": sorted(RAIL_CITIES),
            "flight_provider": active_provider_name(settings),
            "flight_provider_configured": schedule_provider_available(settings),
            "rail_loaded": rail.RAIL_LOADED,
        },
        "distance_km": round(distance_between_places(origin, destination), 1)
        if origin in PLACES and destination in PLACES
        else None,
        "route_airlines": [
            {"code": code, "name": code} for code in route_airlines(origin, destination)[:6]
        ],
    }
