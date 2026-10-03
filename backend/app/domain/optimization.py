"""Plan scoring.

Deterministic. No LLM anywhere near this file. The score is a weighted sum
of normalised, individually explainable factors, so the UI can show exactly
why one plan is recommended over another.

The weights are product policy, not physics. They live here as named
constants so they can be tuned and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ConnectionSafety, RiskLevel

# --- policy weights (sum to 1.0) ---------------------------------------
WEIGHTS: dict[str, float] = {
    "arrival": 0.26,          # how soon the traveller reaches the destination
    "total_time": 0.14,       # door-to-door duration, not just flight time
    "cost": 0.18,             # additional cost to the traveller or company
    "connection": 0.16,       # feasibility and buffer of every connection
    "changes": 0.10,          # number of changes to the original booking
    "hotel_impact": 0.06,     # nights disturbed or added
    "ground": 0.04,           # whether ground transport still works
    "preference": 0.04,       # carrier, cabin, seat and timing preferences
    "visa": 0.02,             # transit and visa friction
}

# Cost is scored against this budget. Beyond it the cost factor bottoms out.
COST_TOLERANCE_MINOR = 90000  # EUR 900 of additional cost

# Arrival is scored against this horizon. Arriving later than this scores 0.
ARRIVAL_TOLERANCE_MINUTES = 26 * 60

PREFERENCE_AIRLINE_BONUS = 1.0
PREFERENCE_CABIN_BONUS = 1.0

SAFETY_SCORE: dict[ConnectionSafety, float] = {
    ConnectionSafety.SAFE: 1.0,
    ConnectionSafety.TIGHT: 0.6,
    ConnectionSafety.AT_RISK: 0.35,
    ConnectionSafety.BROKEN: 0.0,
}


@dataclass(slots=True)
class ScoreInput:
    """Everything the scorer needs, already computed by the plan builder."""

    plan_id: str
    label: str
    arrival_delay_minutes: int        # versus original itinerary arrival
    total_duration_minutes: int       # versus original itinerary duration
    original_duration_minutes: int
    additional_cost_minor: int
    connection_safety: ConnectionSafety
    worst_buffer_minutes: int
    changes_count: int
    hotel_nights_added: int
    hotel_nights_lost: int
    ground_transport_ok: bool
    uses_preferred_carrier: bool
    uses_preferred_cabin: bool
    visa_friction: bool
    risk_level: RiskLevel
    disruption_probability: float     # 0..1, from the risk prior
    is_single_mode_on_leg: bool = True


@dataclass(slots=True)
class ScoreResult:
    plan_id: str
    label: str
    total: float
    components: dict[str, float] = field(default_factory=dict)
    factors: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _arrival_factor(delay_minutes: int) -> float:
    """1.0 when the plan restores the original arrival, 0.0 at the horizon."""
    if delay_minutes <= 0:
        return 1.0
    return _clamp01(1.0 - delay_minutes / ARRIVAL_TOLERANCE_MINUTES)


def _total_time_factor(total_minutes: int, original_minutes: int) -> float:
    if original_minutes <= 0:
        return 0.5
    ratio = total_minutes / original_minutes
    # 1.0 when no longer than the original, 0.0 at 3x the original duration.
    return _clamp01((3.0 - ratio) / 2.0)


def _cost_factor(additional_minor: int) -> float:
    if additional_minor <= 0:
        return 1.0
    return _clamp01(1.0 - additional_minor / COST_TOLERANCE_MINOR)


def _connection_factor(safety: ConnectionSafety, buffer_minutes: int) -> float:
    """A feasible connection scores on its safety band; a broken one is zero."""
    del buffer_minutes  # buffer is already folded into the safety band
    return SAFETY_SCORE[safety]


def _changes_factor(changes: int) -> float:
    return _clamp01(1.0 - changes / 8.0)


def _hotel_factor(added: int, lost: int) -> float:
    return _clamp01(1.0 - (added + lost) / 4.0)


def _preference_factor(carrier: bool, cabin: bool) -> float:
    score = 0.4
    if carrier:
        score += PREFERENCE_AIRLINE_BONUS * 0.3
    if cabin:
        score += PREFERENCE_CABIN_BONUS * 0.3
    return _clamp01(score)


def score_plan(data: ScoreInput) -> ScoreResult:
    components = {
        "arrival": _arrival_factor(data.arrival_delay_minutes),
        "total_time": _total_time_factor(
            data.total_duration_minutes, data.original_duration_minutes
        ),
        "cost": _cost_factor(data.additional_cost_minor),
        "connection": _connection_factor(data.connection_safety, data.worst_buffer_minutes),
        "changes": _changes_factor(data.changes_count),
        "hotel_impact": _hotel_factor(data.hotel_nights_added, data.hotel_nights_lost),
        "ground": 1.0 if data.ground_transport_ok else 0.25,
        "preference": _preference_factor(data.uses_preferred_carrier, data.uses_preferred_cabin),
        "visa": 0.35 if data.visa_friction else 1.0,
    }
    total = sum(components[name] * WEIGHTS[name] for name in WEIGHTS)
    factors = explain(data, components)
    return ScoreResult(
        plan_id=data.plan_id,
        label=data.label,
        total=round(total * 100, 2),
        components={k: round(v, 4) for k, v in components.items()},
        factors=factors,
        risk_level=data.risk_level,
    )


def explain(data: ScoreInput, components: dict[str, float]) -> list[str]:
    """Concise decision factors, in plain language. No confidence percentages."""
    factors: list[str] = []

    if data.arrival_delay_minutes <= 0:
        factors.append("Restores the original arrival time")
    else:
        from .timeutil import format_duration

        factors.append(f"Arrives {format_duration(data.arrival_delay_minutes)} later than planned")

    if data.additional_cost_minor <= 0:
        factors.append("No additional cost")
    else:
        from .money import Money

        factors.append(f"Additional cost: {Money(data.additional_cost_minor, 'EUR')}")

    factors.append(
        {
            ConnectionSafety.SAFE: "All connections feasible with a comfortable buffer",
            ConnectionSafety.TIGHT: "A connection is tight and could still fail",
            ConnectionSafety.AT_RISK: "A connection is at risk if the inbound leg slips further",
            ConnectionSafety.BROKEN: "A connection does not work",
        }[data.connection_safety]
    )

    if data.changes_count == 0:
        factors.append("No changes to existing bookings")
    elif data.changes_count == 1:
        factors.append("One change to the existing booking")
    else:
        factors.append(f"{data.changes_count} changes to existing bookings")

    if data.hotel_nights_added:
        factors.append(
            f"Adds {data.hotel_nights_added} hotel night"
            + ("s" if data.hotel_nights_added > 1 else "")
        )
    if data.hotel_nights_lost:
        factors.append(f"Gives up {data.hotel_nights_lost} booked hotel night(s)")
    if not data.ground_transport_ok:
        factors.append("Ground transport needs rebooking")
    if data.visa_friction:
        factors.append("Requires leaving the international transit area")
    if data.uses_preferred_carrier:
        factors.append("Uses a preferred airline")

    return factors


def pick_recommended(results: list[ScoreResult]) -> ScoreResult | None:
    """Highest total score wins; ties break on the lower label for stability."""
    if not results:
        return None
    return sorted(results, key=lambda r: (-r.total, r.label))[0]


def compare_table(results: list[ScoreResult]) -> list[dict]:
    """Rows for the side-by-side comparison table."""
    return [
        {
            "plan_id": r.plan_id,
            "label": r.label,
            "score": r.total,
            "recommended": False,
            "components": r.components,
            "risk_level": r.risk_level.value,
        }
        for r in sorted(results, key=lambda x: (-x.total, x.label))
    ]
