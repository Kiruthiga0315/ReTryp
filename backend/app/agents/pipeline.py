"""The recovery pipeline.

One function per stage, each one independently testable:

``detect -> assess -> search -> constrain -> generate -> score -> present``
``-> [approval] -> execute -> monitor``

The stages are also exposed as a LangGraph graph (``graph.py``) so the
escalation path can re-enter the pipeline when an active plan becomes
invalid. The service functions are the source of truth; the graph is a thin
sequencer over them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..domain.compensation import estimate, is_delay_extraordinary
from ..domain.enums import (
    AuditAction,
    BookingStatus,
    DisruptionKind,
    DisruptionStatus,
    NotificationKind,
    PlanStatus,
    RiskLevel,
    SegmentStatus,
    Severity,
    TripStatus,
)
from ..domain.impact import (
    GroundSnapshot,
    HotelSnapshot,
    SegmentSnapshot,
    assess_itinerary_impact,
)
from ..domain.money import Money
from ..domain.options import OptionSegment
from ..domain.recovery import (
    PlanDraft,
    ScoredPlan,
    build_plan_drafts,
    choose_recommended,
    describe_arrival_delta,
    find_recovery_target,
    score_drafts,
)
from ..domain.reference import require_place
from ..domain.timeutil import format_duration, format_local, minutes_between
from ..domain.visa import VERIFY_REMINDER, applicable_rules, find_rule
from ..llm.router import LLMRouter, PlanExplanation
from ..llm.templates import (
    disruption_notification,
    plan_body,
    plan_headline,
    plan_tradeoffs,
)
from ..models import (
    AuditLog,
    Disruption,
    GroundTransport,
    HotelStay,
    MonitoringState,
    Notification,
    PlanAction,
    RecoveryPlan,
    Segment,
    Trip,
    TripEvent,
    User,
    utcnow,
)
from ..providers.data import search_hotels
from ..providers.options import search_recovery_options
from .schemas import (
    Alternative,
    ConstraintSet,
    DisruptionEvent,
    PlanSegmentPayload,
)

# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def snapshot_segments(trip: Trip) -> list[SegmentSnapshot]:
    return [
        SegmentSnapshot(
            id=s.id,
            sequence=s.sequence,
            segment_type=s.segment_type,
            origin_code=s.origin_code,
            destination_code=s.destination_code,
            scheduled_departure_utc=s.scheduled_departure_utc,
            scheduled_arrival_utc=s.scheduled_arrival_utc,
            effective_departure_utc=s.effective_departure_utc,
            effective_arrival_utc=s.effective_arrival_utc,
            status=s.status,
            carrier_code=s.carrier_code,
            service_number=s.service_number,
            booking_reference=s.booking_reference,
            is_recovery=s.is_recovery,
        )
        for s in sorted(trip.segments, key=lambda x: x.sequence)
    ]


def snapshot_hotels(trip: Trip) -> list[HotelSnapshot]:
    return [
        HotelSnapshot(
            id=h.id,
            name=h.name,
            city_code=h.city_code,
            check_in_utc=h.check_in_utc,
            check_out_utc=h.check_out_utc,
            booking_reference=h.booking_reference,
            late_arrival_notice=h.late_arrival_notice,
            refundable=bool(h.refundable),
            cost_minor=h.cost_minor or 0,
            currency=h.cost_currency or "EUR",
            provenance=h.provenance or "UNAVAILABLE",
        )
        for h in trip.hotels
    ]


def snapshot_ground(trip: Trip) -> list[GroundSnapshot]:
    return [
        GroundSnapshot(
            id=g.id,
            mode=g.mode,
            from_label=g.from_label,
            to_label=g.to_label,
            city_code=g.city_code,
            pickup_utc=g.pickup_utc,
            booking_reference=g.booking_reference,
        )
        for g in trip.ground
    ]


# ---------------------------------------------------------------------------
# Baseline and reset
# ---------------------------------------------------------------------------

# Fields a recovery cycle rewrites. Capturing them before the first cycle is
# what lets a disrupted itinerary be restored to the original booking.
_SEGMENT_BASELINE_FIELDS = (
    "sequence",
    "segment_type",
    "carrier_code",
    "carrier_name",
    "service_number",
    "origin_code",
    "origin_name",
    "origin_tz",
    "destination_code",
    "destination_name",
    "destination_tz",
    "scheduled_departure_utc",
    "scheduled_arrival_utc",
    "estimated_departure_utc",
    "estimated_arrival_utc",
    "actual_departure_utc",
    "actual_arrival_utc",
    "status",
    "booking_reference",
    "terminal",
    "gate",
    "platform",
    "cabin",
    "fare_class",
    "cost_minor",
    "cost_currency",
    "refundable",
    "distance_km",
    "provenance",
    "source",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_baseline_dt(value) -> datetime | None:
    return _parse_dt(value) if value else None


def capture_baseline(trip: Trip) -> dict:
    """Snapshot the itinerary as loaded, before any recovery touched it."""
    return {
        "trips": {
            "status": trip.status,
            "origin_code": trip.origin_code,
            "destination_code": trip.destination_code,
        },
        "segments": [
            {
                "id": s.id,
                **{f: (_iso(getattr(s, f)) if isinstance(getattr(s, f), datetime) else getattr(s, f))
                   for f in _SEGMENT_BASELINE_FIELDS},
            }
            for s in sorted(trip.segments, key=lambda x: x.sequence)
        ],
        "hotels": [
            {
                "id": h.id,
                "status": h.status,
                "check_in_utc": _iso(h.check_in_utc),
                "check_out_utc": _iso(h.check_out_utc),
                "late_arrival_notice": h.late_arrival_notice,
            }
            for h in trip.hotels
        ],
        "ground": [
            {
                "id": g.id,
                "status": g.status,
                "pickup_utc": _iso(g.pickup_utc),
                "dropoff_utc": _iso(g.dropoff_utc),
            }
            for g in trip.ground
        ],
    }


def ensure_baseline(db: Session, *, trip: Trip) -> dict:
    """Capture the baseline once, the first time a trip is seen."""
    if not trip.baseline:
        trip.baseline = capture_baseline(trip)
        db.flush()
    return trip.baseline


def reset_trip_recovery(db: Session, *, trip: Trip, actor: User | None = None) -> dict:
    """Return a trip to its pre-disruption state and remove the recovery history.

    Deletes every disruption and plan (and the cascade of actions under them),
    removes recovered segments, ground transport and notifications created by
    recovery, restores the baseline itinerary, and clears monitoring and any
    open trip-level events. Manual bookings added to the itinerary are kept;
    only recovery artefacts are removed, so re-injecting a disruption starts a
    clean cycle 1 instead of stacking on top of the old one.
    """
    baseline = ensure_baseline(db, trip=trip)
    removed = {"disruptions": 0, "plans": 0, "segments": 0, "ground": 0, "notifications": 0}

    # Disruptions own their plans; deleting them cascades to PlanAction.
    for disruption in list(trip.disruptions):
        removed["plans"] += len(disruption.plans)
        db.delete(disruption)
        removed["disruptions"] += 1
    trip.disruptions.clear()

    # Recovered legs and the ground transport a plan added are recovery
    # artefacts, not part of the booked itinerary.
    for segment in list(trip.segments):
        if segment.is_recovery:
            db.delete(segment)
            trip.segments.remove(segment)
            removed["segments"] += 1
    for ride in list(trip.ground):
        if ride.source == "Recovery plan":
            db.delete(ride)
            trip.ground.remove(ride)
            removed["ground"] += 1

    for notification in db.scalars(
        select(Notification).where(Notification.trip_id == trip.id)
    ).all():
        db.delete(notification)
        removed["notifications"] += 1

    db.flush()
    _restore_baseline(db, trip=trip, baseline=baseline)

    state = db.get(MonitoringState, trip.id)
    if state is not None:
        state.active_plan_id = None
        state.cycle = 0
        state.watching = True
        state.last_result = {}
        state.last_checked_utc = None
    db.flush()

    db.add(
        AuditLog(
            trip_id=trip.id,
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=AuditAction.RECOVERY_RESET.value,
            summary=f"Recovery state reset for trip {trip.reference}",
            detail={"removed": removed},
        )
    )
    db.flush()
    return removed


def _restore_baseline(db: Session, *, trip: Trip, baseline: dict) -> None:
    """Put the itinerary back to its captured values."""
    segment_rows = {s.id: s for s in trip.segments}
    for record in baseline.get("segments", []):
        segment = segment_rows.get(record["id"])
        if segment is None:
            continue
        for field in _SEGMENT_BASELINE_FIELDS:
            if field not in record:
                continue
            value = record[field]
            if isinstance(value, str) and field.endswith("_utc"):
                value = _parse_baseline_dt(value)
            setattr(segment, field, value)

    hotel_rows = {h.id: h for h in trip.hotels}
    for record in baseline.get("hotels", []):
        stay = hotel_rows.get(record["id"])
        if stay is None:
            continue
        stay.status = record.get("status", stay.status)
        stay.late_arrival_notice = record.get("late_arrival_notice", stay.late_arrival_notice)
        if record.get("check_in_utc"):
            stay.check_in_utc = _parse_baseline_dt(record["check_in_utc"])
        if record.get("check_out_utc"):
            stay.check_out_utc = _parse_baseline_dt(record["check_out_utc"])

    ride_rows = {g.id: g for g in trip.ground}
    for record in baseline.get("ground", []):
        ride = ride_rows.get(record["id"])
        if ride is None:
            continue
        ride.status = record.get("status", ride.status)
        if record.get("pickup_utc"):
            ride.pickup_utc = _parse_baseline_dt(record["pickup_utc"])
        if record.get("dropoff_utc"):
            ride.dropoff_utc = _parse_baseline_dt(record["dropoff_utc"])

    trip.status = baseline.get("trips", {}).get("status", TripStatus.ACTIVE.value)
    db.flush()


def supersede_open_cycles(db: Session, *, trip: Trip, keep: Disruption) -> int:
    """Close any earlier open cycle once a new disruption is recorded.

    A trip has one open disruption at a time: the newest. Older ones that were
    never resolved are marked superseded so the Recovery Center and the
    dashboard show a single active incident instead of a stack of them.
    """
    stale = list(
        db.scalars(
            select(Disruption).where(
                Disruption.trip_id == trip.id,
                Disruption.id != keep.id,
                Disruption.status.in_(
                    [
                        DisruptionStatus.DETECTED.value,
                        DisruptionStatus.VALIDATED.value,
                        DisruptionStatus.ASSESSED.value,
                        DisruptionStatus.RECOVERING.value,
                    ]
                ),
            )
        ).all()
    )
    for disruption in stale:
        disruption.status = DisruptionStatus.SUPERSEDED.value
        disruption.resolved_at_utc = utcnow()
        for plan in disruption.plans:
            if plan.status == PlanStatus.PROPOSED.value:
                plan.status = PlanStatus.SUPERSEDED.value
    if stale:
        db.flush()
    return len(stale)


# ---------------------------------------------------------------------------
# Stage: detect
# ---------------------------------------------------------------------------


def detect_disruption(
    db: Session,
    *,
    trip: Trip,
    kind: DisruptionKind,
    segment_id: str | None = None,
    hotel_id: str | None = None,
    ground_id: str | None = None,
    delay_minutes: int = 0,
    detail: str | None = None,
    payload: dict | None = None,
    provenance: str = "SIMULATED",
    source: str = "Scenario Simulator",
) -> Disruption:
    """Record a disruption and open a recovery cycle.

    The Scenario Simulator calls this to inject a disruption; the monitoring
    loop calls the same function when a live provider reports one.
    """
    cycle = (trip.disruptions and max(d.cycle for d in trip.disruptions) or 0) + 1

    segment = db.get(Segment, segment_id) if segment_id else None
    service = segment.service_number if segment else None
    title, default_detail = _disruption_copy(kind, segment, delay_minutes, detail)

    disruption = Disruption(
        trip_id=trip.id,
        segment_id=segment_id,
        hotel_id=hotel_id,
        ground_id=ground_id,
        kind=kind.value,
        status="detected",
        severity=_severity_for(kind, delay_minutes).value,
        title=title,
        detail=detail or default_detail,
        delay_minutes=delay_minutes or None,
        provenance=provenance,
        source=source,
        payload=payload or {},
        cycle=cycle,
    )
    db.add(disruption)

    # Apply the disruption to the affected segment so every downstream
    # calculation works from the same effective times.
    if segment is not None:
        if kind == DisruptionKind.FLIGHT_CANCELLATION:
            segment.status = SegmentStatus.CANCELLED.value
        elif delay_minutes:
            segment.estimated_departure_utc = segment.scheduled_departure_utc + timedelta(minutes=delay_minutes)
            segment.estimated_arrival_utc = segment.scheduled_arrival_utc + timedelta(minutes=delay_minutes)
            segment.status = SegmentStatus.DELAYED.value
        if kind == DisruptionKind.MISSED_CONNECTION:
            segment.status = SegmentStatus.MISSED.value
    if hotel_id:
        stay = db.get(HotelStay, hotel_id)
        if stay is not None:
            stay.status = BookingStatus.CHANGE_REQUESTED.value
    if ground_id:
        ride = db.get(GroundTransport, ground_id)
        if ride is not None:
            ride.status = BookingStatus.CHANGE_REQUESTED.value

    trip.status = TripStatus.DISRUPTED.value

    db.add(
        TripEvent(
            trip_id=trip.id,
            kind="disruption_detected",
            title=title,
            detail=detail or default_detail,
            segment_id=segment_id,
            payload={"kind": kind.value, "delay_minutes": delay_minutes, "cycle": cycle},
            provenance=provenance,
        )
    )
    db.add(
        AuditLog(
            trip_id=trip.id,
            action=AuditAction.DISRUPTION_DETECTED.value,
            summary=f"{title} on trip {trip.reference}",
            detail={
                "kind": kind.value,
                "delay_minutes": delay_minutes,
                "cycle": cycle,
                "provenance": provenance,
                "source": source,
            },
        )
    )
    db.flush()
    # One open incident per trip: the newest. Anything still open from an
    # earlier cycle is closed, so re-injecting does not stack duplicate cards.
    supersede_open_cycles(db, trip=trip, keep=disruption)
    return disruption


def _disruption_copy(
    kind: DisruptionKind, segment: Segment | None, delay_minutes: int, detail: str | None
) -> tuple[str, str]:
    service = segment.service_number if segment else "The journey"
    origin = segment.origin_code if segment else ""
    destination = segment.destination_code if segment else ""
    delay = format_duration(delay_minutes) if delay_minutes else ""

    table = {
        DisruptionKind.FLIGHT_DELAY: (
            f"{service} delayed {delay}",
            f"{service} from {origin} to {destination} is delayed {delay}.",
        ),
        DisruptionKind.FLIGHT_CANCELLATION: (
            f"{service} cancelled",
            f"{service} from {origin} to {destination} has been cancelled.",
        ),
        DisruptionKind.MISSED_CONNECTION: (
            f"Connection at {origin} missed",
            f"The connection at {origin} is no longer feasible.",
        ),
        DisruptionKind.WEATHER: (
            f"Weather event affecting {origin or 'the journey'}",
            "Severe weather is affecting operations on this route.",
        ),
        DisruptionKind.AIRPORT_DISRUPTION: (
            f"Airport disruption at {origin or 'the departure airport'}",
            "Airport operations are restricted.",
        ),
        DisruptionKind.DENIED_BOARDING: (
            f"Denied boarding on {service}",
            "The traveller was denied boarding on a confirmed ticket.",
        ),
        DisruptionKind.GROUND_TRANSPORT: (
            "Ground transport disruption",
            "The ground transport booking is no longer viable.",
        ),
        DisruptionKind.HOTEL_CANCELLATION: (
            "Hotel booking cancelled",
            "The hotel has cancelled the reservation.",
        ),
        DisruptionKind.VISA_TRANSIT: (
            "Visa or transit restriction",
            f"A visa or transit restriction applies. {VERIFY_REMINDER}",
        ),
    }
    title, default = table.get(kind, ("Journey disrupted", "The itinerary has been disrupted."))
    return title, detail or default


def _severity_for(kind: DisruptionKind, delay_minutes: int) -> Severity:
    if kind in {
        DisruptionKind.FLIGHT_CANCELLATION,
        DisruptionKind.MISSED_CONNECTION,
        DisruptionKind.DENIED_BOARDING,
    }:
        return Severity.CRITICAL
    if kind in {DisruptionKind.HOTEL_CANCELLATION, DisruptionKind.VISA_TRANSIT}:
        return Severity.HIGH
    if delay_minutes >= 180:
        return Severity.HIGH
    if delay_minutes >= 60:
        return Severity.MEDIUM
    return Severity.LOW


# ---------------------------------------------------------------------------
# Stage: assess
# ---------------------------------------------------------------------------


def assess_impact(db: Session, *, trip: Trip, disruption: Disruption) -> dict:
    """Analyse the effect of the disruption across the whole journey."""
    segments = snapshot_segments(trip)
    hotels = snapshot_hotels(trip)
    ground = snapshot_ground(trip)

    kind = DisruptionKind(disruption.kind)
    assessment = assess_itinerary_impact(
        segments=segments,
        hotels=hotels,
        ground=ground,
        disrupted_segment_id=disruption.segment_id,
        delay_minutes=disruption.delay_minutes or 0,
        cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
        missed_connection=kind == DisruptionKind.MISSED_CONNECTION,
        baggage_recheck=bool(disruption.payload.get("baggage_recheck")),
    )

    # Mark the downstream segment missed in the database, so the timeline and
    # the bookings screen agree with the impact analysis.
    for item in assessment.items:
        if item.kind == "segment_missed" and item.segment_id:
            segment = db.get(Segment, item.segment_id)
            if segment is not None and segment.status not in {
                SegmentStatus.CANCELLED.value,
                SegmentStatus.MISSED.value,
            }:
                segment.status = SegmentStatus.MISSED.value

    disruption.status = "assessed"
    db.add(
        TripEvent(
            trip_id=trip.id,
            kind="impact_assessed",
            title=assessment.summary,
            detail="; ".join(i.title for i in assessment.items if i.requires_action),
            payload={"severity": assessment.severity.value, "items": len(assessment.items)},
            provenance="SIMULATED",
        )
    )
    db.add(
        AuditLog(
            trip_id=trip.id,
            action=AuditAction.IMPACT_ASSESSED.value,
            summary=f"Impact assessed: {assessment.summary}",
            detail={
                "severity": assessment.severity.value,
                "connection_safety": assessment.connection_safety.value,
                "actions_required": [i.kind for i in assessment.items if i.requires_action],
            },
        )
    )
    db.flush()

    return {
        "severity": assessment.severity.value,
        "connection_safety": assessment.connection_safety.value,
        "summary": assessment.summary,
        "final_arrival_shift_minutes": assessment.final_arrival_shift_minutes,
        "items": [
            {
                "kind": item.kind,
                "severity": item.severity.value,
                "title": item.title,
                "detail": item.detail,
                "segment_id": item.segment_id,
                "hotel_id": item.hotel_id,
                "ground_id": item.ground_id,
                "delta_minutes": item.delta_minutes,
                "delta_display": format_duration(item.delta_minutes) if item.delta_minutes else None,
                "requires_action": item.requires_action,
            }
            for item in assessment.items
        ],
        "connections": [
            {
                "airport_code": a.airport_code,
                "feasible": a.feasible,
                "safety": a.safety.value,
                "label": a.label,
                "buffer_minutes": a.buffer_minutes,
                "required_minutes": a.required_minutes,
                "shortfall_minutes": a.shortfall_minutes,
                "note": a.note,
                "mct_source": a.mct_source,
                "mct_verified_on": a.mct_verified_on,
            }
            for a in assessment.connection_assessments
        ],
    }


# ---------------------------------------------------------------------------
# Stage: constraints
# ---------------------------------------------------------------------------


def build_constraints(db: Session, *, trip: Trip) -> ConstraintSet:
    """Assemble the traveller's constraints from profile, visa and policy."""
    traveller: User | None = trip.traveller
    destinations = sorted({s.destination_code for s in trip.segments})
    countries = sorted({require_place(code).country for code in destinations})

    visa_notes: list[str] = []
    transit_restrictions: list[str] = []
    if traveller and traveller.passport_nationality:
        rules = applicable_rules(traveller.passport_nationality, countries)
        for rule in rules:
            note = (
                f"{rule.destination} {rule.purpose.replace('_', ' ')}: "
                f"{rule.requirement.replace('_', ' ')}. {rule.detail} "
                f"(source {rule.source_url}, last verified {rule.verified_on}). {VERIFY_REMINDER}"
            )
            visa_notes.append(note)
            if rule.requirement in {"visa_required", "transit_visa_required"}:
                transit_restrictions.append(
                    f"{rule.requirement.replace('_', ' ').capitalize()} for {rule.destination} "
                    f"({rule.purpose.replace('_', ' ')})"
                )
        transit_rule = find_rule(traveller.passport_nationality, "DE", "transit_landside")
        if transit_rule is not None:
            transit_restrictions.append(transit_rule.detail)

    return ConstraintSet(
        traveller_id=trip.traveller_id,
        nationality=traveller.passport_nationality if traveller else None,
        passport_expiring_soon=False,
        visa_notes=visa_notes,
        transit_restrictions=transit_restrictions,
        requires_baggage_recheck=False,
        preferred_airlines=(traveller.preferred_airlines if traveller else []) or [],
        preferred_cabin=traveller.preferred_cabin if traveller else None,
        budget_minor=traveller.budget_minor if traveller else None,
        budget_currency=(traveller.budget_currency if traveller else "EUR") or "EUR",
        accessibility_needs=traveller.accessibility_needs if traveller else None,
        policy_notes=[
            "Plans above the traveller's budget are shown but never marked as recommended.",
            "Passport details are never sent to a provider or written to a log.",
        ],
    )


# ---------------------------------------------------------------------------
# Stage: search
# ---------------------------------------------------------------------------


async def search_alternatives(
    db: Session,
    *,
    trip: Trip,
    disruption: Disruption,
    settings: Settings,
) -> list[OptionSegment]:
    """Ask the provider layer for options on the affected leg."""
    del db
    segments = snapshot_segments(trip)
    kind = DisruptionKind(disruption.kind)
    target = find_recovery_target(
        segments,
        disruption.segment_id,
        cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
        missed_connection=kind == DisruptionKind.MISSED_CONNECTION,
    )
    if target is None:
        return []

    return await search_recovery_options(
        settings,
        origin=target.origin_code,
        destination=target.destination_code,
        depart_after_utc=target.available_from_utc,
    )


# ---------------------------------------------------------------------------
# Stage: generate + score
# ---------------------------------------------------------------------------


async def generate_plans(
    db: Session,
    *,
    trip: Trip,
    disruption: Disruption,
    constraints: ConstraintSet,
    settings: Settings,
    llm: LLMRouter,
) -> list[RecoveryPlan]:
    """Build, score and persist every feasible recovery plan."""
    segments = snapshot_segments(trip)
    hotels = snapshot_hotels(trip)
    ground = snapshot_ground(trip)
    kind = DisruptionKind(disruption.kind)

    target = find_recovery_target(
        segments,
        disruption.segment_id,
        cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
        missed_connection=kind == DisruptionKind.MISSED_CONNECTION,
    )
    if target is None:
        # An intermediate delay absorbed at the connection. There is nothing to
        # replace, but the disruption still warrants a single decision for the
        # traveller - keep the itinerary - so this is handed to the planner to
        # record rather than dropped on the floor.
        drafts = build_plan_drafts(
            segments=segments,
            hotels=hotels,
            ground=ground,
            disrupted_segment_id=disruption.segment_id,
            delay_minutes=disruption.delay_minutes or 0,
            cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
            missed_connection=kind == DisruptionKind.MISSED_CONNECTION,
            flight_options=[],
            rail_options=[],
            transfer_options=[],
            preferred_airlines=constraints.preferred_airlines,
            preferred_cabin=constraints.preferred_cabin,
            currency=constraints.budget_currency,
        )
        if not drafts:
            disruption.status = "recovering"
            db.flush()
            return []
        return await _persist_plans(
            db,
            trip=trip,
            disruption=disruption,
            segments=segments,
            drafts=drafts,
            constraints=constraints,
            llm=llm,
        )

    available_from = target.available_from_utc

    found = await search_recovery_options(
        settings,
        origin=target.origin_code,
        destination=target.destination_code,
        depart_after_utc=available_from,
    )
    flight_options = [o for o in found if o.segment_type.value == "flight"]
    rail_options = [o for o in found if o.segment_type.value == "train"]
    bus_options = [o for o in found if o.segment_type.value == "bus"]

    # Bridge through a hub for multimodal/connecting alternatives
    from ..domain.itineraries import connectable_itineraries
    from ..domain.timeutil import zone_for

    # The departure day is local to the leg's origin, not to UTC.
    hub_day = available_from.astimezone(zone_for(target.origin_code)).date()
    hub_itineraries = connectable_itineraries(
        target.origin_code, target.destination_code, hub_day
    )

    from ..providers.data import get_transfers

    # Fetch transfers for every city that has ground transport on this trip.
    # The disrupted leg's airport is not necessarily where the traveller ends
    # up: the orphaned transfer is the one at the final destination.
    transfer_options = []
    for city_code in sorted({g.city_code for g in trip.ground}):
        transfer_options.extend(await get_transfers(settings, city_code, available_from))

    # An extra night near the airport where the traveller is stuck, quoted
    # from the hotel provider.
    overnight = None
    if disruption.delay_minutes and disruption.delay_minutes >= 120:
        candidates = await search_hotels(settings, target.origin_market, nights=1)
        if candidates:
            cheapest = min(candidates, key=lambda h: h.cost_minor or 10**9)
            overnight = {
                "name": cheapest.name,
                "cost_minor": cheapest.cost_minor,
                "cost_currency": cheapest.currency,
                "provenance": cheapest.provenance,
            }

    drafts = build_plan_drafts(
        segments=segments,
        hotels=hotels,
        ground=ground,
        disrupted_segment_id=disruption.segment_id,
        delay_minutes=disruption.delay_minutes or 0,
        cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
        missed_connection=kind == DisruptionKind.MISSED_CONNECTION,
        flight_options=flight_options,
        rail_options=rail_options,
        bus_options=bus_options,
        transfer_options=transfer_options,
        overnight_hotel=overnight,
        preferred_airlines=constraints.preferred_airlines,
        preferred_cabin=constraints.preferred_cabin,
        currency=constraints.budget_currency,
        hub_itineraries=hub_itineraries,
    )

    if not drafts:
        disruption.status = "recovering"
        db.flush()
        return []

    return await _persist_plans(
        db,
        trip=trip,
        disruption=disruption,
        segments=segments,
        drafts=drafts,
        constraints=constraints,
        llm=llm,
    )


async def _persist_plans(
    db: Session,
    *,
    trip: Trip,
    disruption: Disruption,
    segments: list[SegmentSnapshot],
    drafts: list[PlanDraft],
    constraints: ConstraintSet,
    llm: LLMRouter,
) -> list[RecoveryPlan]:
    """Score, rank, persist and explain a set of plan drafts.

    Shared by both recovery shapes: a broken leg with replacements, and an
    absorbed delay whose only plan is the itinerary the traveller already has.
    """
    original_duration = minutes_between(
        segments[0].scheduled_departure_utc, segments[-1].scheduled_arrival_utc
    )
    scored = score_drafts(drafts, original_duration, segments[-1].scheduled_arrival_utc)
    recommended = choose_recommended(scored)

    # Present plans ranked best-first, and letter them in that order so the
    # list reads A, B, C, D with the recommended plan always A. Labels are
    # assigned after scoring because the build order (direct flight, rail,
    # later flight, next-morning, hub) is not the preference order.
    scored.sort(key=lambda s: (s.draft is not recommended.draft if recommended else False, -s.score.total))
    for offset, scored_plan in enumerate(scored):
        letter = chr(ord("A") + offset)
        scored_plan.draft.label = letter
        scored_plan.score.label = letter
        scored_plan.score.plan_id = letter

    compensation = estimate_compensation_for_plan(
        trip=trip, disruption=disruption, segments=segments
    )

    persisted: list[RecoveryPlan] = []
    for scored_plan in scored:
        draft = scored_plan.draft
        payload_segments = [
            _plan_segment_payload(leg, constraints) for leg in draft.legs
        ]
        plan = RecoveryPlan(
            disruption_id=disruption.id,
            trip_id=trip.id,
            cycle=disruption.cycle,
            label=draft.label,
            title=draft.title,
            summary=draft.summary,
            status=PlanStatus.PROPOSED.value,
            recommended=bool(recommended and recommended.draft.label == draft.label),
            score=scored_plan.score.total,
            score_breakdown=scored_plan.score.components,
            decision_factors=scored_plan.score.factors,
            arrival_utc=draft.arrival_utc or segments[-1].scheduled_arrival_utc,
            original_arrival_utc=segments[-1].scheduled_arrival_utc,
            total_duration_minutes=draft.total_duration_minutes or original_duration,
            additional_cost_minor=draft.additional_cost_minor,
            currency=draft.currency,
            refund_estimate_minor=draft.refund_estimate_minor,
            risk_level=draft.risk_level.value,
            connection_safety=draft.connection_safety.value,
            segments=[s.model_dump(mode="json") for s in payload_segments],
            hotel_changes=draft.hotel_changes,
            ground_transport=draft.ground_transport,
            restrictions=_plan_restrictions(draft, constraints),
            compensation=compensation,
            provenance="SIMULATED",
        )
        db.add(plan)
        persisted.append(plan)

    db.flush()

    # Explanations: one batched request, cached by plan id and version.
    await generate_explanations(
        db, plans=persisted, disruption=disruption, segments=segments, llm=llm
    )

    disruption.status = "recovering"
    trip.status = TripStatus.RECOVERING.value
    db.add(
        TripEvent(
            trip_id=trip.id,
            kind="plans_generated",
            title=f"{len(persisted)} recovery plans prepared",
            detail="; ".join(f"{p.label}: {p.title}" for p in persisted),
            payload={"plans": [p.label for p in persisted], "cycle": disruption.cycle},
            provenance="SIMULATED",
        )
    )
    db.add(
        AuditLog(
            trip_id=trip.id,
            action=AuditAction.PLAN_GENERATED.value,
            summary=f"{len(persisted)} plans generated for cycle {disruption.cycle}",
            detail={
                "plans": [
                    {"label": p.label, "score": round(p.score, 2), "recommended": p.recommended}
                    for p in persisted
                ]
            },
        )
    )
    db.flush()
    return persisted


def _plan_segment_payload(leg, constraints: ConstraintSet) -> PlanSegmentPayload:
    option = leg.option
    origin = require_place(option.origin_code)
    destination = require_place(option.destination_code)
    return PlanSegmentPayload(
        key=option.key,
        mode=option.segment_type.value,
        carrier_code=option.carrier_code,
        carrier_name=option.carrier_name,
        service_number=option.service_number,
        origin_code=option.origin_code,
        origin_name=origin.name,
        origin_tz=origin.tz,
        destination_code=option.destination_code,
        destination_name=destination.name,
        destination_tz=destination.tz,
        departure_utc=option.departure_utc,
        arrival_utc=option.arrival_utc,
        departure_local=format_local(option.departure_utc, option.origin_code, with_date=True),
        arrival_local=format_local(option.arrival_utc, option.destination_code, with_date=True),
        duration_minutes=option.duration_minutes,
        cost_minor=option.cost_minor,
        currency=option.currency,
        refundable=option.refundable,
        cabin=option.cabin or constraints.preferred_cabin,
        fare_class=option.fare_class,
        platform=option.platform,
        terminal=option.terminal,
        gate=option.gate,
        connection_safety=leg.connection_safety.value,
        buffer_minutes=leg.buffer_minutes,
        required_minutes=leg.required_minutes,
        provenance=option.provenance,
        note=option.note,
    )


def _plan_restrictions(draft: PlanDraft, constraints: ConstraintSet) -> list[str]:
    restrictions = list(dict.fromkeys(draft.restrictions))
    if constraints.budget_minor and draft.additional_cost_minor > constraints.budget_minor:
        restrictions.append(
            f"Additional cost {Money(draft.additional_cost_minor, draft.currency)} exceeds the "
            f"traveller's budget of {Money(constraints.budget_minor, constraints.budget_currency)}."
        )
    if constraints.transit_restrictions:
        restrictions.extend(constraints.transit_restrictions[:2])
    if constraints.accessibility_needs:
        restrictions.append(
            "Accessibility requirement on file; confirm assistance is available on each replacement leg."
        )
    return restrictions


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------


def estimate_compensation_for_plan(
    *, trip: Trip, disruption: Disruption, segments: list[SegmentSnapshot]
) -> dict:
    """Estimate passenger-rights eligibility for this disruption."""
    index = next((i for i, s in enumerate(segments) if s.id == disruption.segment_id), None)
    if index is None:
        return {"outcome": "not_eligible", "basis": "none", "factors": ["No affected flight segment"]}

    disrupted = segments[index]
    origin_country = require_place(disrupted.origin_code).country
    destination_country = require_place(disrupted.destination_code).country

    from ..domain.geo import distance_between_places

    distance = distance_between_places(segments[0].origin_code, segments[-1].destination_code)
    carrier_country = _carrier_region(disrupted.carrier_code)

    delay = disruption.delay_minutes or 0
    kind = DisruptionKind(disruption.kind)

    estimate_result = estimate(
        departure_country=origin_country,
        carrier_country=carrier_country,
        distance_km=distance,
        delay_minutes=delay,
        one_way_fare_minor=disrupted_fare_minor(trip, disrupted),
        fare_currency=_trip_currency(trip),
        block_minutes=minutes_between(
            disrupted.scheduled_departure_utc, disrupted.scheduled_arrival_utc
        ),
        extraordinary_circumstances=is_delay_extraordinary(kind.value),
        re_routed=True,
        denied_boarding=kind == DisruptionKind.DENIED_BOARDING,
        cancelled=kind == DisruptionKind.FLIGHT_CANCELLATION,
        overnight_delay=delay > 720,
    )
    payload = estimate_result.to_payload()
    payload["route"] = f"{segments[0].origin_code} to {segments[-1].destination_code}"
    payload["departure_country"] = origin_country
    payload["destination_country"] = destination_country
    return payload


def disrupted_fare_minor(trip: Trip, disrupted: SegmentSnapshot) -> int:
    segment = next((s for s in trip.segments if s.id == disrupted.id), None)
    return segment.cost_minor or 0


def _trip_currency(trip: Trip) -> str:
    for segment in trip.segments:
        if segment.cost_currency:
            return segment.cost_currency
    return "EUR"


def _carrier_region(carrier_code: str | None) -> str:
    """Map a carrier to its home region for EU261 scope checks.

    TODO: verify - extend this mapping from a real carrier reference dataset
    before relying on it for compensation advice on uncatalogued carriers.
    """
    if not carrier_code:
        return "XX"
    # ISO 3166-1 alpha-2 home countries of the carriers in the reference table.
    home_country = {
        "LH": "DE", "EW": "DE", "AF": "FR", "KL": "NL", "BA": "GB", "VS": "GB",
        "U2": "GB", "IB": "ES", "AZ": "IT", "LX": "CH", "OS": "AT", "SK": "SE",
        "AY": "FI", "TP": "PT", "SN": "BE", "AI": "IN", "IX": "IN", "UK": "IN",
        "6E": "IN", "SG": "IN", "EK": "AE", "QR": "QA", "TK": "TR", "SQ": "SG",
    }
    return home_country.get(carrier_code, "XX")


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------


async def generate_explanations(
    db: Session,
    *,
    plans: list[RecoveryPlan],
    disruption: Disruption,
    segments: list[SegmentSnapshot],
    llm: LLMRouter,
) -> None:
    """Write plan explanations, batched into a single request where possible.

    Prompts carry structured plan data only. Results are cached by plan id and
    version, so re-rendering the Recovery Centre costs nothing.
    """
    if not plans:
        return

    original_arrival = segments[-1].scheduled_arrival_utc
    structured = [
        {
            "plan_id": plan.id,
            "label": plan.label,
            "title": plan.title,
            "arrival_delta_minutes": minutes_between(plan.original_arrival_utc, plan.arrival_utc),
            "additional_cost_minor": plan.additional_cost_minor,
            "currency": plan.currency,
            "connection_safety": plan.connection_safety,
            "changes_count": len(plan.segments) + len(plan.hotel_changes) + len(plan.ground_transport),
            "hotel_nights_added": 1 if any(
                c.get("action") == "book_extra_night" for c in plan.hotel_changes
            ) else 0,
            "hotel_nights_lost": 1 if any(
                c.get("action") == "shift_one_night" for c in plan.hotel_changes
            ) else 0,
            "ground_transport_ok": bool(plan.ground_transport),
            "segments": [
                {
                    "origin_code": s.get("origin_code"),
                    "destination_code": s.get("destination_code"),
                    "service_number": s.get("service_number"),
                    "departure_local": s.get("departure_local"),
                    "mode": s.get("mode"),
                }
                for s in (plan.segments or [])
            ],
            "hotel_changes": [
                {"action": c.get("action"), "detail": c.get("detail")}
                for c in (plan.hotel_changes or [])
            ],
            "ground_transport": [
                {"pickup_local": g.get("pickup_local")} for g in (plan.ground_transport or [])
            ],
        }
        for plan in plans
    ]

    user_prompt = (
        "Write a short explanation for each recovery plan below. "
        "Return a JSON object with one key per plan label, each holding "
        '{"headline": str, "body": str, "tradeoffs": [str]}. '
        "Two sentences for the body at most. No reasoning, no advice about money.\n\n"
        + json.dumps(structured, indent=None, default=str)
    )

    for plan in plans:
        template = {
            "headline": plan_headline(
                plan.label,
                plan.title,
                minutes_between(plan.original_arrival_utc, plan.arrival_utc),
            ),
            "body": plan_body(_plan_context(plan, segments)),
            "tradeoffs": plan_tradeoffs(_plan_context(plan, segments)),
        }
        plan.explanation = template["body"]
        plan.explanation_source = "template"
        plan.explanation_version = plan.explanation_version or 1

    result = await llm.generate(
        namespace="plan_explanations",
        cache_parts=tuple(p.id for p in plans),
        user_prompt=user_prompt,
        schema=PlanExplanation,
        template={"plans": {}},
        max_tokens=900,
    )

    if result.source != "template" and isinstance(result.value.get("plans"), dict):
        for plan in plans:
            entry = result.value["plans"].get(plan.label)
            if not entry:
                continue
            plan.explanation = entry.get("body") or plan.explanation
            plan.explanation_source = result.source
    db.flush()


def _plan_context(plan: RecoveryPlan, segments: list[SegmentSnapshot]) -> dict:
    return {
        "title": plan.title,
        "segments": plan.segments,
        "additional_cost_minor": plan.additional_cost_minor,
        "currency": plan.currency,
        "changes_count": len(plan.segments) + len(plan.hotel_changes) + len(plan.ground_transport),
        "hotel_changes": plan.hotel_changes,
        "ground_transport": plan.ground_transport,
        "hotel_nights_added": 1 if any(
            c.get("action") == "book_extra_night" for c in plan.hotel_changes
        ) else 0,
        "hotel_nights_lost": 1 if any(
            c.get("action") == "shift_one_night" for c in plan.hotel_changes
        ) else 0,
        "ground_transport_ok": bool(plan.ground_transport),
        "connection_safety": plan.connection_safety,
        "arrival_delta_minutes": minutes_between(plan.original_arrival_utc, plan.arrival_utc),
    }


# ---------------------------------------------------------------------------
# Approval and execution
# ---------------------------------------------------------------------------


def approve_plan(db: Session, *, plan: RecoveryPlan, actor: User) -> RecoveryPlan:
    """Record the traveller's decision. Idempotent."""
    if plan.status == PlanStatus.APPROVED.value:
        return plan

    plan.status = PlanStatus.APPROVED.value
    plan.approved_by_id = actor.id
    plan.approved_at_utc = utcnow()

    # Every other plan in the cycle is superseded.
    siblings = db.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.disruption_id == plan.disruption_id, RecoveryPlan.id != plan.id
        )
    ).all()
    for sibling in siblings:
        if sibling.status == PlanStatus.PROPOSED.value:
            sibling.status = PlanStatus.SUPERSEDED.value

    disruption = db.get(Disruption, plan.disruption_id)
    if disruption is not None:
        disruption.status = "recovering"

    db.add(
        TripEvent(
            trip_id=plan.trip_id,
            kind="plan_approved",
            title=f"Plan {plan.label} approved",
            detail=plan.title,
            payload={"plan_id": plan.id, "label": plan.label},
            provenance="SIMULATED",
        )
    )
    db.add(
        AuditLog(
            trip_id=plan.trip_id,
            actor_id=actor.id,
            actor_email=actor.email,
            action=AuditAction.PLAN_APPROVED.value,
            summary=f"{actor.full_name} approved plan {plan.label}",
            detail={"plan_id": plan.id, "label": plan.label, "score": round(plan.score, 2)},
        )
    )
    db.flush()
    return plan


def build_plan_actions(db: Session, *, plan: RecoveryPlan) -> list[PlanAction]:
    """Turn a plan into executable steps. Each step is idempotent by key."""
    existing = {a.idempotency_key for a in plan.actions}
    created: list[PlanAction] = []

    for i, segment in enumerate(plan.segments or []):
        key = f"{plan.id}:segment:{segment.get('key')}"
        if key in existing:
            continue
        action = PlanAction(
            plan_id=plan.id,
            sequence=i,
            action_type="rebook_segment",
            target_kind="segment",
            target_id=segment.get("replaces_segment_id"),
            description=(
                f"Request rebooking on {segment.get('service_number')} "
                f"{segment.get('origin_code')} to {segment.get('destination_code')} "
                f"departing {segment.get('departure_local')}"
            ),
            status="change_requested",
            idempotency_key=key,
            cost_minor=segment.get("cost_minor"),
            currency=segment.get("currency"),
        )
        db.add(action)
        created.append(action)

    for change in plan.hotel_changes or []:
        key = f"{plan.id}:hotel:{change.get('action')}:{change.get('hotel_id') or change.get('name')}"
        if key in existing:
            continue
        action = PlanAction(
            plan_id=plan.id,
            sequence=len(created) + 10,
            action_type=f"hotel_{change.get('action')}",
            target_kind="hotel",
            target_id=change.get("hotel_id"),
            description=change.get("detail") or f"Hotel action: {change.get('action')}",
            status="change_requested",
            idempotency_key=key,
            cost_minor=change.get("cost_minor"),
            currency=change.get("currency"),
        )
        db.add(action)
        created.append(action)

    for ride in plan.ground_transport or []:
        key = f"{plan.id}:ground:{ride.get('key')}"
        if key in existing:
            continue
        action = PlanAction(
            plan_id=plan.id,
            sequence=len(created) + 20,
            action_type="rebook_transfer",
            target_kind="ground",
            target_id=ride.get("replaces"),
            description=(
                f"Request transfer rebooking: {ride.get('from_label')} to {ride.get('to_label')}, "
                f"pickup {ride.get('pickup_local') or ride.get('pickup_utc')}"
            ),
            status="change_requested",
            idempotency_key=key,
            cost_minor=ride.get("cost_minor"),
            currency=ride.get("currency"),
        )
        db.add(action)
        created.append(action)

    db.flush()
    return created


def execute_plan(db: Session, *, plan: RecoveryPlan, actor: User) -> RecoveryPlan:
    """Apply an approved plan.

    Idempotent: re-running does not duplicate actions. Execution states are
    honest. Without a real booking integration every action lands on
    "Recorded offline" or "Pending provider confirmation"; the product never
    claims a real airline ticket was rebooked.
    """
    if plan.status == PlanStatus.EXECUTED.value:
        return plan

    plan.status = PlanStatus.EXECUTING.value
    actions = build_plan_actions(db, plan=plan)

    trip = db.get(Trip, plan.trip_id)
    disruption = db.get(Disruption, plan.disruption_id)

    for action in actions:
        action.status = BookingStatus.RECORDED_OFFLINE.value
        action.executed_at_utc = utcnow()
        action.result = {
            "provider": "No booking provider configured",
            "honest_state": BookingStatus.RECORDED_OFFLINE.value,
            "note": "No live booking provider is configured. This records the intended change only.",
        }

    # Apply the plan to the itinerary.
    if trip is not None:
        _apply_plan_to_itinerary(db, trip=trip, plan=plan)

    if disruption is not None:
        disruption.status = "resolved"
        disruption.resolved_at_utc = utcnow()

    plan.status = PlanStatus.EXECUTED.value
    if trip is not None:
        trip.status = TripStatus.RECOVERING.value

    db.add(
        TripEvent(
            trip_id=plan.trip_id,
            kind="plan_executed",
            title=f"Plan {plan.label} applied",
            detail="; ".join(a.description for a in actions),
            payload={"plan_id": plan.id, "actions": len(actions)},
            provenance="SIMULATED",
        )
    )
    db.add(
        AuditLog(
            trip_id=plan.trip_id,
            actor_id=actor.id,
            actor_email=actor.email,
            action=AuditAction.EXECUTION_COMPLETED.value,
            summary=f"{actor.full_name} executed plan {plan.label} ({len(actions)} actions)",
            detail={
                "plan_id": plan.id,
                "actions": [
                    {"type": a.action_type, "status": a.status, "key": a.idempotency_key}
                    for a in actions
                ],
            },
        )
    )

    state = db.get(MonitoringState, plan.trip_id)
    if state is None:
        state = MonitoringState(trip_id=plan.trip_id)
        db.add(state)
    state.active_plan_id = plan.id
    state.cycle = plan.cycle
    state.watching = True
    state.last_checked_utc = utcnow()
    db.flush()
    return plan


def _apply_plan_to_itinerary(db: Session, *, trip: Trip, plan: RecoveryPlan) -> None:
    """Rewrite the trip to match the plan.

    Replaced legs are marked as superseded rather than deleted, so the
    original booking stays visible in history.
    """
    for segment_payload in plan.segments or []:
        replaced_id = segment_payload.get("replaces_segment_id")
        if replaced_id:
            original = db.get(Segment, replaced_id)
            if original is not None:
                original.status = SegmentStatus.MISSED.value

        from ..domain.enums import SegmentType

        new_segment = Segment(
            trip_id=trip.id,
            sequence=_next_sequence(db, trip.id),
            segment_type=segment_payload.get("mode", "flight"),
            carrier_code=segment_payload.get("carrier_code"),
            carrier_name=segment_payload.get("carrier_name"),
            service_number=segment_payload.get("service_number"),
            origin_code=segment_payload["origin_code"],
            origin_name=segment_payload.get("origin_name"),
            origin_tz=segment_payload["origin_tz"],
            destination_code=segment_payload["destination_code"],
            destination_name=segment_payload.get("destination_name"),
            destination_tz=segment_payload["destination_tz"],
            scheduled_departure_utc=_parse_dt(segment_payload["departure_utc"]),
            scheduled_arrival_utc=_parse_dt(segment_payload["arrival_utc"]),
            status=SegmentStatus.RECOVERED.value,
            booking_reference=f"RTY-{plan.label}-{plan.cycle}",
            terminal=segment_payload.get("terminal"),
            gate=segment_payload.get("gate"),
            platform=segment_payload.get("platform"),
            cabin=segment_payload.get("cabin"),
            fare_class=segment_payload.get("fare_class"),
            cost_minor=segment_payload.get("cost_minor"),
            cost_currency=segment_payload.get("currency"),
            refundable=segment_payload.get("refundable"),
            provenance=segment_payload.get("provenance", "UNAVAILABLE"),
            source="Recovery plan",
            is_recovery=True,
            replaces_segment_id=replaced_id,
        )
        db.add(new_segment)

    for change in plan.hotel_changes or []:
        if not change.get("hotel_id"):
            continue
        stay = db.get(HotelStay, change["hotel_id"])
        if stay is None:
            continue
        if change.get("action") == "late_arrival_notice":
            stay.late_arrival_notice = True
            stay.status = BookingStatus.RECORDED_OFFLINE.value
        elif change.get("action") == "shift_one_night":
            stay.check_in_utc = stay.check_in_utc + timedelta(days=1)
            stay.status = BookingStatus.CHANGE_REQUESTED.value

    for ride_payload in plan.ground_transport or []:
        replaced_reference = ride_payload.get("replaces")
        if replaced_reference:
            original = db.scalars(
                select(GroundTransport).where(
                    GroundTransport.trip_id == trip.id,
                    GroundTransport.booking_reference == replaced_reference,
                )
            ).first()
            if original is not None:
                original.status = BookingStatus.CANCELLED.value

        db.add(
            GroundTransport(
                trip_id=trip.id,
                mode="transfer",
                provider_name=ride_payload.get("provider_name"),
                from_label=ride_payload.get("from_label", ""),
                to_label=ride_payload.get("to_label", ""),
                city_code=ride_payload.get("city_code", "BER"),
                timezone=ride_payload.get("timezone", "Europe/Berlin"),
                pickup_utc=_parse_dt(ride_payload["pickup_utc"]),
                dropoff_utc=_parse_dt(ride_payload["dropoff_utc"]) if ride_payload.get("dropoff_utc") else None,
                booking_reference=f"RTY-{plan.label}-T",
                status=BookingStatus.RECORDED_OFFLINE.value,
                cost_minor=ride_payload.get("cost_minor"),
                cost_currency=ride_payload.get("currency"),
                provenance=ride_payload.get("provenance", "UNAVAILABLE"),
                source="Recovery plan",
            )
        )
    db.flush()


def _next_sequence(db: Session, trip_id: str) -> int:
    rows = db.scalars(select(Segment.sequence).where(Segment.trip_id == trip_id)).all()
    return (max(rows) if rows else 0) + 1


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


def monitor_trip(db: Session, *, trip: Trip) -> dict:
    """Re-check the active plan against the current itinerary.

    Returns a result describing whether the plan still holds. If it does not,
    the caller re-enters the pipeline with a new cycle.
    """
    state = db.get(MonitoringState, trip.id)
    segments = snapshot_segments(trip)
    active_segments = [s for s in segments if s.status not in {
        SegmentStatus.MISSED.value,
        SegmentStatus.CANCELLED.value,
    }]

    broken: list[dict] = []
    for i, segment in enumerate(active_segments[:-1]):
        nxt = active_segments[i + 1]
        if nxt.origin_code != segment.destination_code:
            continue
        from ..domain.connections import assess_connection

        assessment = assess_connection(
            airport_code=segment.destination_code,
            arriving_at_utc=segment.effective_arrival_utc,
            departing_at_utc=nxt.effective_departure_utc,
        )
        if not assessment.feasible:
            broken.append(
                {
                    "airport_code": segment.destination_code,
                    "segment_id": nxt.id,
                    "service_number": nxt.service_number,
                    "shortfall_minutes": assessment.shortfall_minutes,
                    "required_minutes": assessment.required_minutes,
                }
            )

    result = {
        "checked_at_utc": utcnow().isoformat(),
        "active_plan_id": state.active_plan_id if state else None,
        "cycle": state.cycle if state else 0,
        "segments_checked": len(active_segments),
        "healthy": not broken,
        "broken_connections": broken,
    }

    if state is not None:
        state.last_checked_utc = utcnow()
        state.last_result = result
    db.flush()
    return result


def notification_for_disruption(
    db: Session, *, trip: Trip, disruption: Disruption, llm_source: str | None = None
) -> Notification:
    """Create the traveller-facing notification for a disruption."""
    segment = db.get(Segment, disruption.segment_id) if disruption.segment_id else None
    wording = disruption_notification(
        {
            "kind": disruption.kind,
            "service_number": segment.service_number if segment else None,
            "origin_code": segment.origin_code if segment else None,
            "destination_code": segment.destination_code if segment else None,
            "delay_minutes": disruption.delay_minutes or 0,
            "new_arrival_local": (
                format_local(segment.effective_arrival_utc, segment.destination_code, with_date=True)
                if segment
                else None
            ),
        }
    )
    notification = Notification(
        user_id=trip.traveller_id,
        trip_id=trip.id,
        kind=NotificationKind.DISRUPTION.value,
        title=wording["title"],
        body=wording["body"],
        severity=disruption.severity,
        provenance=disruption.provenance,
        wording_source=llm_source or "template",
    )
    db.add(notification)
    db.flush()
    return notification


__all__ = [
    "Alternative",
    "ConstraintSet",
    "DisruptionEvent",
    "approve_plan",
    "assess_impact",
    "build_constraints",
    "build_plan_actions",
    "choose_recommended",
    "describe_arrival_delta",
    "detect_disruption",
    "estimate_compensation_for_plan",
    "execute_plan",
    "generate_explanations",
    "generate_plans",
    "monitor_trip",
    "notification_for_disruption",
    "search_alternatives",
    "snapshot_ground",
    "snapshot_hotels",
    "snapshot_segments",
]
