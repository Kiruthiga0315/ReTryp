"""Recovery Center: plans, comparison, approval, execution and the simulator.

This is the most important router in the product. It owns:

* reading the plans generated for a disruption
* the side-by-side comparison table
* explicit confirmation and execution
* the Scenario Simulator (admin only) that injects disruptions
* the Server-Sent Events stream for live updates
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..agents import pipeline
from ..config import get_settings
from ..settings_store import current_data_status
from ..db import get_db
from ..domain.enums import (
    AuditAction,
    BookingStatus,
    DisruptionKind,
    NotificationKind,
    PlanStatus,
    Role,
    TripStatus,
)
from ..domain.money import Money
from ..llm.router import build_router
from ..llm.templates import help_answer
from pydantic import BaseModel
from ..models import (
    Disruption,
    MonitoringState,
    Notification,
    RecoveryPlan,
    Trip,
    TripEvent,
    User,
)
from ..providers.data import provider_health
from ..schemas import (
    ApprovePlanRequest,
    HelpRequest,
    HelpResponse,
    SimulateDisruptionRequest,
)
from ..security import current_user, log_audit, require_role
from ..serializers import disruption_payload, plan_payload, trip_summary_payload
from .deps import actor_can_access_trip, bus, load_trip

router = APIRouter(prefix="/api", tags=["recovery"])


class _HelpSchema(BaseModel):
    """Validated shape for a rephrased help answer."""

    answer: str


def _trip_or_404(db: Session, actor: User, trip_id: str) -> Trip:
    trip = load_trip(db, trip_id)
    if trip is None or not actor_can_access_trip(db, actor, trip):
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def _plan_or_404(db: Session, actor: User, plan_id: str) -> RecoveryPlan:
    plan = db.scalars(
        select(RecoveryPlan)
        .options(selectinload(RecoveryPlan.actions), selectinload(RecoveryPlan.disruption))
        .where(RecoveryPlan.id == plan_id)
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    trip = load_trip(db, plan.trip_id)
    if trip is None or not actor_can_access_trip(db, actor, trip):
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


# ---------------------------------------------------------------------------
# Reading plans
# ---------------------------------------------------------------------------


@router.get("/trips/{trip_id}/recovery")
def recovery_center(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Everything the Recovery Center screen needs in one call."""
    trip = _trip_or_404(db, actor, trip_id)
    disruptions = sorted(trip.disruptions, key=lambda d: d.detected_at_utc, reverse=True)
    active = [d for d in disruptions if d.status in {"detected", "validated", "assessed", "recovering"}]

    target = active[0] if active else (disruptions[0] if disruptions else None)
    if target is None:
        return {
            "trip": trip_summary_payload(trip),
            "disruption": None,
            "impact": None,
            "plans": [],
            "comparison": [],
            "recommended_plan_id": None,
            "active_plan": None,
            "empty_reason": "No disruption is open for this trip.",
        }

    plans = sorted(target.plans, key=lambda p: (not p.recommended, -p.score))
    payloads = [plan_payload(p) for p in plans]

    active_plan = db.scalars(
        select(RecoveryPlan)
        .options(selectinload(RecoveryPlan.actions))
        .where(
            RecoveryPlan.trip_id == trip_id,
            RecoveryPlan.status.in_([PlanStatus.APPROVED.value, PlanStatus.EXECUTED.value]),
        )
        .order_by(RecoveryPlan.approved_at_utc.desc())
    ).first()

    return {
        "trip": trip_summary_payload(trip),
        "disruption": disruption_payload(target),
        "impact": target.payload.get("impact"),
        "plans": payloads,
        "comparison": _comparison_table(payloads),
        "recommended_plan_id": next((p["plan_id"] for p in payloads if p["recommended"]), None),
        "active_plan": plan_payload(active_plan) if active_plan else None,
        "empty_reason": None if payloads else "No feasible plan could be built from the available options.",
    }


def _comparison_table(plans: list[dict]) -> list[dict]:
    """Rows for the sortable side-by-side table."""
    rows = []
    for plan in plans:
        first = plan["segments"][0] if plan["segments"] else {}
        rows.append(
            {
                "plan_id": plan["plan_id"],
                "label": plan["label"],
                "title": plan["title"],
                "recommended": plan["recommended"],
                "score": plan["score"],
                "arrival_local": plan["arrival_local"],
                "arrival_delta_minutes": plan["arrival_delta_minutes"],
                "arrival_delta_display": plan["arrival_delta_display"],
                "total_duration_minutes": plan["total_duration_minutes"],
                "total_duration_display": plan["total_duration_display"],
                "additional_cost_minor": plan["additional_cost_minor"],
                "additional_cost_display": plan["additional_cost_display"],
                "risk_level": plan["risk_level"],
                "connection_safety": plan["connection_safety"],
                "changes_count": plan["changes_count"],
                "mode": first.get("mode", "flight"),
                "carrier": first.get("carrier_name"),
                "service_number": first.get("service_number"),
                "hotel_change_count": len(plan["hotel_changes"]),
                "ground_change_count": len(plan["ground_transport"]),
                "hotel_summary": _hotel_summary(plan),
                "ground_summary": _ground_summary(plan),
                "compensation_outcome": plan["compensation"]["outcome"],
                "compensation_display": plan["compensation"]["amount_display"],
                "compensation_amount_minor": plan["compensation"]["amount_minor"],
                "score_breakdown": plan["score_breakdown"],
            }
        )
    return rows


_HOTEL_ACTION_COPY = {
    "keep": "Hotel retained",
    "late_arrival_notice": "Late-arrival notice",
    "shift_one_night": "Shifted one night",
    "book_extra_night": "Extra night booked",
    "cancel": "Cancelled",
}


def _hotel_summary(plan: dict) -> str:
    changes = plan["hotel_changes"]
    if not changes:
        return "Unchanged"
    return ", ".join(
        _HOTEL_ACTION_COPY.get(change["action"], change["action"]) for change in changes
    )


def _ground_summary(plan: dict) -> str:
    changes = plan["ground_transport"]
    if not changes:
        return "Unchanged"
    return f"{len(changes)} rebooked" if len(changes) > 1 else "Rebooked"


@router.get("/plans/{plan_id}")
def plan_detail(
    plan_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    plan = _plan_or_404(db, actor, plan_id)
    trip = load_trip(db, plan.trip_id)
    return {
        "plan": plan_payload(plan),
        "trip": trip_summary_payload(trip) if trip else None,
        "original_itinerary": _original_itinerary(trip) if trip else [],
        "recovered_itinerary": _recovered_itinerary(plan),
    }


def _original_itinerary(trip: Trip) -> list[dict]:
    from ..serializers import segment_payload

    return [
        segment_payload(s)
        for s in sorted(trip.segments, key=lambda x: x.sequence)
        if not s.is_recovery
    ]


def _recovered_itinerary(plan: RecoveryPlan) -> list[dict]:
    return [
        {
            "mode": s.get("mode"),
            "service_number": s.get("service_number"),
            "carrier_name": s.get("carrier_name"),
            "origin_code": s.get("origin_code"),
            "origin_name": s.get("origin_name"),
            "destination_code": s.get("destination_code"),
            "destination_name": s.get("destination_name"),
            "departure_local": s.get("departure_local"),
            "arrival_local": s.get("arrival_local"),
            "duration_minutes": s.get("duration_minutes"),
            "connection_safety": s.get("connection_safety"),
            "buffer_minutes": s.get("buffer_minutes"),
            "required_minutes": s.get("required_minutes"),
            "cost_minor": s.get("cost_minor"),
            "currency": s.get("currency"),
            "refundable": s.get("refundable"),
            "provenance": s.get("provenance"),
            "note": s.get("note"),
        }
        for s in (plan.segments or [])
    ]


# ---------------------------------------------------------------------------
# Approval and execution
# ---------------------------------------------------------------------------


@router.post("/plans/{plan_id}/approve")
def approve_plan(
    plan_id: str,
    payload: ApprovePlanRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Approve a plan. Requires explicit confirmation from the UI dialog."""
    if payload.plan_id != plan_id:
        raise HTTPException(status_code=400, detail="Plan identifier mismatch")
    if not payload.confirmation:
        raise HTTPException(
            status_code=400,
            detail="A plan can only be approved after confirming in the dialog",
        )

    plan = _plan_or_404(db, actor, plan_id)
    if plan.status in {PlanStatus.REJECTED.value, PlanStatus.SUPERSEDED.value}:
        raise HTTPException(status_code=409, detail="This plan is no longer available")

    plan = pipeline.approve_plan(db, plan=plan, actor=actor)
    db.commit()
    db.refresh(plan)

    bus.publish(
        plan.trip_id,
        "plan_approved",
        {"plan_id": plan.id, "label": plan.label, "status": plan.status},
    )
    return {"plan": plan_payload(plan)}


@router.post("/plans/{plan_id}/execute")
def execute_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Apply an approved plan. Idempotent."""
    plan = _plan_or_404(db, actor, plan_id)
    if plan.status not in {PlanStatus.APPROVED.value, PlanStatus.EXECUTED.value}:
        raise HTTPException(
            status_code=409,
            detail="The plan must be approved before it can be applied",
        )

    plan = pipeline.execute_plan(db, plan=plan, actor=actor)
    _notify_execution(db, plan=plan)
    db.commit()
    db.refresh(plan)

    bus.publish(
        plan.trip_id,
        "plan_executed",
        {"plan_id": plan.id, "label": plan.label, "status": plan.status},
    )
    return {"plan": plan_payload(plan)}


@router.post("/plans/{plan_id}/reject")
def reject_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    plan = _plan_or_404(db, actor, plan_id)
    if plan.status != PlanStatus.PROPOSED.value:
        raise HTTPException(status_code=409, detail="Only a proposed plan can be rejected")
    plan.status = PlanStatus.REJECTED.value
    db.add(
        TripEvent(
            trip_id=plan.trip_id,
            kind="plan_rejected",
            title=f"Plan {plan.label} rejected",
            detail=plan.title,
            payload={"plan_id": plan.id},
            provenance="SIMULATED",
        )
    )
    log_audit(
        db,
        action=AuditAction.PLAN_REJECTED.value,
        summary=f"{actor.full_name} rejected plan {plan.label}",
        actor=actor,
        trip_id=plan.trip_id,
        detail={"plan_id": plan.id},
    )
    db.commit()
    bus.publish(plan.trip_id, "plan_rejected", {"plan_id": plan.id, "label": plan.label})
    return {"plan": plan_payload(plan)}


def _notify_execution(db: Session, *, plan: RecoveryPlan) -> None:
    trip = db.get(Trip, plan.trip_id)
    if trip is None:
        return
    actions = [a for a in plan.actions]
    body_parts = []
    for action in actions:
        if action.status == BookingStatus.RECORDED_OFFLINE.value:
            body_parts.append(
                f"{action.description} — recorded, pending a booking provider."
            )
        elif action.status == "pending_provider_confirmation":
            body_parts.append(f"{action.description} — pending provider confirmation.")
        else:
            body_parts.append(f"{action.description} — change requested.")
    db.add(
        Notification(
            user_id=trip.traveller_id,
            trip_id=trip.id,
            kind=NotificationKind.EXECUTION.value,
            title=f"Plan {plan.label} applied",
            body=" ".join(body_parts) or "The recovery plan has been applied.",
            severity="low",
            provenance="SIMULATED",
            wording_source="template",
        )
    )
    db.flush()


# ---------------------------------------------------------------------------
# Scenario Simulator
# ---------------------------------------------------------------------------


@router.post("/simulator/disruptions", dependencies=[Depends(require_role(Role.ADMIN, Role.TRAVEL_MANAGER))])
async def simulate_disruption(
    payload: SimulateDisruptionRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Inject a disruption into the same pipeline live feeds use.

    Admin-only, tagged SIMULATED, and never presented as live data.
    """
    trip = _trip_or_404(db, actor, payload.trip_id)
    settings = get_settings()

    segment_id = payload.segment_id
    if segment_id is None and payload.hotel_id is None and payload.ground_id is None:
        # Left unspecified: target the earliest segment that can still be
        # disrupted, so an operator can inject a scenario in one click.
        candidate = next(
            (
                segment
                for segment in sorted(trip.segments, key=lambda s: s.sequence)
                if segment.status not in {"cancelled", "completed"}
            ),
            None,
        )
        segment_id = candidate.id if candidate else None

    disruption = pipeline.detect_disruption(
        db,
        trip=trip,
        kind=payload.kind,
        segment_id=segment_id,
        hotel_id=payload.hotel_id,
        ground_id=payload.ground_id,
        delay_minutes=payload.delay_minutes,
        detail=payload.detail,
        payload={"baggage_recheck": payload.baggage_recheck, "injected_by": actor.email},
        provenance="SIMULATED",
        source="Scenario Simulator",
    )

    impact = pipeline.assess_impact(db, trip=trip, disruption=disruption)
    disruption.payload = {**(disruption.payload or {}), "impact": impact}

    pipeline.notification_for_disruption(db, trip=trip, disruption=disruption)

    plans: list[RecoveryPlan] = []
    if payload.auto_generate_plans:
        constraints = pipeline.build_constraints(db, trip=trip)
        plans = await pipeline.generate_plans(
            db,
            trip=trip,
            disruption=disruption,
            constraints=constraints,
            settings=settings,
            llm=build_router(settings),
        )

    _ensure_monitoring(db, trip_id=trip.id, cycle=disruption.cycle)
    db.commit()

    bus.publish(
        trip.id,
        "disruption_detected",
        {
            "disruption": disruption_payload(disruption),
            "impact": impact,
            "plan_count": len(plans),
            "cycle": disruption.cycle,
        },
    )
    db.refresh(disruption)
    return {
        "disruption": disruption_payload(disruption),
        "impact": impact,
        "plans": [plan_payload(p) for p in plans],
    }


@router.post("/trips/{trip_id}/reset", dependencies=[Depends(require_role(Role.ADMIN, Role.TRAVEL_MANAGER))])
def reset_recovery(
    trip_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    """Remove a trip's recovery history and restore its pre-disruption itinerary.

    Admin/manager only. After a reset the trip has no disruptions, no plans
    and no recovered legs, so the next injected disruption opens cycle 1
    against the original booking.
    """
    trip = _trip_or_404(db, actor, trip_id)
    removed = pipeline.reset_trip_recovery(db, trip=trip, actor=actor)
    db.commit()
    db.refresh(trip)

    bus.publish(trip.id, "recovery_reset", {"trip_id": trip.id, "removed": removed})
    return {
        "trip": trip_summary_payload(trip),
        "removed": removed,
        "disruptions": [disruption_payload(d) for d in trip.disruptions],
    }


def _ensure_monitoring(db: Session, *, trip_id: str, cycle: int) -> MonitoringState:
    state = db.get(MonitoringState, trip_id)
    if state is None:
        state = MonitoringState(trip_id=trip_id, cycle=cycle, watching=True)
        db.add(state)
    else:
        state.cycle = cycle
        state.watching = True
    db.flush()
    return state


@router.get("/simulator/scenarios")
def simulator_scenarios(actor: User = Depends(current_user)) -> dict:
    """The disruption kinds the simulator can inject."""
    del actor
    return {
        "kinds": [
            {"value": k.value, "label": k.value.replace("_", " ").capitalize()}
            for k in DisruptionKind
        ],
        "note": (
            "Everything injected here is tagged SIMULATED and enters the same detection "
            "pipeline that live feeds use."
        ),
    }


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


@router.get("/trips/{trip_id}/monitoring")
def monitoring_status(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    trip = _trip_or_404(db, actor, trip_id)
    state = db.get(MonitoringState, trip_id)
    result = pipeline.monitor_trip(db, trip=trip)
    db.commit()
    return {
        "trip_id": trip_id,
        "watching": state.watching if state else True,
        "cycle": state.cycle if state else 0,
        "active_plan_id": state.active_plan_id if state else None,
        "last_result": result,
    }


@router.post("/trips/{trip_id}/monitoring/check")
async def monitoring_check(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> dict:
    """Run one monitoring pass. Re-enters the pipeline if the plan has failed."""
    trip = _trip_or_404(db, actor, trip_id)
    settings = get_settings()
    result = pipeline.monitor_trip(db, trip=trip)

    escalated = False
    if not result["healthy"]:
        escalated = True
        broken = result["broken_connections"][0]
        disruption = pipeline.detect_disruption(
            db,
            trip=trip,
            kind=DisruptionKind.MISSED_CONNECTION,
            segment_id=broken["segment_id"],
            detail=(
                f"Monitoring found the connection at {broken['airport_code']} is no longer "
                f"feasible: {broken['shortfall_minutes']} min short of the "
                f"{broken['required_minutes']} min minimum."
            ),
            payload={"escalated_from_plan": result["active_plan_id"]},
            provenance="SIMULATED",
            source="Journey monitoring",
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
        db.add(
            TripEvent(
                trip_id=trip.id,
                kind="escalation",
                title="A new recovery cycle started",
                detail=f"Monitoring invalidated the active plan. {len(plans)} new plans prepared.",
                payload={"cycle": disruption.cycle, "plans": [p.label for p in plans]},
                provenance="SIMULATED",
            )
        )
        log_audit(
            db,
            action=AuditAction.ESCALATION_TRIGGERED.value,
            summary=f"Monitoring escalated to a new recovery cycle for {trip.reference}",
            actor=actor,
            trip_id=trip.id,
            detail={"broken": result["broken_connections"], "cycle": disruption.cycle},
        )
        result["escalation"] = {
            "disruption_id": disruption.id,
            "cycle": disruption.cycle,
            "plans": [p.label for p in plans],
        }

    _ensure_monitoring(db, trip_id=trip.id, cycle=result.get("escalation", {}).get("cycle", result["cycle"]))
    db.commit()

    bus.publish(
        trip_id,
        "monitoring_result",
        {"result": result, "escalated": escalated},
    )
    return result


# ---------------------------------------------------------------------------
# Events and help
# ---------------------------------------------------------------------------


@router.get("/trips/{trip_id}/events")
async def trip_events(
    trip_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> StreamingResponse:
    """Server-Sent Events: disruption, plan and monitoring updates."""
    _trip_or_404(db, actor, trip_id)
    return StreamingResponse(
        bus.stream(trip_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/help", response_model=HelpResponse)
async def contextual_help(
    payload: HelpRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> HelpResponse:
    """The small contextual help panel. Secondary, never the main interface."""
    settings = get_settings()
    context: dict = {}

    if payload.plan_id:
        plan = _plan_or_404(db, actor, payload.plan_id)
        context = {
            "factors": plan.decision_factors,
            "arrival_delta_display": _delta_display(plan),
            "additional_cost_display": str(
                Money(plan.additional_cost_minor, plan.currency)
            ),
            "outcome": (plan.compensation or {}).get("outcome"),
            "amount_display": (plan.compensation or {}).get("amount_display"),
        }
        for segment in plan.segments or []:
            if segment.get("buffer_minutes"):
                context["buffer_minutes"] = segment["buffer_minutes"]
                context["required_minutes"] = segment["required_minutes"]
                break
        siblings = db.scalars(
            select(RecoveryPlan).where(
                RecoveryPlan.disruption_id == plan.disruption_id, RecoveryPlan.id != plan.id
            )
        ).all()
        cheaper = sorted(
            [s for s in siblings if s.additional_cost_minor < plan.additional_cost_minor],
            key=lambda s: s.additional_cost_minor,
        )
        context["cheaper"] = [
            {
                "title": s.title,
                "additional_cost_display": str(
                    Money(plan.additional_cost_minor - s.additional_cost_minor, plan.currency)
                ),
                "arrival_delta_display": _delta_display(s),
            }
            for s in cheaper[:2]
        ]

    answer = help_answer(payload.topic, context)

    # The LLM is used only to rephrase; the facts above are the source.
    if payload.question and settings.llm_enabled:
        router_llm = build_router(settings)
        result = await router_llm.generate(
            namespace="help",
            cache_parts=(payload.topic, payload.question, tuple(sorted(context.keys()))),
            user_prompt=(
                "Rewrite this operational answer in one short paragraph. "
                "Do not add facts, do not add advice about money, do not mention "
                "assistants or artificial intelligence.\n\n"
                f"Answer: {answer}\nFacts: {context}"
            ),
            schema=_HelpSchema,
            template={"answer": answer},
            max_tokens=250,
        )
        if result.source != "template" and result.value.get("answer"):
            answer = result.value["answer"]
            return HelpResponse(topic=payload.topic, answer=answer, source=result.source, related=context)

    return HelpResponse(topic=payload.topic, answer=answer, source="template", related=context)


def _delta_display(plan: RecoveryPlan) -> str:
    from ..domain.timeutil import format_duration, minutes_between

    delta = minutes_between(plan.original_arrival_utc, plan.arrival_utc)
    if delta == 0:
        return "on schedule"
    return f"{format_duration(abs(delta))} {'later' if delta > 0 else 'earlier'}"


@router.get("/providers/health")
def providers_health(actor: User = Depends(current_user)) -> dict:
    """What the Settings screen shows about external data sources."""
    del actor
    settings = get_settings()
    return {
        "data_status": current_data_status()["mode"],
        "providers": provider_health(settings),
        "note": (
            "No API key is ever sent to the browser. Every value carries its own "
            "provenance badge, and when a provider is not configured or fails, ReTryp "
            "falls back to a stored reading and labels it CACHED rather than inventing one."
        ),
    }
