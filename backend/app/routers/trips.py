"""Trip, dashboard, journey and history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..domain.enums import DisruptionStatus, Role, TripStatus
from ..models import (
    AuditLog,
    MonitoringState,
    Notification,
    Segment,
    Trip,
    TripEvent,
    User,
)
from ..providers.data import all_delay_priors, get_weather
from ..security import current_user, log_audit
from ..serializers import (
    disruption_payload,
    ground_payload,
    hotel_payload,
    plan_payload,
    segment_payload,
    trip_summary_payload,
)
from .deps import actor_can_access_trip, load_trip, load_trips_for

router = APIRouter(prefix="/api", tags=["trips"])

ACTIVE_DISRUPTION_STATUSES = {
    DisruptionStatus.DETECTED.value,
    DisruptionStatus.VALIDATED.value,
    DisruptionStatus.ASSESSED.value,
    DisruptionStatus.RECOVERING.value,
}


def _trip_or_404(db: Session, actor: User, trip_id: str) -> Trip:
    trip = load_trip(db, trip_id)
    if trip is None or not actor_can_access_trip(db, actor, trip):
        # Same response for "missing" and "not yours".
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.get("/trips")
def list_trips(
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
) -> dict:
    trips = load_trips_for(db, actor)
    if status_filter:
        trips = [t for t in trips if t.status == status_filter]
    if search:
        needle = search.lower()
        trips = [
            t
            for t in trips
            if needle in t.name.lower()
            or needle in t.reference.lower()
            or needle in t.origin_code.lower()
            or needle in t.destination_code.lower()
        ]
    return {"trips": [trip_summary_payload(t) for t in trips], "count": len(trips)}


@router.get("/trips/current")
def current_trip(
    db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """The journey the header indicator and the Dashboard point at."""
    trips = load_trips_for(db, actor)
    live = [t for t in trips if t.status in {
        TripStatus.ACTIVE.value,
        TripStatus.DISRUPTED.value,
        TripStatus.RECOVERING.value,
    }]
    if live:
        trip = live[0]
    elif trips:
        trip = trips[0]
    else:
        return {"trip": None}
    return {"trip": _dashboard_payload(db, trip)}


@router.get("/trips/{trip_id}")
def get_trip(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    return {"trip": _journey_payload(trip)}


@router.get("/trips/{trip_id}/dashboard")
async def trip_dashboard(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    return {"trip": _dashboard_payload(db, trip)}


@router.get("/trips/{trip_id}/timeline")
def trip_timeline(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    events = db.scalars(
        select(TripEvent)
        .where(TripEvent.trip_id == trip_id)
        .order_by(TripEvent.occurred_at_utc.desc())
    ).all()
    return {
        "segments": [segment_payload(s) for s in sorted(trip.segments, key=lambda x: x.sequence)],
        "hotels": [hotel_payload(h) for h in trip.hotels],
        "ground": [ground_payload(g) for g in trip.ground],
        "events": [
            {
                "id": e.id,
                "occurred_at_utc": e.occurred_at_utc.isoformat(),
                "kind": e.kind,
                "title": e.title,
                "detail": e.detail,
                "segment_id": e.segment_id,
                "provenance": e.provenance,
            }
            for e in events
        ],
    }


@router.get("/trips/{trip_id}/history")
def trip_history(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    disruptions = sorted(trip.disruptions, key=lambda d: d.detected_at_utc)
    plans = [p for d in disruptions for p in d.plans]
    executed = [p for p in plans if p.status == "executed"]
    extra_cost_minor, cost_currency = _sum_in_display_currency(
        [(p.additional_cost_minor, p.currency) for p in executed]
    )
    refunds_minor, refund_currency = _sum_in_display_currency(
        [(p.refund_estimate_minor, p.currency) for p in executed]
    )
    return {
        "trip": trip_summary_payload(trip),
        "disruptions": [disruption_payload(d) for d in disruptions],
        "plans": [plan_payload(p) for p in plans],
        "recovery_performed": len(executed),
        "final_arrival_utc": executed[-1].arrival_utc.isoformat() if executed else None,
        "extra_cost_minor": extra_cost_minor,
        "extra_cost_display": _money(extra_cost_minor, cost_currency),
        "refund_estimate_minor": refunds_minor,
        "refund_display": _money(refunds_minor, refund_currency) if refunds_minor else "Not estimated",
        "currency": cost_currency,
    }


@router.get("/trips/{trip_id}/disruptions")
def trip_disruptions(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    disruptions = sorted(trip.disruptions, key=lambda d: d.detected_at_utc, reverse=True)
    return {
        "disruptions": [disruption_payload(d) for d in disruptions],
        "active": [disruption_payload(d) for d in disruptions if d.status in ACTIVE_DISRUPTION_STATUSES],
    }


@router.get("/trips/{trip_id}/context")
async def trip_context(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Weather and delay priors for the places on this trip.

    India and Europe figures are aggregates, and the payload says so, so the
    UI can label them correctly.
    """
    trip = _trip_or_404(db, actor, trip_id)
    settings = get_settings()
    codes = sorted({s.origin_code for s in trip.segments} | {s.destination_code for s in trip.segments})
    weather = []
    for code in codes:
        reading = await get_weather(settings, code)
        weather.append(
            {
                "place_code": reading.place_code,
                "condition": reading.condition,
                "temp_c": reading.temp_c,
                "wind_kph": reading.wind_kph,
                "precip_mm": reading.precip_mm,
                "visibility_km": reading.visibility_km,
                "provenance": reading.provenance,
                "source": reading.source,
                "fetched_at": reading.fetched_at.isoformat() if reading.fetched_at else None,
                "note": reading.note,
            }
        )
    priors = [
        {
            "subject": p.subject,
            "scope": p.scope,
            "on_time_pct": p.on_time_pct,
            "avg_delay_minutes": p.avg_delay_minutes,
            "sample": p.sample,
            "source_name": p.source_name,
            "source_url": p.source_url,
            "verified_on": p.verified_on,
            "provenance": p.provenance,
            "note": p.note,
        }
        for p in all_delay_priors()
    ]
    return {
        "weather": weather,
        "delay_priors": priors,
        "disclaimer": (
            "Punctuality figures are published regional aggregates, not per-flight history. "
            "They are used as risk priors only."
        ),
    }


def _journey_payload(trip: Trip) -> dict:
    return {
        **trip_summary_payload(trip),
        "segments": [segment_payload(s) for s in sorted(trip.segments, key=lambda x: x.sequence)],
        "hotels": [hotel_payload(h) for h in trip.hotels],
        "ground": [ground_payload(g) for g in trip.ground],
        "disruptions": [
            disruption_payload(d)
            for d in sorted(trip.disruptions, key=lambda x: x.detected_at_utc, reverse=True)
        ],
    }


def _dashboard_payload(db: Session, trip: Trip) -> dict:
    segments = sorted(trip.segments, key=lambda s: s.sequence)
    disruptions = sorted(trip.disruptions, key=lambda d: d.detected_at_utc, reverse=True)
    active = [d for d in disruptions if d.status in ACTIVE_DISRUPTION_STATUSES]

    next_segment = None
    for segment in segments:
        if segment.status not in {"completed", "missed", "cancelled"}:
            next_segment = segment
            break

    active_plans = []
    for disruption in active:
        active_plans.extend(
            [plan_payload(p) for p in disruption.plans if p.status == "proposed"]
        )
    active_plans.sort(key=lambda p: (not p["recommended"], -p["score"]))

    return {
        "trip": trip_summary_payload(trip),
        "current_location": _current_location(segments),
        "next_segment": segment_payload(next_segment) if next_segment else None,
        "segments": [segment_payload(s) for s in segments],
        "hotels": [hotel_payload(h) for h in trip.hotels],
        "ground": [ground_payload(g) for g in trip.ground],
        "active_disruption": disruption_payload(active[0]) if active else None,
        "active_disruptions": [disruption_payload(d) for d in active],
        "recovery_plan_count": len(active_plans),
        "recommended_plan": next((p for p in active_plans if p["recommended"]), None),
        "has_active_recovery": bool(active_plans),
    }


def _current_location(segments: list[Segment]) -> dict:
    """Where the traveller is, derived from segment status. Never invented."""
    for segment in segments:
        if segment.status in {"delayed", "disrupted", "at_risk"}:
            return {
                "label": f"At {segment.origin_code}",
                "detail": f"Awaiting {segment.service_number or segment.segment_type}",
                "place_code": segment.origin_code,
                "kind": "airport" if segment.segment_type == "flight" else "station",
            }
        if segment.status == "missed":
            return {
                "label": f"At {segment.origin_code}",
                "detail": f"Missed {segment.service_number or segment.segment_type}",
                "place_code": segment.origin_code,
                "kind": "airport" if segment.segment_type == "flight" else "station",
            }
    return {
        "label": "Not yet departed",
        "detail": "The journey has not started",
        "place_code": segments[0].origin_code if segments else None,
        "kind": "city",
    }


def _money(minor: int, currency: str) -> str:
    from ..domain.money import Money

    return str(Money(minor, currency))


def _sum_in_display_currency(amounts: list[tuple[int, str]]) -> tuple[int, str]:
    """Total a set of amounts that may be quoted in different currencies.

    Each amount is converted into the viewer's display currency first, so a
    trip whose plans were priced in EUR and INR does not add up as if the two
    currencies were the same unit. The returned currency is the one the total
    is expressed in.
    """
    from ..display import convert_minor, current_display

    context = current_display()
    fallback = context.target_currency.upper() if context else "EUR"
    total = 0
    currency = fallback
    for minor, code in amounts:
        converted, converted_code = convert_minor(minor, code)
        total += converted or 0
        currency = converted_code or currency
    return total, currency


@router.delete("/trips/{trip_id}", status_code=200)
def delete_trip(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Remove a trip the traveller owns, with everything derived from it.

    Only the owner (or an administrator) may delete a trip, and it must not be
    part-way through a recovery: a journey being recovered is not something to
    discard from a list. The deletion is audited before the rows go.
    """
    trip = load_trip(db, trip_id)
    if trip is None or not actor_can_access_trip(db, actor, trip):
        raise HTTPException(status_code=404, detail="Trip not found")
    if actor.role != Role.ADMIN.value and trip.traveller_id != actor.id:
        raise HTTPException(
            status_code=403, detail="Only the trip owner or an administrator can delete a trip"
        )

    active = [
        d
        for d in trip.disruptions
        if d.status
        in {
            DisruptionStatus.DETECTED.value,
            DisruptionStatus.VALIDATED.value,
            DisruptionStatus.ASSESSED.value,
            DisruptionStatus.RECOVERING.value,
        }
    ]
    if active:
        raise HTTPException(
            status_code=409,
            detail="This journey has a recovery in progress. Resolve it before deleting the trip.",
        )

    reference = trip.reference
    name = trip.name

    # Segments, hotels, ground transport, disruptions, plans and plan actions
    # cascade from the trip through the ORM. The remaining tables either have no
    # relationship or a nullable trip_id, so they are cleared explicitly.
    db.query(TripEvent).filter(TripEvent.trip_id == trip.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.trip_id == trip.id).delete(
        synchronize_session=False
    )
    db.query(MonitoringState).filter(MonitoringState.trip_id == trip.id).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.trip_id == trip.id).delete(synchronize_session=False)
    db.delete(trip)
    log_audit(
        db,
        action="trip.deleted",
        summary=f"Deleted trip {reference} ({name})",
        actor=actor,
        detail={"reference": reference},
    )
    db.commit()
    return {"deleted": True, "reference": reference}
