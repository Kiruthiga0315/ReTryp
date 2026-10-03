"""Connection feasibility.

The single most important piece of arithmetic in the product: given the
effective arrival of one segment and the effective departure of the next,
is the connection still makeable, and how much slack is left?

All inputs and outputs are UTC. Local times are only ever used for display,
which is why the timezone handling lives in ``timeutil`` and never here.
The tests in ``tests/test_connections.py`` cover the DST edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .enums import ConnectionSafety
from .mct import TIGHT_MARGIN_MINUTES, intermodal_transfer_minutes, mct_for, transfer_kind
from .reference import PLACES, require_place
from .timeutil import ensure_utc, minutes_between, to_local


@dataclass(frozen=True, slots=True)
class ConnectionAssessment:
    feasible: bool
    safety: ConnectionSafety
    buffer_minutes: int
    required_minutes: int
    shortfall_minutes: int
    airport_code: str
    mct_source: str
    mct_verified_on: str
    note: str

    @property
    def label(self) -> str:
        return {
            ConnectionSafety.SAFE: "Connection maintained",
            ConnectionSafety.TIGHT: "Connection is tight",
            ConnectionSafety.AT_RISK: "Connection at risk",
            ConnectionSafety.BROKEN: "Connection no longer feasible",
        }[self.safety]


def assess_connection(
    *,
    airport_code: str,
    arriving_at_utc: datetime,
    departing_at_utc: datetime,
    origin_country: str | None = None,
    destination_country: str | None = None,
    requires_baggage_recheck: bool = False,
    requires_immigration: bool = True,
    from_place: str | None = None,
    to_place: str | None = None,
) -> ConnectionAssessment:
    """Assess whether a connection at ``airport_code`` still works.

    ``arriving_at_utc`` is the effective arrival of the inbound segment and
    ``departing_at_utc`` the effective departure of the outbound segment.
    """
    kind = transfer_kind(
        origin_country or "XX", destination_country or "YY"
    )
    from_kind = PLACES.get(from_place).kind if from_place and from_place in PLACES else None
    to_kind = PLACES.get(to_place).kind if to_place and to_place in PLACES else None

    if from_kind == "rail" and to_kind == "rail" and from_place == to_place:
        base_minutes = 20
        source = "Rail station platform transfer buffer"
        verified_on = "2026-10-01"
    elif from_place and to_place and from_place != to_place:
        intermodal_mins = intermodal_transfer_minutes(from_place, to_place)
        base_minutes = intermodal_mins
        source = f"Inter-modal transfer allowance ({from_place} to {to_place})"
        verified_on = "2026-10-01"
    else:
        base_minutes, source, verified_on = mct_for(airport_code, kind)

    required = base_minutes
    if requires_baggage_recheck:
        required += 20
    if not requires_immigration and from_kind != "rail":
        required -= 10
    required = max(required, 15)

    buffer_minutes = minutes_between(arriving_at_utc, departing_at_utc)
    shortfall = max(0, required - buffer_minutes)

    if buffer_minutes < required:
        safety = ConnectionSafety.BROKEN
    elif buffer_minutes < required + TIGHT_MARGIN_MINUTES:
        safety = ConnectionSafety.TIGHT
    else:
        safety = ConnectionSafety.SAFE

    notes: list[str] = []
    if requires_baggage_recheck:
        notes.append("Baggage must be re-checked")
    if not requires_immigration:
        notes.append("No immigration control required on this transfer")
    if safety == ConnectionSafety.BROKEN:
        notes.append(f"Short by {shortfall} min against a {required} min minimum")
    elif safety == ConnectionSafety.TIGHT:
        notes.append(f"{buffer_minutes} min against a {required} min minimum")

    return ConnectionAssessment(
        feasible=safety != ConnectionSafety.BROKEN,
        safety=safety,
        buffer_minutes=buffer_minutes,
        required_minutes=required,
        shortfall_minutes=shortfall,
        airport_code=airport_code.upper(),
        mct_source=source,
        mct_verified_on=verified_on,
        note=". ".join(notes),
    )


def assess_chain(
    legs: list[tuple[str, datetime, datetime]],
    *,
    requires_immigration_at: set[str] | None = None,
) -> list[ConnectionAssessment]:
    """Assess every connection in a chain of ``(airport, arrival, departure)``."""
    immigration = requires_immigration_at or set()
    results: list[ConnectionAssessment] = []
    for airport_code, arrival, departure in legs:
        results.append(
            assess_connection(
                airport_code=airport_code,
                arriving_at_utc=arrival,
                departing_at_utc=departure,
                requires_immigration=airport_code in immigration or not immigration,
            )
        )
    return results


def worst_safety(assessments: list[ConnectionAssessment]) -> ConnectionSafety:
    order = [
        ConnectionSafety.SAFE,
        ConnectionSafety.TIGHT,
        ConnectionSafety.AT_RISK,
        ConnectionSafety.BROKEN,
    ]
    if not assessments:
        return ConnectionSafety.SAFE
    return max((a.safety for a in assessments), key=order.index)


def arrival_shift_minutes(
    original_arrival_utc: datetime, new_arrival_utc: datetime
) -> int:
    """Positive means later than originally planned."""
    return minutes_between(
        ensure_utc(original_arrival_utc), ensure_utc(new_arrival_utc)
    )


def local_hour_offset(place_a: str, place_b: str, moment: datetime | None = None) -> int:
    """Whole-hour offset between two places' local clocks, for display copy."""
    ref = ensure_utc(moment) if moment else datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    a = to_local(ref, place_a).utcoffset() or timedelta()
    b = to_local(ref, place_b).utcoffset() or timedelta()
    return int((b - a).total_seconds() // 3600)


__all__ = [
    "ConnectionAssessment",
    "assess_chain",
    "assess_connection",
    "arrival_shift_minutes",
    "local_hour_offset",
    "worst_safety",
    "require_place",
]
