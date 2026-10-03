"""Serialisation from ORM rows to API payloads.

Every payload that carries an external fact carries its provenance and, for
CACHED values, the time it was fetched. Local times are computed here, once,
so the frontend never has to do timezone arithmetic.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .domain.enums import (
    BookingStatus,
    ConnectionSafety,
    PlanStatus,
    SegmentStatus,
    TripStatus,
)
from .domain.money import Money
from .domain.reference import require_place
from .domain.timeutil import format_duration, format_local, minutes_between
from .display import convert_minor
from .models import (
    Disruption,
    GroundTransport,
    HotelStay,
    RecoveryPlan,
    Segment,
    Trip,
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _converted_cost(minor: int | None, currency: str | None) -> dict:
    """``cost_minor``/``cost_currency`` in the viewer's currency."""
    amount, code = convert_minor(minor, currency)
    return {"cost_minor": amount, "cost_currency": code}


def _cost_display(minor: int | None, currency: str | None) -> str:
    """A formatted amount in the viewer's currency."""
    if minor is None:
        return "Not estimated"
    amount, code = convert_minor(minor, currency)
    return _money(amount or 0, code or "EUR")


def _plan_cost(minor: int | None, currency: str | None) -> tuple[int | None, str | None]:
    """Convert an optional plan-level amount for the viewer."""
    return convert_minor(minor, currency)


def _converted_action_cost(minor: int | None, currency: str | None) -> dict:
    amount, code = convert_minor(minor, currency)
    return {"cost_minor": amount, "currency": code}


def _convert_plain(items: list[dict] | None) -> list[dict]:
    """Convert ``cost_minor``/``currency`` on plan sub-items (hotel, ground)."""
    converted: list[dict] = []
    for item in items or []:
        entry = dict(item)
        if entry.get("cost_minor") is not None:
            amount, code = convert_minor(entry.get("cost_minor"), entry.get("currency"))
            entry["cost_minor"] = amount
            if entry.get("currency") is not None:
                entry["currency"] = code
        converted.append(entry)
    return converted


def _convert_segment_list(items: list[dict] | None) -> list[dict]:
    return _convert_plain(items)


def _convert_compensation(compensation: dict | None) -> dict | None:
    if not compensation:
        return compensation
    entry = dict(compensation)
    if entry.get("amount_minor") is not None:
        amount, code = convert_minor(entry.get("amount_minor"), entry.get("currency"))
        entry["amount_minor"] = amount
        if code:
            entry["currency"] = code
            entry["amount_display"] = _money(amount or 0, code)
    return entry


def segment_payload(segment: Segment) -> dict:
    place_origin = require_place(segment.origin_code)
    place_destination = require_place(segment.destination_code)
    scheduled_departure = segment.scheduled_departure_utc
    effective_departure = segment.effective_departure_utc
    effective_arrival = segment.effective_arrival_utc

    delay_minutes = minutes_between(scheduled_departure, effective_departure)
    arrival_delay_minutes = minutes_between(segment.scheduled_arrival_utc, effective_arrival)

    return {
        "id": segment.id,
        "sequence": segment.sequence,
        "segment_type": segment.segment_type,
        "mode_label": _mode_label(segment.segment_type),
        "carrier_code": segment.carrier_code,
        "carrier_name": segment.carrier_name,
        "service_number": segment.service_number,
        "origin": {
            "code": segment.origin_code,
            "name": segment.origin_name or place_origin.name,
            "city": place_origin.city,
            "country": place_origin.country,
            "timezone": segment.origin_tz,
            "latitude": place_origin.lat,
            "longitude": place_origin.lon,
        },
        "destination": {
            "code": segment.destination_code,
            "name": segment.destination_name or place_destination.name,
            "city": place_destination.city,
            "country": place_destination.country,
            "timezone": segment.destination_tz,
            "latitude": place_destination.lat,
            "longitude": place_destination.lon,
        },
        "scheduled_departure_utc": _iso(scheduled_departure),
        "scheduled_arrival_utc": _iso(segment.scheduled_arrival_utc),
        "estimated_departure_utc": _iso(segment.estimated_departure_utc),
        "estimated_arrival_utc": _iso(segment.estimated_arrival_utc),
        "actual_departure_utc": _iso(segment.actual_departure_utc),
        "actual_arrival_utc": _iso(segment.actual_arrival_utc),
        "scheduled_departure_local": format_local(scheduled_departure, segment.origin_code, with_date=True),
        "scheduled_arrival_local": format_local(segment.scheduled_arrival_utc, segment.destination_code, with_date=True),
        "effective_departure_local": format_local(effective_departure, segment.origin_code, with_date=True),
        "effective_arrival_local": format_local(effective_arrival, segment.destination_code, with_date=True),
        "duration_minutes": minutes_between(segment.scheduled_departure_utc, segment.scheduled_arrival_utc),
        "duration_display": format_duration(
            minutes_between(segment.scheduled_departure_utc, segment.scheduled_arrival_utc)
        ),
        "delay_minutes": delay_minutes,
        "arrival_delay_minutes": arrival_delay_minutes,
        "status": segment.status,
        "status_label": _segment_status_label(segment.status),
        "booking_reference": segment.booking_reference,
        "terminal": segment.terminal,
        "gate": segment.gate,
        "platform": segment.platform,
        "cabin": segment.cabin,
        "fare_class": segment.fare_class,
        **_converted_cost(segment.cost_minor, segment.cost_currency),
        "refundable": segment.refundable,
        "distance_km": segment.distance_km,
        "is_recovery": segment.is_recovery,
        "replaces_segment_id": segment.replaces_segment_id,
        "provenance": segment.provenance,
        "source": segment.source,
        "fetched_at": _iso(segment.fetched_at),
    }


def hotel_payload(stay: HotelStay) -> dict:
    return {
        "id": stay.id,
        "name": stay.name,
        "city_code": stay.city_code,
        "city_name": stay.city_name,
        "timezone": stay.timezone,
        "address": stay.address,
        "latitude": stay.latitude,
        "longitude": stay.longitude,
        "check_in_utc": _iso(stay.check_in_utc),
        "check_out_utc": _iso(stay.check_out_utc),
        "check_in_local": format_local(stay.check_in_utc, stay.city_code, with_date=True),
        "check_out_local": format_local(stay.check_out_utc, stay.city_code, with_date=True),
        "nights": max(1, minutes_between(stay.check_in_utc, stay.check_out_utc) // 1440),
        "rooms": stay.rooms,
        "guests": stay.guests,
        "booking_reference": stay.booking_reference,
        "status": stay.status,
        "status_label": _booking_status_label(stay.status),
        "late_arrival_notice": stay.late_arrival_notice,
        **_converted_cost(stay.cost_minor, stay.cost_currency),
        "refundable": stay.refundable,
        "provenance": stay.provenance,
        "source": stay.source,
        "fetched_at": _iso(stay.fetched_at),
    }


def ground_payload(ride: GroundTransport) -> dict:
    return {
        "id": ride.id,
        "mode": ride.mode,
        "provider_name": ride.provider_name,
        "from_label": ride.from_label,
        "to_label": ride.to_label,
        "city_code": ride.city_code,
        "timezone": ride.timezone,
        "pickup_utc": _iso(ride.pickup_utc),
        "dropoff_utc": _iso(ride.dropoff_utc),
        "pickup_local": format_local(ride.pickup_utc, ride.city_code, with_date=True),
        "booking_reference": ride.booking_reference,
        "status": ride.status,
        "status_label": _booking_status_label(ride.status),
        **_converted_cost(ride.cost_minor, ride.cost_currency),
        "provenance": ride.provenance,
        "source": ride.source,
        "fetched_at": _iso(ride.fetched_at),
    }


def disruption_payload(disruption: Disruption) -> dict:
    return {
        "id": disruption.id,
        "trip_id": disruption.trip_id,
        "segment_id": disruption.segment_id,
        "hotel_id": disruption.hotel_id,
        "ground_id": disruption.ground_id,
        "kind": disruption.kind,
        "kind_label": disruption.kind.replace("_", " ").capitalize(),
        "status": disruption.status,
        "severity": disruption.severity,
        "title": disruption.title,
        "detail": disruption.detail,
        "delay_minutes": disruption.delay_minutes,
        "delay_display": format_duration(disruption.delay_minutes) if disruption.delay_minutes else None,
        "detected_at_utc": _iso(disruption.detected_at_utc),
        "resolved_at_utc": _iso(disruption.resolved_at_utc),
        "provenance": disruption.provenance,
        "source": disruption.source,
        "cycle": disruption.cycle,
        "parent_disruption_id": disruption.parent_disruption_id,
        "payload": disruption.payload,
    }


_MONEY_IN_TEXT = re.compile(r"Additional cost ([A-Z]{3}) (\d[\d,]*\.\d{2})")


def _localized_explanation(plan: RecoveryPlan) -> str | None:
    """The stored explanation, with any embedded amount in the viewer's currency.

    Explanations are written once in the base currency; the amount inside the
    sentence is re-rendered here so the prose agrees with the figures on the card.
    """
    text = plan.explanation
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        source_currency, source_amount = match.group(1), match.group(2)
        minor = round(float(source_amount.replace(",", "")) * 100)
        amount, code = convert_minor(minor, source_currency)
        return f"Additional cost {_money(amount or 0, code or source_currency)}"

    return _MONEY_IN_TEXT.sub(replace, text)


def _localized_factors(plan: RecoveryPlan) -> list[str]:
    """Decision factors, with any amount shown in the viewer's currency.

    Factors are generated once and stored; the cost line is currency-bearing,
    so it is re-rendered here rather than shown in the stored currency.
    """
    cost_display = _cost_display(plan.additional_cost_minor, plan.currency)
    localized: list[str] = []
    for factor in plan.decision_factors or []:
        if factor.startswith("Additional cost:"):
            localized.append(f"Additional cost: {cost_display}")
        else:
            localized.append(factor)
    return localized


def plan_payload(plan: RecoveryPlan) -> dict:
    arrival_delta = minutes_between(plan.original_arrival_utc, plan.arrival_utc)
    return {
        "plan_id": plan.id,
        "disruption_id": plan.disruption_id,
        "trip_id": plan.trip_id,
        "cycle": plan.cycle,
        "label": plan.label,
        "title": plan.title,
        "summary": plan.summary,
        "status": plan.status,
        "status_label": _plan_status_label(plan.status),
        "recommended": plan.recommended,
        "score": round(plan.score, 2),
        "score_breakdown": plan.score_breakdown,
        "decision_factors": _localized_factors(plan),
        "segments": _convert_segment_list(plan.segments),
        "hotel_changes": _convert_plain(plan.hotel_changes),
        "ground_transport": _convert_plain(plan.ground_transport),
        "restrictions": plan.restrictions,
        "compensation": _convert_compensation(plan.compensation),
        "arrival_utc": _iso(plan.arrival_utc),
        "arrival_local": _arrival_local(plan),
        "original_arrival_utc": _iso(plan.original_arrival_utc),
        "original_arrival_local": _original_arrival_local(plan),
        "arrival_delta_minutes": arrival_delta,
        "arrival_delta_display": _arrival_delta_display(arrival_delta),
        "total_duration_minutes": plan.total_duration_minutes,
        "total_duration_display": format_duration(plan.total_duration_minutes),
        "additional_cost_minor": _plan_cost(plan.additional_cost_minor, plan.currency)[0],
        "additional_cost_display": _cost_display(plan.additional_cost_minor, plan.currency),
        "refund_estimate_minor": _plan_cost(plan.refund_estimate_minor, plan.currency)[0],
        "refund_estimate_display": (
            _cost_display(plan.refund_estimate_minor, plan.currency)
            if plan.refund_estimate_minor
            else "Not estimated"
        ),
        "currency": _plan_cost(plan.additional_cost_minor, plan.currency)[1],
        "risk_level": plan.risk_level,
        "connection_safety": plan.connection_safety,
        "changes_count": len(plan.segments) + len(plan.hotel_changes) + len(plan.ground_transport),
        "provenance": plan.provenance,
        "explanation": _localized_explanation(plan),
        "explanation_source": plan.explanation_source,
        "explanation_version": plan.explanation_version,
        "approved_at_utc": _iso(plan.approved_at_utc),
        "actions": [
            {
                "id": action.id,
                "sequence": action.sequence,
                "action_type": action.action_type,
                "target_kind": action.target_kind,
                "target_id": action.target_id,
                "description": action.description,
                "status": action.status,
                "status_label": _action_status_label(action.status),
                **_converted_action_cost(action.cost_minor, action.currency),
                "executed_at_utc": _iso(action.executed_at_utc),
                "result": action.result,
            }
            for action in sorted(plan.actions, key=lambda a: a.sequence)
        ],
    }


def _trip_provenance(segments: list) -> str:
    """The strongest provenance any of the trip's segments carries.

    A trip is badged by what it was actually built from, so a journey assembled
    from a real schedule reads LIVE and one from the rail timetable reads
    REFERENCE. A trip with no source at all reads UNAVAILABLE.
    """
    order = {"LIVE": 0, "CACHED": 1, "REFERENCE": 2, "SIMULATED": 3}
    if not segments:
        return "UNAVAILABLE"
    best = min((s.provenance for s in segments), key=lambda p: order.get(p, 4))
    return best


def trip_summary_payload(trip: Trip) -> dict:
    segments = sorted(trip.segments, key=lambda s: s.sequence)
    active = [d for d in trip.disruptions if d.status in {"detected", "validated", "assessed", "recovering"}]
    return {
        "id": trip.id,
        "reference": trip.reference,
        "name": trip.name,
        "purpose": trip.purpose,
        "traveller_id": trip.traveller_id,
        "traveller_name": trip.traveller.full_name if trip.traveller else None,
        "origin_code": trip.origin_code,
        "destination_code": trip.destination_code,
        "origin_city": require_place(trip.origin_code).city,
        "destination_city": require_place(trip.destination_code).city,
        "starts_at_utc": _iso(trip.starts_at_utc),
        "ends_at_utc": _iso(trip.ends_at_utc),
        "starts_at_local": format_local(trip.starts_at_utc, trip.origin_code, with_date=True),
        "ends_at_local": format_local(trip.ends_at_utc, trip.destination_code, with_date=True),
        "status": trip.status,
        "status_label": _trip_status_label(trip.status),
        "segment_count": len(segments),
        "hotel_count": len(trip.hotels),
        "ground_count": len(trip.ground),
        "disruption_count": len(trip.disruptions),
        "active_disruption_count": len(active),
        "provenance": _trip_provenance(segments),
    }


def _arrival_local(plan: RecoveryPlan) -> str:
    code = _final_place_code(plan)
    return format_local(plan.arrival_utc, code, with_date=True)


def _original_arrival_local(plan: RecoveryPlan) -> str:
    code = _final_place_code(plan)
    return format_local(plan.original_arrival_utc, code, with_date=True)


def _final_place_code(plan: RecoveryPlan) -> str:
    for segment in reversed(plan.segments or []):
        code = segment.get("destination_code")
        if code:
            return code
    return "BER"


def _arrival_delta_display(delta_minutes: int) -> str:
    if delta_minutes == 0:
        return "Arrives as originally planned"
    if delta_minutes < 0:
        return f"Arrives {format_duration(abs(delta_minutes))} earlier"
    return f"Arrives {format_duration(delta_minutes)} later"


def _money(minor: int, currency: str) -> str:
    from .domain.money import Money

    return str(Money(minor, currency))


def _mode_label(segment_type: str) -> str:
    return {
        "flight": "Flight",
        "train": "Rail",
        "bus": "Coach",
        "taxi": "Taxi",
        "transfer": "Transfer",
        "rental_car": "Rental car",
    }.get(segment_type, segment_type.title())


def _segment_status_label(status: str) -> str:
    return {
        SegmentStatus.SCHEDULED.value: "Scheduled",
        SegmentStatus.ON_TIME.value: "On time",
        SegmentStatus.AT_RISK.value: "At risk",
        SegmentStatus.DELAYED.value: "Delayed",
        SegmentStatus.DISRUPTED.value: "Disrupted",
        SegmentStatus.CANCELLED.value: "Cancelled",
        SegmentStatus.RECOVERING.value: "Recovery in progress",
        SegmentStatus.RECOVERED.value: "Recovered",
        SegmentStatus.COMPLETED.value: "Completed",
        SegmentStatus.MISSED.value: "Missed",
    }.get(status, status.replace("_", " ").title())


def _booking_status_label(status: str) -> str:
    return {
        BookingStatus.CONFIRMED.value: "Confirmed",
        BookingStatus.CHANGE_REQUESTED.value: "Change requested",
        BookingStatus.PENDING_PROVIDER.value: "Pending provider confirmation",
        BookingStatus.RECORDED_OFFLINE.value: "Recorded offline",
        BookingStatus.CANCELLED.value: "Cancelled",
        BookingStatus.UNCHANGED.value: "Unchanged",
    }.get(status, status.replace("_", " ").title())


def _plan_status_label(status: str) -> str:
    return {
        PlanStatus.PROPOSED.value: "Proposed",
        PlanStatus.APPROVED.value: "Approved",
        PlanStatus.EXECUTING.value: "Executing",
        PlanStatus.EXECUTED.value: "Executed",
        PlanStatus.REJECTED.value: "Rejected",
        PlanStatus.SUPERSEDED.value: "Superseded",
        PlanStatus.FAILED.value: "Failed",
    }.get(status, status.replace("_", " ").title())


def _action_status_label(status: str) -> str:
    return {
        "change_requested": "Change requested",
        "pending_provider_confirmation": "Pending provider confirmation",
        "recorded_offline": "Recorded offline",
        "confirmed": "Confirmed",
        "failed": "Failed",
    }.get(status, status.replace("_", " ").title())


def _trip_status_label(status: str) -> str:
    return {
        TripStatus.PLANNED.value: "Planned",
        TripStatus.ACTIVE.value: "Active",
        TripStatus.DISRUPTED.value: "Disrupted",
        TripStatus.RECOVERING.value: "Recovery in progress",
        TripStatus.COMPLETED.value: "Completed",
        TripStatus.CANCELLED.value: "Cancelled",
    }.get(status, status.replace("_", " ").title())


def safety_label(safety: ConnectionSafety | str) -> str:
    value = safety.value if isinstance(safety, ConnectionSafety) else safety
    return {
        ConnectionSafety.SAFE.value: "Connection maintained",
        ConnectionSafety.TIGHT.value: "Connection is tight",
        ConnectionSafety.AT_RISK.value: "Connection at risk",
        ConnectionSafety.BROKEN.value: "Connection not feasible",
    }.get(value, value)
