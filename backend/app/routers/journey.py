"""Journey builder endpoints.

This is the first screen after sign-in: pick the places, see what the datasets
can actually offer, choose the mode and a reason, then run the pipeline. The
build endpoint persists a real ``Trip`` with its segments, hotel and transfer,
and immediately checks it so the traveller lands on a journey that has already
been assessed.

Everything here reuses the same detection and recovery code the live feeds and
the Scenario Simulator use. Nothing in this router fabricates a schedule: if a
pair has no service in the loaded datasets the response says so.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..agents import pipeline
from ..config import get_settings
from ..db import get_db
from ..domain import journey as builder
from ..domain.connections import assess_connection
from ..domain.enums import (
    BookingStatus,
    DisruptionKind,
    SegmentStatus,
    TripStatus,
)
from ..llm.router import build_router
from ..domain.timeutil import ensure_utc, format_local, minutes_between, zone_for
from ..models import (
    AuditLog,
    GroundTransport,
    HotelStay,
    Segment,
    Trip,
    TripEvent,
    User,
)
from ..providers.data import search_hotels
from ..schemas import BuildJourneyRequest, RecoverJourneyRequest
from ..security import current_user
from ..display import convert_minor
from ..serializers import plan_payload, segment_payload, trip_summary_payload
from .deps import bus, load_trip

router = APIRouter(prefix="/api/journey", tags=["journey"])

# Reason codes the builder offers, plus the label shown on the trip.
_REASON_LABELS = {r["code"]: r["label"] for r in builder.REASONS}


def _option_payload(option, *, origin_tz: str, destination_tz: str) -> dict:
    """One selectable service, with local times and its provenance.

    The fare is converted to the viewer's display currency so a leg costs the
    same whether it is read here or on a recovery plan.
    """
    cost_minor, cost_currency = convert_minor(option.cost_minor, option.currency)
    return {
        "key": option.key,
        "mode": option.segment_type.value,
        "mode_label": option.segment_type.value.capitalize(),
        "carrier_code": option.carrier_code,
        "carrier_name": option.carrier_name,
        "service_number": option.service_number,
        "origin": option.origin_code,
        "destination": option.destination_code,
        "departure_utc": option.departure_utc.isoformat(),
        "arrival_utc": option.arrival_utc.isoformat(),
        "departure_local": format_local(option.departure_utc, option.origin_code, with_date=True),
        "arrival_local": format_local(option.arrival_utc, option.destination_code, with_date=True),
        "origin_tz": origin_tz,
        "destination_tz": destination_tz,
        "duration_minutes": option.duration_minutes,
        "cost_minor": cost_minor,
        "cost_currency": cost_currency,
        "cost_display": _money(cost_minor, cost_currency),
        "refundable": option.refundable,
        "terminal": option.terminal,
        "gate": option.gate,
        "platform": option.platform,
        "distance_km": option.distance_km,
        "note": option.note,
        # A reading of a journey that has already finished is a snapshot of a
        # past fact, not a live service, so it is badged cached.
        "provenance": "CACHED" if option.stale_when_landed else option.provenance,
        "stale": option.stale_when_landed,
    }


def _money(minor: int, currency: str) -> str:
    whole, frac = divmod(abs(minor), 100)
    return f"{currency} {whole:,}.{frac:02d}"


@router.get("/reasons")
def reasons(actor: User = Depends(current_user)) -> dict:
    """Reasons for travel, offered on the builder screen."""
    return {"reasons": list(builder.REASONS)}


@router.get("/places")
def places(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=10, ge=1, le=25),
    actor: User = Depends(current_user),
) -> dict:
    """Airport and rail-station lookup, backed by the loaded reference data."""
    return {"query": q, "places": builder.search_places(q, limit=limit)}


@router.get("/options")
async def options(
    origin: str = Query(min_length=2, max_length=8),
    destination: str = Query(min_length=2, max_length=8),
    date_str: str = Query(alias="date", description="Local departure day, YYYY-MM-DD"),
    actor: User = Depends(current_user),
) -> dict:
    """Every service the datasets can offer for one leg on one day.

    When a live schedule provider is configured this answers for any pair.
    With no key it falls back to the loaded datasets and, where no direct
    service exists, to concrete connecting routes through a hub.
    """
    origin, destination = origin.upper(), destination.upper()
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    try:
        leg = await builder.search_options_live(origin, destination, on_date=day)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown origin or destination code")

    origin_tz = zone_for(origin).key
    destination_tz = zone_for(destination).key
    return {
        "origin": origin,
        "destination": destination,
        "date": leg.date,
        "distance_km": _distance(origin, destination),
        "provenance": leg.provenance,
        "sources": leg.sources,
        "notes": leg.notes,
        "coverage": builder.dataset_coverage(),
        "connections": leg.connections,
        "itineraries": _itinerary_payloads(leg.itineraries),
        "options": [
            _option_payload(o, origin_tz=origin_tz, destination_tz=destination_tz)
            for o in leg.options
        ],
    }


def _itinerary_payloads(rows: list[dict]) -> list[dict]:
    """Convert each stitched itinerary's leg costs to the display currency."""
    out: list[dict] = []
    for row in rows:
        legs = []
        total = 0
        for leg in row["legs"]:
            cost_minor, cost_currency = convert_minor(leg["cost_minor"], leg["currency"])
            total += cost_minor
            legs.append({**leg, "cost_minor": cost_minor, "currency": cost_currency})
        out.append(
            {
                **row,
                "legs": legs,
                "cost_minor": total,
                "cost_display": _money(total, legs[0]["currency"]),
            }
        )
    return out


@router.get("/network")
def network(
    actor: User = Depends(current_user),
) -> dict:
    """What the connectivity graph can answer for.

    Reports node and edge counts from the loaded datasets, the best-connected
    hubs, and whether a live schedule provider is currently answering. This is
    the honest answer to "how far does ReTryp's network actually reach".
    """
    from ..domain import graph
    from ..providers.flights import active_provider_name, schedule_provider_available

    settings = get_settings()
    return {
        "coverage": graph.served_coverage(),
        "hubs": [{"code": code, "degree": degree} for code, degree in graph.hub_rank(limit=12)],
        "flight_provider": active_provider_name(settings),
        "schedule_provider_configured": schedule_provider_available(settings),
    }


@router.get("/nearest")
def nearest(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    limit: int = Query(default=8, ge=1, le=25),
    kinds: str = Query(default="", description="Comma-separated: airport,rail,city"),
    actor: User = Depends(current_user),
) -> dict:
    """Places closest to a coordinate on the map."""
    from ..domain import graph

    wanted = {k.strip() for k in kinds.split(",") if k.strip()} or None
    return {
        "lat": lat,
        "lon": lon,
        "places": graph.nearest_nodes(lat, lon, limit=limit, kinds=wanted),
    }


@router.get("/connections")
def connections(
    origin: str = Query(min_length=2, max_length=8),
    destination: str = Query(min_length=2, max_length=8),
    actor: User = Depends(current_user),
) -> dict:
    """Connecting routes between two places when no direct service is loaded."""
    from ..domain import graph

    origin, destination = origin.upper(), destination.upper()
    try:
        served = graph.is_served(origin, destination)
        path = graph.find_path(origin, destination)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown origin or destination code")

    return {
        "origin": origin,
        "destination": destination,
        "served_directly": served,
        "path": graph.path_summary(path) if path else [],
        "connections": [] if served else graph.suggest_bridges(origin, destination),
    }


@router.get("/transit-near")
async def transit_near(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=15.0, ge=1, le=60),
    actor: User = Depends(current_user),
) -> dict:
    """Rail stations and bus stops near a map point, from OpenStreetMap.

    These are places, not services: OpenStreetMap records where a stop is, not
    when a train or bus departs. A station found here cannot become a bookable
    service on its own, and the response says so.
    """
    from ..providers import transit

    settings = get_settings()
    result = await transit.transit_near(settings, lat=lat, lon=lon, radius_km=radius_km)
    nodes = result.pop("nodes")
    return {
        **result,
        "lat": lat,
        "lon": lon,
        "summary": transit.summarise(nodes),
        "nodes": [
            {
                "osm_id": n.osm_id,
                "name": n.name,
                "kind": n.kind,
                "kind_label": "Rail station" if n.kind == "rail" else "Bus stop",
                "lat": n.lat,
                "lon": n.lon,
                "operator": n.operator or None,
            }
            for n in nodes
        ],
    }


def _distance(origin: str, destination: str) -> float | None:
    try:
        from ..domain.geo import distance_between_places

        return round(distance_between_places(origin, destination), 1)
    except KeyError:
        return None


@router.get("/transfers")
async def transfers(
    city: str = Query(min_length=2, max_length=8),
    date_str: str = Query(alias="date", description="Local pickup day, YYYY-MM-DD"),
    actor: User = Depends(current_user),
) -> dict:
    """Airport-to-hotel transfers for the arrival city."""
    city = city.upper()
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    tz = zone_for(city)
    window_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    rides = await builder.transfer_options(city, window_start - timedelta(hours=1))
    rides = [r for r in rides if r.departure_utc < window_start + timedelta(days=1)]

    settings = get_settings()
    if rides:
        sources = sorted({r.provenance for r in rides})
        notes = ["Ground transport from GTFS feeds via Transitland."]
    elif not settings.transitland_api_key:
        sources = []
        notes = [
            "Ground transport is unavailable: no Transitland key is configured."
        ]
    else:
        sources = []
        notes = ["No ground transport is available for this city from the configured feeds."]

    return {
        "city": city,
        "date": day.isoformat(),
        "options": [
            _option_payload(r, origin_tz=tz.key, destination_tz=tz.key) for r in rides
        ],
        "sources": sources,
        "notes": notes,
    }


@router.post("/build", status_code=201)
async def build(
    payload: BuildJourneyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Persist the chosen journey, then check it and open a recovery cycle."""
    if payload.reason not in builder.REASON_CODES:
        raise HTTPException(status_code=422, detail=f"Unknown reason {payload.reason!r}")

    resolved = await _resolve_segments(payload)
    trip = _persist_trip(db, actor, payload, resolved)
    await _attach_hotel_and_transfer(db, trip, resolved)

    # Capture the itinerary before any recovery rewrites it. This baseline is
    # what a reset restores, so the trip can be replayed from exactly here.
    pipeline.ensure_baseline(db, trip=trip)

    db.add(
        TripEvent(
            trip_id=trip.id,
            kind="trip_created",
            title=f"{payload.name} created",
            detail=f"{len(resolved)} segments selected in the journey builder.",
            payload={"reason": payload.reason, "origin": payload.origin, "destination": payload.destination},
            provenance=_strongest_provenance([s.provenance for s in resolved.values()]),
        )
    )
    db.add(
        AuditLog(
            trip_id=trip.id,
            action="trip_created",
            summary=f"Journey built: {trip.reference}",
            actor_id=actor.id,
            actor_email=actor.email,
            detail={"reason": payload.reason, "segments": len(resolved)},
        )
    )

    # Check the journey immediately. If the traveller asked for a disruption,
    # the pipeline opens a recovery cycle before the response returns.
    check = _check_journey(db, trip)
    result: dict = {"trip": trip_summary_payload(trip), "check": check, "cycle": None, "plans": []}

    if payload.disrupted_service_key and payload.disruption_kind:
        # Look the row up directly: the relationship collection is not
        # populated when rows are added by foreign key.
        disrupted = db.get(Segment, resolved[payload.disrupted_service_key].id) if (
            payload.disrupted_service_key in resolved
        ) else None
        if disrupted is not None:
            outcome = await _open_recovery(
                db,
                trip,
                actor,
                kind=payload.disruption_kind,
                segment=disrupted,
                delay_minutes=payload.delay_minutes,
            )
            result["cycle"] = outcome["cycle"]
            result["plans"] = [plan_payload(p) for p in outcome["plans"]]

    db.commit()
    db.refresh(trip)

    bus.publish(trip.id, "trip_created", {"trip_id": trip.id, "reference": trip.reference})
    if result["cycle"] is not None:
        bus.publish(
            trip.id,
            "recovery_started",
            {"cycle": result["cycle"], "plan_count": len(result["plans"])},
        )
    return result


@router.post("/{trip_id}/check")
def check(
    trip_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Re-check a built journey: connections, buffers and cascading effects."""
    trip = load_trip(db, trip_id)
    if trip is None or not _can_see(db, actor, trip):
        raise HTTPException(status_code=404, detail="Trip not found")
    return _check_journey(db, trip)


@router.post("/{trip_id}/recover")
async def recover(
    trip_id: str,
    payload: RecoverJourneyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Re-plan a built journey after a disruption, opening a new cycle."""
    trip = load_trip(db, trip_id)
    if trip is None or not _can_see(db, actor, trip):
        raise HTTPException(status_code=404, detail="Trip not found")

    if payload.disruption_kind not in {k.value for k in DisruptionKind}:
        raise HTTPException(status_code=422, detail="Unknown disruption kind")

    # Default to the leg that feeds the connection, so a missed-connection
    # check has something concrete to act on.
    segment = None
    if payload.service_key:
        segment = next((s for s in trip.segments if s.id == payload.service_key), None)
    if segment is None:
        ordered = sorted(trip.segments, key=lambda s: s.sequence)
        segment = ordered[0] if ordered else None

    already_broken = _check_journey(db, trip)
    if not already_broken["issues"]:
        return {
            "trip": trip_summary_payload(trip),
            "check": already_broken,
            "cycle": None,
            "plans": [],
            "message": "The journey checks out. No recovery cycle was needed.",
        }

    outcome = await _open_recovery(
        db,
        trip,
        actor,
        kind=payload.disruption_kind,
        segment=segment,
        delay_minutes=payload.delay_minutes,
    )
    db.commit()
    db.refresh(trip)

    plans = [plan_payload(p) for p in outcome["plans"]]
    bus.publish(trip.id, "recovery_started", {"cycle": outcome["cycle"], "plan_count": len(plans)})
    return {
        "trip": trip_summary_payload(trip),
        "check": already_broken,
        "cycle": outcome["cycle"],
        "plans": plans,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _can_see(db: Session, actor: User, trip: Trip) -> bool:
    from .deps import actor_can_access_trip

    return actor_can_access_trip(db, actor, trip)


async def _resolve_segments(payload: BuildJourneyRequest) -> dict[str, Segment]:
    """Re-resolve every chosen service from the datasets, server-side.

    The client sends only keys and codes. A key that no dataset offers is
    rejected rather than trusted, so a tampered request cannot invent a flight.

    Resolution uses the same live-first search the picker used, so a service
    chosen from a live departure board re-resolves to the same option here.
    There is no other way to accept a key the traveller was legitimately shown
    when the option came from a schedule provider rather than a stored
    catalogue.
    """
    resolved: dict[str, Segment] = {}
    for selection in payload.segments:
        day = date.fromisoformat(selection.date)
        leg = await builder.search_options_live(
            selection.origin.upper(), selection.destination.upper(), on_date=day
        )
        match = next((o for o in leg.options if o.key == selection.service_key), None)
        if match is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{selection.service_key!r} is not an available service for "
                    f"{selection.origin} to {selection.destination} on {selection.date}"
                ),
            )
        if match.segment_type.value != selection.mode:
            raise HTTPException(
                status_code=422,
                detail=f"{selection.service_key!r} is a {match.segment_type.value}, not a {selection.mode}",
            )
        resolved[selection.service_key] = _segment_row(match)
    return resolved


def _segment_row(option) -> Segment:
    from ..domain.reference import require_place

    origin_place = require_place(option.origin_code)
    destination_place = require_place(option.destination_code)
    return Segment(
        segment_type=option.segment_type.value,
        carrier_code=option.carrier_code,
        carrier_name=option.carrier_name,
        service_number=option.service_number,
        origin_code=option.origin_code,
        origin_name=origin_place.name,
        origin_tz=origin_place.tz,
        destination_code=option.destination_code,
        destination_name=destination_place.name,
        destination_tz=destination_place.tz,
        scheduled_departure_utc=ensure_utc(option.departure_utc),
        scheduled_arrival_utc=ensure_utc(option.arrival_utc),
        status=SegmentStatus.SCHEDULED.value,
        terminal=option.terminal,
        gate=option.gate,
        platform=option.platform,
        cabin=option.cabin,
        fare_class=option.fare_class,
        booking_reference=option.booking_reference,
        cost_minor=option.cost_minor,
        cost_currency=option.currency,
        refundable=option.refundable,
        distance_km=option.distance_km,
        provenance=option.provenance,
        source=_segment_source(option.provenance),
        fetched_at=datetime.now(timezone.utc),
    )


def _strongest_provenance(provenances: list[str]) -> str:
    """The strongest provenance among a set of persisted rows."""
    order = {"LIVE": 0, "CACHED": 1, "REFERENCE": 2, "SIMULATED": 3}
    if not provenances:
        return "UNAVAILABLE"
    return min(provenances, key=lambda p: order.get(p, 4))


def _segment_source(provenance: str) -> str:
    """The source label recorded against a persisted segment."""
    return {
        "LIVE": "Flight schedule provider",
        "CACHED": "Flight schedule provider (cached)",
        "REFERENCE": "DELFI / GTFS.de timetable",
    }.get(provenance, "Unknown source")


def _persist_trip(
    db: Session,
    actor: User,
    payload: BuildJourneyRequest,
    resolved: dict[str, Segment],
) -> Trip:
    # Order the legs by departure, which is the itinerary order.
    ordered = sorted(resolved.items(), key=lambda kv: kv[1].scheduled_departure_utc)
    first = ordered[0][1]
    last = ordered[-1][1]

    trip = Trip(
        reference=builder.new_reference(),
        name=payload.name,
        purpose=_REASON_LABELS.get(payload.reason, payload.reason),
        traveller_id=actor.id,
        origin_code=payload.origin.upper(),
        destination_code=payload.destination.upper(),
        starts_at_utc=first.scheduled_departure_utc,
        ends_at_utc=last.scheduled_arrival_utc,
        status=TripStatus.PLANNED.value,
    )
    db.add(trip)
    db.flush()

    for sequence, (_, segment) in enumerate(ordered, start=1):
        segment.trip_id = trip.id
        segment.sequence = sequence
        db.add(segment)
        # Append through the relationship as well: the recovery pipeline reads
        # ``trip.segments`` in memory during this request, before any reload.
        trip.segments.append(segment)
    db.flush()
    return trip


async def _attach_hotel_and_transfer(
    db: Session, trip: Trip, resolved: dict[str, Segment]
) -> None:
    """Add a hotel and a transfer when a real source answers for them.

    Hotel stays are only added when Amadeus returns a property and transfers
    only when Transitland returns GTFS stops. Nothing is invented for a city
    we cannot serve; the trip is simply built without them.
    """
    from ..domain.reference import require_place

    settings = get_settings()
    final = require_place(trip.destination_code)
    city = final.market
    arrival = trip.ends_at_utc

    hotels = await search_hotels(settings, city, nights=1)
    hotel_name = city
    if hotels:
        option = hotels[0]
        hotel_name = option.name
        check_in = arrival + timedelta(hours=2)
        check_out = check_in + timedelta(days=1)
        db.add(
            HotelStay(
                trip_id=trip.id,
                name=option.name,
                city_code=option.city_code,
                city_name=option.city_name,
                timezone=option.timezone,
                address=option.address,
                latitude=option.latitude,
                longitude=option.longitude,
                check_in_utc=check_in,
                check_out_utc=check_out,
                rooms=1,
                guests=1,
                status=BookingStatus.CONFIRMED.value,
                cost_minor=option.cost_minor,
                cost_currency=option.currency,
                refundable=option.refundable,
                provenance=option.provenance,
                source=option.source,
                fetched_at=datetime.now(timezone.utc),
            )
        )

    rides = await builder.transfer_options(city, arrival - timedelta(minutes=30))
    if rides:
        # Pick the transfer that leaves soonest after the traveller can be out
        # of arrivals; the constraint checker later rebooks it if plans change.
        ride = rides[0]
        db.add(
            GroundTransport(
                trip_id=trip.id,
                mode="transfer",
                provider_name=ride.service_number,
                from_label=_label_for(ride.origin_code),
                to_label=hotel_name,
                city_code=city,
                timezone=final.tz,
                pickup_utc=ensure_utc(ride.departure_utc),
                dropoff_utc=ensure_utc(ride.arrival_utc),
                status=BookingStatus.CONFIRMED.value,
                cost_minor=ride.cost_minor,
                cost_currency=ride.currency,
                provenance=ride.provenance,
                source="Transitland (GTFS)",
                fetched_at=datetime.now(timezone.utc),
            )
        )
    db.flush()


def _label_for(code: str) -> str:
    from ..domain.reference import require_place

    try:
        return require_place(code).name
    except KeyError:  # pragma: no cover - defensive
        return code


def _check_journey(db: Session, trip: Trip) -> dict:
    """Assess every connection in the itinerary, with local times and buffers."""
    ordered = sorted(trip.segments, key=lambda s: s.effective_departure_utc)
    legs: list[dict] = []
    issues: list[dict] = []

    for index, segment in enumerate(ordered):
        row = {
            "segment": segment_payload(segment),
            "connection": None,
            "arrival_shift_minutes": minutes_between(
                segment.scheduled_arrival_utc, segment.effective_arrival_utc
            ),
        }
        if index + 1 < len(ordered):
            nxt = ordered[index + 1]
            if nxt.origin_code == segment.destination_code:
                assessment = assess_connection(
                    airport_code=segment.destination_code,
                    arriving_at_utc=segment.effective_arrival_utc,
                    departing_at_utc=nxt.effective_departure_utc,
                )
                row["connection"] = {
                    "at": segment.destination_code,
                    "feasible": assessment.feasible,
                    "safety": safety_label(assessment.safety),
                    "safety_code": assessment.safety.value,
                    "buffer_minutes": assessment.buffer_minutes,
                    "required_minutes": assessment.required_minutes,
                    "shortfall_minutes": assessment.shortfall_minutes,
                    "note": assessment.note,
                    "mct_source": assessment.mct_source,
                    "mct_verified_on": assessment.mct_verified_on,
                }
                if not assessment.feasible:
                    issues.append(
                        {
                            "kind": "missed_connection",
                            "at": segment.destination_code,
                            "segment_id": nxt.id,
                            "service_number": nxt.service_number,
                            "shortfall_minutes": assessment.shortfall_minutes,
                            "required_minutes": assessment.required_minutes,
                            "detail": (
                                f"{segment.destination_code} connection is {assessment.shortfall_minutes} "
                                f"minutes short of the {assessment.required_minutes} minute minimum."
                            ),
                        }
                    )
        legs.append(row)

    return {
        "trip_id": trip.id,
        "reference": trip.reference,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "segment_count": len(ordered),
        "connection_count": sum(1 for leg in legs if leg["connection"]),
        "healthy": not issues,
        "issues": issues,
        "legs": legs,
        "hotel": [h.name for h in trip.hotels],
        "ground": [g.mode for g in trip.ground],
    }


async def _open_recovery(
    db: Session,
    trip: Trip,
    actor: User,
    *,
    kind: str,
    segment: Segment | None,
    delay_minutes: int,
) -> dict:
    """Detect, assess and generate plans for a built journey.

    Returns the new cycle number and the plans it produced. The rows are added
    through foreign keys, so ``trip.disruptions`` is not relied on here.
    """
    from ..models import MonitoringState

    settings = get_settings()
    disruption = pipeline.detect_disruption(
        db,
        trip=trip,
        kind=DisruptionKind(kind),
        segment_id=segment.id if segment else None,
        delay_minutes=delay_minutes,
        detail=None,
        payload={"injected_by": actor.email, "origin": "journey_builder"},
        provenance="SIMULATED",
        source="Journey builder",
    )
    impact = pipeline.assess_impact(db, trip=trip, disruption=disruption)
    disruption.payload = {**(disruption.payload or {}), "impact": impact}
    pipeline.notification_for_disruption(db, trip=trip, disruption=disruption)

    constraints = pipeline.build_constraints(db, trip=trip)
    plans = await pipeline.generate_plans(
        db,
        trip=trip,
        disruption=disruption,
        constraints=constraints,
        settings=settings,
        llm=build_router(settings),
    )
    trip.status = TripStatus.RECOVERING.value

    state = db.get(MonitoringState, trip.id)
    if state is None:
        db.add(MonitoringState(trip_id=trip.id, cycle=disruption.cycle, watching=True))
    else:
        state.cycle = disruption.cycle
        state.watching = True
    db.flush()

    plans.sort(key=lambda p: p.score or 0, reverse=True)
    return {"cycle": disruption.cycle, "plans": plans, "impact": impact, "disruption": disruption}


def safety_label(safety) -> str:
    from ..serializers import safety_label as _label

    return _label(safety)
