"""Itinerary impact analysis.

Given a disruption on one segment, work out what else breaks. This is the
"cascading consequences" step: a delayed long-haul does not just move one
flight, it invalidates the connection, shifts the hotel check-in, and
orphans the airport transfer.

Pure functions over a plain snapshot of the journey so the logic is easy to
test without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .connections import ConnectionAssessment, assess_connection, arrival_shift_minutes
from .enums import ConnectionSafety, SegmentStatus, Severity
from .reference import require_place
from .timeutil import ensure_utc, minutes_between

# Typical time from arrival at the airport or station to hotel reception.
HOTEL_TRANSFER_MINUTES = 45
# Time from landing to being in a car for the onward transfer.
GROUND_WAIT_MINUTES = 50
# How long after check-in opens a non-refundable booking can go unattended
# before the hotel should be told the guest is still coming.
LATE_ARRIVAL_NOTICE_MINUTES = 90


@dataclass(frozen=True, slots=True)
class SegmentSnapshot:
    id: str
    sequence: int
    segment_type: str
    origin_code: str
    destination_code: str
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime
    effective_departure_utc: datetime
    effective_arrival_utc: datetime
    status: str
    carrier_code: str | None = None
    service_number: str | None = None
    booking_reference: str | None = None
    is_recovery: bool = False

    @property
    def origin_country(self) -> str:
        return require_place(self.origin_code).country

    @property
    def destination_country(self) -> str:
        return require_place(self.destination_code).country


@dataclass(frozen=True, slots=True)
class HotelSnapshot:
    id: str
    name: str
    city_code: str
    check_in_utc: datetime
    check_out_utc: datetime
    booking_reference: str | None = None
    late_arrival_notice: bool = False
    refundable: bool = False
    cost_minor: int = 0
    currency: str = "EUR"
    provenance: str = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class GroundSnapshot:
    id: str
    mode: str
    from_label: str
    to_label: str
    city_code: str
    pickup_utc: datetime
    booking_reference: str | None = None


@dataclass(slots=True)
class ImpactItem:
    """One consequence of a disruption, with a severity and a reason."""

    kind: str
    severity: Severity
    title: str
    detail: str
    segment_id: str | None = None
    hotel_id: str | None = None
    ground_id: str | None = None
    delta_minutes: int | None = None
    requires_action: bool = True


@dataclass(slots=True)
class ImpactAssessment:
    disruption_segment_id: str | None
    delay_minutes: int
    severity: Severity
    items: list[ImpactItem] = field(default_factory=list)
    connection_assessments: list[ConnectionAssessment] = field(default_factory=list)
    final_arrival_shift_minutes: int = 0
    affected_segment_ids: list[str] = field(default_factory=list)
    affected_hotel_ids: list[str] = field(default_factory=list)
    affected_ground_ids: list[str] = field(default_factory=list)
    connection_safety: ConnectionSafety = ConnectionSafety.SAFE

    @property
    def has_broken_connection(self) -> bool:
        return any(not a.feasible for a in self.connection_assessments)

    @property
    def summary(self) -> str:
        broken = [a for a in self.connection_assessments if not a.feasible]
        if broken:
            first = broken[0]
            return (
                f"{first.airport_code} connection at risk: {first.shortfall_minutes} min short "
                f"of the {first.required_minutes} min minimum"
            )
        if self.items:
            return self.items[0].title
        return "No downstream impact"


def assess_itinerary_impact(
    *,
    segments: list[SegmentSnapshot],
    hotels: list[HotelSnapshot],
    ground: list[GroundSnapshot],
    disrupted_segment_id: str | None,
    delay_minutes: int = 0,
    cancelled: bool = False,
    missed_connection: bool = False,
    baggage_recheck: bool = False,
    projected_arrival_utc: datetime | None = None,
) -> ImpactAssessment:
    """Compute the cascading effect of a disruption across the whole journey.

    ``delay_minutes`` is descriptive: it drives severity and copy. The
    *times* come from the snapshots' effective fields, which the caller has
    already updated to reflect the disruption. Keeping a single source of
    truth for the times is what stops a delay being applied twice.

    ``projected_arrival_utc`` is the arrival at the final destination that
    recovery is expected to achieve. It is optional: when a connection is
    broken and no replacement has been chosen yet, the caller leaves it out
    and the hotel and ground-transport consequences are deferred rather than
    guessed.
    """
    ordered = sorted(segments, key=lambda s: (s.sequence, s.scheduled_departure_utc))
    if not ordered:
        return ImpactAssessment(None, delay_minutes, Severity.LOW)

    index = next(
        (i for i, s in enumerate(ordered) if s.id == disrupted_segment_id),
        None,
    )

    # Effective times, as already updated by the caller. The onward leg keeps
    # its own schedule, which is exactly why a delay can break a connection.
    effective: dict[str, tuple[datetime, datetime]] = {
        s.id: (s.effective_departure_utc, s.effective_arrival_utc) for s in ordered
    }

    items: list[ImpactItem] = []
    assessments: list[ConnectionAssessment] = []

    if index is None:
        return ImpactAssessment(None, delay_minutes, Severity.LOW)

    disrupted = ordered[index]
    arrival = effective[disrupted.id][1]

    if cancelled:
        items.append(
            ImpactItem(
                kind="segment_cancelled",
                severity=Severity.CRITICAL,
                title=f"{disrupted.service_number or disrupted.segment_type} cancelled",
                detail=(
                    f"The {disrupted.origin_code} to {disrupted.destination_code} leg will not operate. "
                    "The traveller needs a replacement on this leg."
                ),
                segment_id=disrupted.id,
                requires_action=True,
            )
        )
    else:
        items.append(
            ImpactItem(
                kind="segment_delayed",
                severity=_delay_severity(delay_minutes),
                title=(
                    f"{disrupted.service_number or disrupted.segment_type} delayed "
                    f"{_human(delay_minutes)}"
                ),
                detail=(
                    f"New estimated arrival at {disrupted.destination_code} is "
                    f"{_human(minutes_between(disrupted.scheduled_arrival_utc, arrival))} later "
                    "than scheduled."
                ),
                segment_id=disrupted.id,
                delta_minutes=delay_minutes,
                requires_action=False,
            )
        )

    # Walk forward: every subsequent leg must still connect.
    #
    # A broken connection does not mean "the outbound waits for you". The
    # outbound departs on schedule and the traveller is left behind, so the
    # downstream leg is marked MISSED and no arrival time is invented here.
    # The caller supplies the arrival that recovery actually achieves, which
    # is what drives the hotel and ground-transport consequences below.
    previous_arrival = arrival
    previous_place = disrupted.destination_code
    chain_broken = False

    for nxt in ordered[index + 1 :]:
        if nxt.origin_code != previous_place:
            # A gap in the chain (different city); re-anchor without an assessment.
            previous_arrival = effective[nxt.id][0]
            previous_place = nxt.destination_code
            continue

        departure = effective[nxt.id][0]

        assessment = assess_connection(
            airport_code=previous_place,
            arriving_at_utc=previous_arrival,
            departing_at_utc=departure,
            origin_country=nxt.origin_country,
            destination_country=nxt.destination_country,
            requires_baggage_recheck=baggage_recheck,
        )
        assessments.append(assessment)

        if not assessment.feasible:
            chain_broken = True
            items.append(
                ImpactItem(
                    kind="connection_broken",
                    severity=Severity.CRITICAL,
                    title=f"{previous_place} connection no longer feasible",
                    detail=(
                        f"{nxt.origin_code} to {nxt.destination_code} departs "
                        f"{assessment.buffer_minutes} min after the inbound arrives, "
                        f"against a {assessment.required_minutes} min minimum connection time. "
                        f"Short by {assessment.shortfall_minutes} min. The leg is missed as booked."
                    ),
                    segment_id=nxt.id,
                    delta_minutes=assessment.shortfall_minutes,
                    requires_action=True,
                )
            )
            items.append(
                ImpactItem(
                    kind="segment_missed",
                    severity=Severity.CRITICAL,
                    title=f"{nxt.service_number or nxt.segment_type} will be missed",
                    detail=(
                        f"The {nxt.origin_code} to {nxt.destination_code} service departs before the "
                        "traveller can reach the gate. A replacement on this leg is required."
                    ),
                    segment_id=nxt.id,
                    requires_action=True,
                )
            )
        elif assessment.safety == ConnectionSafety.TIGHT:
            items.append(
                ImpactItem(
                    kind="connection_tight",
                    severity=Severity.MEDIUM,
                    title=f"{previous_place} connection is tight",
                    detail=(
                        f"{assessment.buffer_minutes} min against a {assessment.required_minutes} min "
                        "minimum. A further short delay would break it."
                    ),
                    segment_id=nxt.id,
                    requires_action=False,
                )
            )
        else:
            items.append(
                ImpactItem(
                    kind="connection_ok",
                    severity=Severity.LOW,
                    title=f"{previous_place} connection maintained",
                    detail=(
                        f"{assessment.buffer_minutes} min against a {assessment.required_minutes} min minimum."
                    ),
                    segment_id=nxt.id,
                    requires_action=False,
                )
            )

        previous_arrival = effective[nxt.id][1]
        previous_place = nxt.destination_code

    final_segment = ordered[-1]
    final_arrival_shift = 0
    if not chain_broken:
        final_arrival_shift = arrival_shift_minutes(
            final_segment.scheduled_arrival_utc, effective[final_segment.id][1]
        )
        if final_arrival_shift:
            items.append(
                ImpactItem(
                    kind="arrival_shift",
                    severity=_delay_severity(final_arrival_shift),
                    title=f"Arrival at {final_segment.destination_code} shifts {_human(final_arrival_shift)}",
                    detail=(
                        f"Planned {final_segment.scheduled_arrival_utc:%H:%M}Z, now "
                        f"{effective[final_segment.id][1]:%H:%M}Z."
                    ),
                    segment_id=final_segment.id,
                    delta_minutes=final_arrival_shift,
                    requires_action=False,
                )
            )

    # What recovery actually achieves. When the chain is broken and no
    # replacement has been selected yet, there is no honest projected arrival
    # to show, so the hotel and ground consequences wait for the plan.
    projected_final_arrival = projected_arrival_utc
    if projected_final_arrival is None and not chain_broken:
        projected_final_arrival = effective[final_segment.id][1]

    if projected_final_arrival is not None:
        final_arrival_shift = arrival_shift_minutes(
            final_segment.scheduled_arrival_utc, projected_final_arrival
        )
        if chain_broken:
            items.append(
                ImpactItem(
                    kind="arrival_projected",
                    severity=_delay_severity(max(final_arrival_shift, 0)),
                    title=(
                        f"Earliest arrival at {final_segment.destination_code} is "
                        f"{_human(final_arrival_shift)} later than planned"
                    ),
                    detail=(
                        f"Using the earliest feasible replacement, arrival moves to "
                        f"{projected_final_arrival:%H:%M}Z."
                    ),
                    segment_id=final_segment.id,
                    delta_minutes=final_arrival_shift,
                    requires_action=False,
                )
            )

    # Hotels: a later arrival means a late-arrival notice or a lost first night.
    affected_hotels: list[str] = []
    for stay in hotels:
        landing = (
            projected_final_arrival
            if projected_final_arrival is not None
            else _projected_arrival_at(stay.city_code, ordered, effective)
        )
        if landing is None:
            continue
        # Time from wheels down (or platform) to the hotel reception.
        projected = landing + timedelta(minutes=HOTEL_TRANSFER_MINUTES)
        late_by = minutes_between(stay.check_in_utc, projected)

        if projected.date() > stay.check_in_utc.date():
            # A different calendar day means the booking itself has to move,
            # not just be held with a late-arrival notice.
            affected_hotels.append(stay.id)
            items.append(
                ImpactItem(
                    kind="hotel_shift_needed",
                    severity=Severity.HIGH,
                    title=f"{stay.name}: booking night must move",
                    detail=(
                        f"Projected arrival at the hotel is {projected:%d %b %H:%M}Z, the day after "
                        f"the booked check-in of {stay.check_in_utc:%d %b %H:%M}Z. "
                        "The first night cannot be used."
                    ),
                    hotel_id=stay.id,
                    delta_minutes=late_by,
                )
            )
        elif projected > stay.check_in_utc + timedelta(hours=4):
            # Past the point a hotel would normally release an untouched room.
            affected_hotels.append(stay.id)
            items.append(
                ImpactItem(
                    kind="hotel_at_risk",
                    severity=Severity.HIGH,
                    title=f"{stay.name}: room at risk of release",
                    detail=(
                        f"Projected arrival at the hotel is {projected:%H:%M}Z, "
                        f"{late_by} min after check-in opens. Without contact the hotel may "
                        "release the room."
                    ),
                    hotel_id=stay.id,
                    delta_minutes=late_by,
                )
            )
        elif projected > stay.check_in_utc + timedelta(minutes=LATE_ARRIVAL_NOTICE_MINUTES):
            affected_hotels.append(stay.id)
            items.append(
                ImpactItem(
                    kind="hotel_late_arrival",
                    severity=Severity.MEDIUM,
                    title=f"{stay.name}: late-arrival notice needed",
                    detail=(
                        f"Projected arrival at the hotel is {projected:%H:%M}Z, "
                        f"{late_by} min after check-in opens. A late-arrival notice holds the room."
                    ),
                    hotel_id=stay.id,
                    delta_minutes=late_by,
                )
            )
        else:
            items.append(
                ImpactItem(
                    kind="hotel_on_time",
                    severity=Severity.LOW,
                    title=f"{stay.name}: arrival within the check-in window",
                    detail=f"Projected arrival {projected:%H:%M}Z. No action needed.",
                    hotel_id=stay.id,
                    requires_action=False,
                )
            )

    # Ground transport: a pickup before the traveller lands is orphaned.
    affected_ground: list[str] = []
    for ride in ground:
        landing = (
            projected_final_arrival
            if projected_final_arrival is not None
            else _projected_arrival_at(ride.city_code, ordered, effective)
        )
        if landing is None:
            continue
        projected = landing + timedelta(minutes=GROUND_WAIT_MINUTES)
        if ride.pickup_utc < projected:
            affected_ground.append(ride.id)
            items.append(
                ImpactItem(
                    kind="ground_orphaned",
                    severity=Severity.HIGH,
                    title=f"{ride.mode.title()} pickup no longer works",
                    detail=(
                        f"Pickup is scheduled for {ride.pickup_utc:%H:%M}Z but the traveller now "
                        f"arrives at {projected:%H:%M}Z. The transfer must be rebooked."
                    ),
                    ground_id=ride.id,
                    delta_minutes=minutes_between(ride.pickup_utc, projected),
                )
            )

    severity = _overall_severity(items, cancelled, missed_connection)
    safety = _worst(assessments)

    return ImpactAssessment(
        disruption_segment_id=disrupted.id,
        delay_minutes=delay_minutes,
        severity=severity,
        items=items,
        connection_assessments=assessments,
        final_arrival_shift_minutes=final_arrival_shift,
        affected_segment_ids=[i.segment_id for i in items if i.segment_id and i.requires_action],
        affected_hotel_ids=affected_hotels,
        affected_ground_ids=affected_ground,
        connection_safety=safety,
    )


def _projected_arrival_at(
    city_code: str,
    ordered: list[SegmentSnapshot],
    effective: dict[str, tuple[datetime, datetime]],
) -> datetime | None:
    """Latest projected arrival at a city, using the effective times."""
    arrivals = [
        effective[s.id][1]
        for s in ordered
        if s.destination_code == city_code and s.id in effective
    ]
    if not arrivals:
        return None
    return max(arrivals)


def _delay_severity(minutes: int) -> Severity:
    if minutes >= 240:
        return Severity.CRITICAL
    if minutes >= 120:
        return Severity.HIGH
    if minutes >= 45:
        return Severity.MEDIUM
    return Severity.LOW


def _overall_severity(
    items: list[ImpactItem], cancelled: bool, missed: bool
) -> Severity:
    if cancelled or missed:
        return Severity.CRITICAL
    severities = [i.severity for i in items if i.requires_action]
    if Severity.CRITICAL in severities:
        return Severity.CRITICAL
    if Severity.HIGH in severities:
        return Severity.HIGH
    if Severity.MEDIUM in severities:
        return Severity.MEDIUM
    return Severity.LOW


def _worst(assessments: list[ConnectionAssessment]) -> ConnectionSafety:
    order = [
        ConnectionSafety.SAFE,
        ConnectionSafety.TIGHT,
        ConnectionSafety.AT_RISK,
        ConnectionSafety.BROKEN,
    ]
    if not assessments:
        return ConnectionSafety.SAFE
    return max((a.safety for a in assessments), key=order.index)


def _human(minutes: int) -> str:
    from .timeutil import format_duration

    return format_duration(minutes)


def segment_status_after_impact(
    assessment: ImpactAssessment, segment_id: str
) -> SegmentStatus | None:
    """The status a segment should carry after the impact is applied."""
    if segment_id == assessment.disruption_segment_id:
        if any(i.kind == "segment_cancelled" for i in assessment.items):
            return SegmentStatus.CANCELLED
        return SegmentStatus.DELAYED
    for item in assessment.items:
        if item.segment_id == segment_id:
            if item.kind == "connection_broken":
                return SegmentStatus.AT_RISK
            if item.kind == "connection_tight":
                return SegmentStatus.AT_RISK
    return None


def ensure_utc_chain(*values: datetime) -> list[datetime]:
    return [ensure_utc(v) for v in values]
