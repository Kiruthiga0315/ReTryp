"""Bookings, notifications, audit log and the data status indicator."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..display import fx_block
from ..domain.enums import Role
from ..domain.rail import rail_services_meta
from ..domain.reference import REFERENCE_FETCHED_AT, REFERENCE_LOADED
from ..models import AuditLog, Notification, Trip, User, utcnow
from ..providers.data import provider_health
from ..providers.flights import build_flight_provider
from ..schemas import NotificationReadRequest
from ..settings_store import current_data_status
from ..security import current_user, require_role, visible_traveller_ids
from ..serializers import ground_payload, hotel_payload, segment_payload
from .deps import load_trip, load_trips_for

router = APIRouter(prefix="/api", tags=["bookings"])

# Human-readable labels for audit actions. The raw action value stays in the
# payload so filters keep working.
AUDIT_LABELS: dict[str, str] = {
    "disruption_detected": "Disruption detected",
    "impact_assessed": "Impact assessed",
    "plan_generated": "Plans generated",
    "plan_approved": "Plan approved",
    "plan_rejected": "Plan rejected",
    "execution_started": "Execution started",
    "execution_completed": "Execution completed",
    "notification_sent": "Notification sent",
    "monitoring_alert": "Monitoring alert",
    "escalation_triggered": "Escalation triggered",
    "login": "Sign-in",
    "logout": "Sign-out",
    "user_created": "User created",
    "trip_created": "Trip created",
}


@router.get("/trips/{trip_id}/bookings")
def trip_bookings(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Bookings grouped by mode, for the tabbed Bookings screen."""
    trip = load_trip(db, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    from .deps import actor_can_access_trip

    if not actor_can_access_trip(db, actor, trip):
        raise HTTPException(status_code=404, detail="Trip not found")

    flights = [segment_payload(s) for s in trip.segments if s.segment_type == "flight"]
    trains = [segment_payload(s) for s in trip.segments if s.segment_type == "train"]
    others = [
        segment_payload(s)
        for s in trip.segments
        if s.segment_type not in {"flight", "train"}
    ]
    return {
        "trip": {
            "id": trip.id,
            "reference": trip.reference,
            "name": trip.name,
            "provenance": trip.provenance,
        },
        "flights": sorted(flights, key=lambda s: s["scheduled_departure_utc"]),
        "trains": sorted(trains, key=lambda s: s["scheduled_departure_utc"]),
        "ground_transport": [ground_payload(g) for g in trip.ground],
        "other_transport": others,
        "hotels": [hotel_payload(h) for h in trip.hotels],
        "counts": {
            "flights": len(flights),
            "trains": len(trains),
            "hotels": len(trip.hotels),
            "ground_transport": len(trip.ground),
        },
    }


@router.get("/bookings")
def all_bookings(
    db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Every booking the actor can see, across their trips."""
    trips = load_trips_for(db, actor)
    rows: list[dict] = []
    for trip in trips:
        for segment in trip.segments:
            payload = segment_payload(segment)
            payload["trip_reference"] = trip.reference
            payload["trip_name"] = trip.name
            rows.append(payload)
    return {"bookings": sorted(rows, key=lambda r: r["scheduled_departure_utc"]), "count": len(rows)}


@router.get("/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    unread_only: bool = Query(default=False),
    kind: str | None = Query(default=None),
) -> dict:
    # A traveller sees their own notifications. A manager or admin also sees
    # notifications for trips they can access, matching trip/audit visibility.
    visible_ids = visible_traveller_ids(db, actor)
    query = select(Notification)
    if actor.role in (Role.ADMIN.value, Role.TRAVEL_MANAGER.value):
        trip_ids = select(Trip.id).where(Trip.traveller_id.in_(visible_ids))
        query = query.where(
            or_(Notification.user_id == actor.id, Notification.trip_id.in_(trip_ids))
        )
    else:
        query = query.where(Notification.user_id == actor.id)
    if unread_only:
        query = query.where(Notification.read_at_utc.is_(None))
    if kind:
        query = query.where(Notification.kind == kind)
    rows = db.scalars(query.order_by(Notification.created_at.desc())).all()
    return {
        "notifications": [
            {
                "id": n.id,
                "trip_id": n.trip_id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "severity": n.severity,
                "read": n.read_at_utc is not None,
                "created_at_utc": n.created_at.isoformat(),
                "provenance": n.provenance,
                "wording_source": n.wording_source,
            }
            for n in rows
        ],
        "unread_count": sum(1 for n in rows if n.read_at_utc is None),
        "count": len(rows),
    }


@router.post("/notifications/read")
def mark_read(
    payload: NotificationReadRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    query = select(Notification)
    if actor.role in (Role.ADMIN.value, Role.TRAVEL_MANAGER.value):
        trip_ids = select(Trip.id).where(
            Trip.traveller_id.in_(visible_traveller_ids(db, actor))
        )
        query = query.where(
            or_(Notification.user_id == actor.id, Notification.trip_id.in_(trip_ids))
        )
    else:
        query = query.where(Notification.user_id == actor.id)
    if not payload.all:
        if not payload.notification_ids:
            raise HTTPException(status_code=400, detail="Provide notification ids or set all=true")
        query = query.where(Notification.id.in_(payload.notification_ids))
    rows = db.scalars(query).all()
    now = utcnow()
    for row in rows:
        if row.read_at_utc is None:
            row.read_at_utc = now
    db.commit()
    return {"updated": len(rows)}


@router.get("/audit", dependencies=[Depends(require_role(Role.ADMIN, Role.TRAVEL_MANAGER))])
def audit_log(
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    trip_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Who did what, when. Visible to managers and admins."""
    query = select(AuditLog)
    if trip_id:
        query = query.where(AuditLog.trip_id == trip_id)
    if action:
        query = query.where(AuditLog.action == action)
    rows = db.scalars(query.order_by(AuditLog.occurred_at_utc.desc()).limit(limit)).all()

    visible_trip_ids = {t.id for t in load_trips_for(db, actor)}
    filtered = [
        r for r in rows
        if r.trip_id is None or r.trip_id in visible_trip_ids or actor.role == Role.ADMIN.value
    ]
    actor_ids = {r.actor_id for r in filtered if r.actor_id}
    actors = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    } if actor_ids else {}
    return {
        "entries": [
            {
                "id": r.id,
                "occurred_at_utc": r.occurred_at_utc.isoformat(),
                "created_at_utc": r.occurred_at_utc.isoformat(),
                "created_at_local": f"{r.occurred_at_utc:%d %b %Y %H:%M} UTC",
                "actor_id": r.actor_id,
                "actor_email": r.actor_email,
                "actor_name": actors[r.actor_id].full_name if r.actor_id in actors else (r.actor_email or "System"),
                "actor_role": actors[r.actor_id].role if r.actor_id in actors else "system",
                "trip_id": r.trip_id,
                "action": r.action,
                "action_label": AUDIT_LABELS.get(r.action, r.action.replace("_", " ").title()),
                "subject_kind": r.detail.get("kind") or r.detail.get("subject_kind"),
                "subject_id": r.detail.get("subject_id"),
                "summary": r.summary,
                "detail": r.detail,
                "provenance": r.detail.get("provenance", "UNAVAILABLE"),
            }
            for r in filtered
        ],
        "count": len(filtered),
    }


@router.get("/data-status")
def data_status(db: Session = Depends(get_db), actor: User = Depends(current_user)) -> dict:
    """The global data-status indicator in the header.

    Reports which real sources are answering. There is no mode to switch
    between, because ReTryp answers from real sources only.
    """
    del db, actor
    settings = get_settings()
    provider = build_flight_provider(settings)
    live = provider.name != "unconfigured"
    rail = rail_services_meta()

    # LIVE when a schedule provider is configured, REFERENCE when only the
    # downloaded reference and rail datasets are in use, UNAVAILABLE otherwise.
    if live:
        mode = "live"
    elif REFERENCE_LOADED or rail["loaded"]:
        mode = "reference"
    else:
        mode = "unavailable"

    sources = [
        {
            "name": "Airport and airline reference",
            "detail": "OurAirports and OpenFlights",
            "loaded": REFERENCE_LOADED,
            "provenance": "REFERENCE",
            "fetched_at": REFERENCE_FETCHED_AT,
        },
        {
            "name": "Rail timetables",
            "detail": "DELFI e.V. / GTFS.de (Germany)",
            "loaded": rail["loaded"],
            "provenance": "REFERENCE",
            "fetched_at": rail["fetched_at"],
            "valid_from": rail["valid_from"],
            "valid_to": rail["valid_to"],
        },
        {
            "name": "Flight schedules and status",
            "detail": (
                provider.name
                if live
                else "Not configured. Set FLIGHT_PROVIDER and its API key."
            ),
            "loaded": live,
            "provenance": "LIVE" if live else "UNAVAILABLE",
            "fetched_at": None,
        },
        {
            "name": "Fares and hotel rates",
            "detail": (
                "Fares are planning estimates. A real fare provider is not configured."
            ),
            "loaded": False,
            "provenance": "ESTIMATE",
            "fetched_at": None,
        },
    ]

    fx = fx_block()
    if fx:
        sources.append(
            {
                "name": "Currency conversion",
                "detail": f"European Central Bank rates via Frankfurter, base {fx['rate_base']}",
                "loaded": True,
                "provenance": fx["rate_provenance"],
                "fetched_at": fx["rate_as_of"],
            }
        )

    notes = {
        "live": (
            "A live flight provider is configured. Reference and timetable data come from "
            "downloaded datasets, and every value still carries its own provenance badge."
        ),
        "reference": (
            "Using downloaded reference and timetable datasets. No live provider key is set, "
            "so schedules and availability are labelled per value."
        ),
        "unavailable": (
            "No reference dataset is loaded and no live provider is configured. "
            "Configure a source to see schedules."
        ),
    }
    return {
        "mode": mode,
        "flight_provider": provider.name,
        "live_providers": [provider.name] if live else [],
        "reference_loaded": REFERENCE_LOADED,
        "reference_fetched_at": REFERENCE_FETCHED_AT,
        "rail_loaded": rail["loaded"],
        "rail_valid_from": rail["valid_from"],
        "rail_valid_to": rail["valid_to"],
        "sources": sources,
        "note": notes[mode],
    }


@router.get("/admin/data-status", dependencies=[Depends(require_role(Role.ADMIN))])
def admin_data_status() -> dict:
    """The administrator's view of which real sources are answering."""
    settings = get_settings()
    return {
        "data_status": current_data_status()["mode"],
        "providers": provider_health(settings),
        "reference_loaded": REFERENCE_LOADED,
        "reference_fetched_at": REFERENCE_FETCHED_AT,
        "explanation": (
            "ReTryp uses real sources only. Each provider is attempted when configured "
            "and reports itself unavailable when it is not; every value carries its own "
            "provenance badge."
        ),
    }
