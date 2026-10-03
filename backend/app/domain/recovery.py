"""Recovery planning.

Searches the option catalogue for replacements on every leg that no longer
works, assembles complete plans (transport + hotel + ground transport),
scores them and picks a recommendation.

This module is deterministic and provider-agnostic: it consumes whatever the
provider layer returns, and reads the itinerary it is given rather than
searching for candidates itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .connections import assess_connection, arrival_shift_minutes
from .enums import ConnectionSafety, RiskLevel, SegmentType
from .impact import (
    HOTEL_TRANSFER_MINUTES,
    GroundSnapshot,
    HotelSnapshot,
    SegmentSnapshot,
    assess_itinerary_impact,
)
from .money import Money
from .optimization import ScoreInput, ScoreResult, pick_recommended, score_plan
from .options import OptionSegment
from .reference import require_place
from .timeutil import format_duration, format_local, minutes_between

# A plan must leave at least this much slack beyond the minimum connection
# time, or it is rejected rather than offered as "safe".
SAFE_SLACK_MINUTES = 15

# Assumed probability that a given replacement leg slips further. Derived
# from the regional punctuality prior, not invented per plan.
DEFAULT_DISRUPTION_PROBABILITY = 0.22


@dataclass(slots=True)
class ReplacementLeg:
    option: OptionSegment
    connection_safety: ConnectionSafety
    buffer_minutes: int
    required_minutes: int
    note: str = ""


@dataclass(slots=True)
class PlanDraft:
    label: str
    title: str
    summary: str
    legs: list[ReplacementLeg]
    hotel_changes: list[dict] = field(default_factory=list)
    ground_transport: list[dict] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    keeps_original_segment_ids: list[str] = field(default_factory=list)
    replaces_segment_ids: list[str] = field(default_factory=list)
    arrival_utc: datetime | None = None
    total_duration_minutes: int = 0
    additional_cost_minor: int = 0
    refund_estimate_minor: int = 0
    connection_safety: ConnectionSafety = ConnectionSafety.SAFE
    risk_level: RiskLevel = RiskLevel.MEDIUM
    disruption_probability: float = DEFAULT_DISRUPTION_PROBABILITY
    changes_count: int = 0
    hotel_nights_added: int = 0
    hotel_nights_lost: int = 0
    ground_transport_ok: bool = True
    uses_preferred_carrier: bool = False
    uses_preferred_cabin: bool = False
    visa_friction: bool = False
    currency: str = "EUR"


@dataclass(slots=True)
class ScoredPlan:
    draft: PlanDraft
    score: ScoreResult

    @property
    def label(self) -> str:
        return self.draft.label


def _replacement_legs_for(
    *,
    airport_code: str,
    available_from_utc: datetime,
    destination_market: str,
    candidates: list[OptionSegment],
    requires_immigration: bool = True,
    origin_leg: bool = False,
    exclude_service: str | None = None,
) -> list[ReplacementLeg]:
    """Filter candidates to those that actually connect, and grade the buffer.

    Candidates are matched on the destination *market*, not the exact station
    or airport code, so a rail option arriving at Berlin Hauptbahnhof counts
    as reaching BER.

    When the broken leg is the journey's last leg (``origin_leg``) there is no
    onward connection to protect, so the minimum connection time does not
    apply: any service departing after the traveller is free is a valid
    replacement, graded only on how much slack it leaves.
    """
    legs: list[ReplacementLeg] = []
    for option in sorted(candidates, key=lambda c: c.departure_utc):
        if exclude_service and option.service_number == exclude_service:
            continue
        if require_place(option.destination_code).market != destination_market:
            continue
        transfer_mins = 0
        earliest_dep = available_from_utc
        if airport_code != option.origin_code:
            from .mct import intermodal_transfer_minutes
            transfer_mins = intermodal_transfer_minutes(airport_code, option.origin_code)
            earliest_dep = available_from_utc + timedelta(minutes=transfer_mins)

        if option.departure_utc <= earliest_dep:
            continue

        if origin_leg:
            slack = minutes_between(earliest_dep, option.departure_utc)
            note = "Departing from the origin of the disrupted leg; no connection to protect."
            if transfer_mins > 0:
                note = f"Includes {transfer_mins} min transfer from {airport_code} to {option.origin_code}."
            legs.append(
                ReplacementLeg(
                    option=option,
                    connection_safety=ConnectionSafety.SAFE if slack >= 20 else ConnectionSafety.TIGHT,
                    buffer_minutes=slack,
                    required_minutes=transfer_mins,
                    note=note,
                )
            )
            continue
        assessment = assess_connection(
            airport_code=airport_code,
            arriving_at_utc=available_from_utc,
            departing_at_utc=option.departure_utc,
            requires_immigration=requires_immigration,
            from_place=airport_code,
            to_place=option.origin_code,
        )
        if not assessment.feasible:
            continue
        legs.append(
            ReplacementLeg(
                option=option,
                connection_safety=assessment.safety,
                buffer_minutes=assessment.buffer_minutes,
                required_minutes=assessment.required_minutes,
                note=assessment.note,
            )
        )
    return legs


def _pick_transfer(
    options: list, city_code: str, arrive_by_utc: datetime, from_label_hint: str | None = None
) -> dict | None:
    """Earliest transfer whose pickup is after the traveller can be there."""
    ready_at = arrive_by_utc + timedelta(minutes=HOTEL_TRANSFER_MINUTES - 15)
    best = None
    for option in sorted(options, key=lambda o: o.pickup_utc):
        if option.city_code != city_code:
            continue
        if option.pickup_utc < ready_at:
            continue
        if from_label_hint and from_label_hint not in option.from_label:
            continue
        best = option
        break
    if best is None:
        return None
    return {
        "key": best.key,
        "mode": "transfer",
        "provider_name": best.provider_name,
        "from_label": best.from_label,
        "to_label": best.to_label,
        "city_code": best.city_code,
        "timezone": best.timezone,
        "pickup_utc": best.pickup_utc.isoformat(),
        "dropoff_utc": best.dropoff_utc.isoformat(),
        "pickup_local": format_local(best.pickup_utc, best.city_code, with_date=True),
        "cost_minor": best.cost_minor,
        "currency": best.currency,
        "provenance": best.provenance,
        "note": best.note,
        "action": "rebook",
    }


@dataclass(slots=True)
class RecoveryTarget:
    """Which leg must be replaced, and where the traveller waits for it.

    Two shapes occur:

    * A delay breaks a *downstream* leg. The traveller is at the connection
      airport, free from the inbound leg's arrival.
    * A cancellation or missed connection breaks the *disrupted* leg itself.
      The traveller is at that leg's origin, free from its scheduled
      departure.
    """

    segment_id: str
    origin_code: str
    destination_code: str
    available_from_utc: datetime
    origin_market: str
    destination_market: str
    requires_immigration: bool
    # True when the broken leg is itself the last leg of the journey, so the
    # traveller is already at that leg's origin and no onward connection (and
    # therefore no minimum connection time) applies.
    origin_leg: bool = False


def find_recovery_target(
    segments: list[SegmentSnapshot],
    disrupted_segment_id: str,
    *,
    cancelled: bool = False,
    missed_connection: bool = False,
) -> RecoveryTarget | None:
    """Work out which leg recovery has to fix.

    Returns ``None`` when nothing needs replacing, which is the case for a
    delay that is fully absorbed at the connection.
    """
    ordered = sorted(segments, key=lambda s: (s.sequence, s.scheduled_departure_utc))
    index = next((i for i, s in enumerate(ordered) if s.id == disrupted_segment_id), None)
    if index is None:
        return None
    disrupted = ordered[index]

    # A leg that cannot operate at all must be replaced outright.
    if cancelled or missed_connection:
        return RecoveryTarget(
            segment_id=disrupted.id,
            origin_code=disrupted.origin_code,
            destination_code=disrupted.destination_code,
            available_from_utc=disrupted.scheduled_departure_utc,
            origin_market=require_place(disrupted.origin_code).market,
            destination_market=require_place(disrupted.destination_code).market,
            requires_immigration=False,
            origin_leg=True,
        )

    # Otherwise, the first downstream leg that no longer connects.
    previous_arrival = disrupted.effective_arrival_utc
    previous_place = disrupted.destination_code
    for nxt in ordered[index + 1 :]:
        if nxt.origin_code != previous_place:
            previous_arrival = nxt.effective_departure_utc
            previous_place = nxt.destination_code
            continue
        assessment = assess_connection(
            airport_code=previous_place,
            arriving_at_utc=previous_arrival,
            departing_at_utc=nxt.effective_departure_utc,
        )
        if not assessment.feasible:
            return RecoveryTarget(
                segment_id=nxt.id,
                origin_code=nxt.origin_code,
                destination_code=nxt.destination_code,
                available_from_utc=previous_arrival,
                origin_market=require_place(nxt.origin_code).market,
                destination_market=require_place(nxt.destination_code).market,
                requires_immigration=True,
            )
        previous_arrival = nxt.effective_arrival_utc
        previous_place = nxt.destination_code

    # Nothing downstream broke. If the disrupted leg is itself the last leg of
    # the journey - a single-leg trip, or a delay on the final leg - the
    # traveller is stranded at that leg's origin with no onward connection to
    # protect. The leg can still be replaced: a same-day flight or rail service
    # that gets them there sooner is a valid recovery. No minimum connection
    # time applies because this is the origin of the broken leg, not a transfer.
    if index == len(ordered) - 1:
        return RecoveryTarget(
            segment_id=disrupted.id,
            origin_code=disrupted.origin_code,
            destination_code=disrupted.destination_code,
            available_from_utc=disrupted.effective_departure_utc,
            origin_market=require_place(disrupted.origin_code).market,
            destination_market=require_place(disrupted.destination_code).market,
            requires_immigration=False,
            origin_leg=True,
        )
    return None


def build_plan_drafts(
    *,
    segments: list[SegmentSnapshot],
    hotels: list[HotelSnapshot],
    ground: list[GroundSnapshot],
    disrupted_segment_id: str,
    delay_minutes: int,
    flight_options: list[OptionSegment],
    rail_options: list[OptionSegment],
    transfer_options: list,
    bus_options: list[OptionSegment] | None = None,
    cancelled: bool = False,
    missed_connection: bool = False,
    overnight_hotel: dict | None = None,
    preferred_airlines: list[str] | None = None,
    preferred_cabin: str | None = None,
    currency: str = "EUR",
    hub_itineraries: list | None = None,
) -> list[PlanDraft]:
    """Build every feasible complete plan for a single-segment disruption.

    The shape is always: transport for the broken leg, then whatever the new
    arrival time does to the hotel and to the ground transfer.

    ``segments`` must already carry the disruption in their effective times.
    ``delay_minutes`` is descriptive only; it is never added to a time here,
    because that would double-count the delay the caller already applied.
    """
    ordered = sorted(segments, key=lambda s: (s.sequence, s.scheduled_departure_utc))
    index = next(i for i, s in enumerate(ordered) if s.id == disrupted_segment_id)
    disrupted = ordered[index]

    original_final = ordered[-1].scheduled_arrival_utc
    original_duration = minutes_between(
        ordered[0].scheduled_departure_utc, ordered[-1].scheduled_arrival_utc
    )

    drafts: list[PlanDraft] = []

    target = find_recovery_target(
        segments,
        disrupted_segment_id,
        cancelled=cancelled,
        missed_connection=missed_connection,
    )
    if target is None:
        # An intermediate delay fully absorbed at the connection: the rest of
        # the journey still operates, so there is one plan - keep it. The final
        # arrival is the last leg's effective arrival, not its scheduled
        # arrival plus the delay (which would double-count it).
        assessment = assess_connection(
            airport_code=disrupted.destination_code,
            arriving_at_utc=disrupted.effective_arrival_utc,
            departing_at_utc=disrupted.effective_departure_utc,
        )
        final_arrival = ordered[-1].effective_arrival_utc
        drafts.append(
            PlanDraft(
                label="A",
                title="Keep the existing itinerary",
                summary=(
                    "The delay is absorbed and the rest of the journey continues as booked."
                ),
                legs=[],
                arrival_utc=final_arrival,
                total_duration_minutes=minutes_between(
                    ordered[0].scheduled_departure_utc, final_arrival
                ),
                connection_safety=assessment.safety,
                changes_count=0,
                ground_transport_ok=True,
                currency=currency,
            )
        )
        return drafts

    broken_leg = next(s for s in ordered if s.id == target.segment_id)
    transfer_airport = target.origin_code
    destination_market = target.destination_market
    inbound_arrival = target.available_from_utc

    # --- transport candidates for the broken leg -------------------------
    same_day_flights = _replacement_legs_for(
        airport_code=transfer_airport,
        available_from_utc=inbound_arrival,
        destination_market=destination_market,
        candidates=flight_options,
        requires_immigration=target.requires_immigration,
        origin_leg=target.origin_leg,
        exclude_service=broken_leg.service_number,
    )
    rail_legs = _replacement_legs_for(
        airport_code=transfer_airport,
        available_from_utc=inbound_arrival,
        destination_market=destination_market,
        candidates=rail_options,
        requires_immigration=target.requires_immigration,
        origin_leg=target.origin_leg,
    )
    bus_legs = _replacement_legs_for(
        airport_code=transfer_airport,
        available_from_utc=inbound_arrival,
        destination_market=destination_market,
        candidates=bus_options or [],
        requires_immigration=target.requires_immigration,
        origin_leg=target.origin_leg,
    )

    def _arrival_place(draft: PlanDraft, arrival_at_destination: datetime) -> str:
        """Where the traveller physically arrives: station or airport terminal."""
        if draft.legs:
            return draft.legs[-1].option.destination_code
        del arrival_at_destination
        return broken_leg.destination_code

    def _downstream(draft: PlanDraft, arrival_at_destination: datetime) -> None:
        """Apply the hotel and ground consequences of a chosen arrival."""
        impact = assess_itinerary_impact(
            segments=segments,
            hotels=hotels,
            ground=ground,
            disrupted_segment_id=disrupted_segment_id,
            delay_minutes=delay_minutes,
            projected_arrival_utc=arrival_at_destination,
        )
        arrival_place = _arrival_place(draft, arrival_at_destination)

        for item in impact.items:
            if item.hotel_id and item.kind in {
                "hotel_late_arrival",
                "hotel_at_risk",
                "hotel_shift_needed",
            }:
                stay = next((h for h in hotels if h.id == item.hotel_id), None)
                if stay is None:
                    continue
                if item.kind == "hotel_shift_needed":
                    draft.hotel_nights_lost += 1
                    draft.hotel_changes.append(
                        {
                            "hotel_id": stay.id,
                            "name": stay.name,
                            "action": "shift_one_night",
                            "detail": (
                                f"Move the {stay.name} booking forward by one night: the traveller "
                                f"now arrives {arrival_at_destination:%d %b}."
                            ),
                            "cost_minor": 0,
                            "currency": currency,
                            "provenance": stay.provenance,
                        }
                    )
                else:
                    draft.hotel_changes.append(
                        {
                            "hotel_id": stay.id,
                            "name": stay.name,
                            "action": "late_arrival_notice",
                            "detail": (
                                f"Tell {stay.name} the guest is still arriving. Projected arrival "
                                f"at the hotel {item.delta_minutes} min after check-in opens."
                            ),
                            "cost_minor": 0,
                            "currency": currency,
                            "provenance": stay.provenance,
                        }
                    )
                if not stay.refundable:
                    draft.restrictions.append(
                        f"{stay.name} is non-refundable; changes depend on the property's goodwill."
                    )

            if item.kind == "ground_orphaned" and item.ground_id:
                ride = next((g for g in ground if g.id == item.ground_id), None)
                if ride is None:
                    continue
                hint = "Hauptbahnhof" if require_place(arrival_place).kind == "rail" else "Terminal"
                transfer = _pick_transfer(transfer_options, ride.city_code, arrival_at_destination, hint)
                if transfer is None:
                    transfer = _pick_transfer(transfer_options, ride.city_code, arrival_at_destination)
                if transfer is not None:
                    # A second orphaned ride (for example a transfer added by an
                    # earlier recovery cycle) can resolve to the same replacement.
                    # One rebooking covers it; do not bill or list it twice.
                    if any(existing["key"] == transfer["key"] for existing in draft.ground_transport):
                        continue
                    transfer["replaces"] = ride.booking_reference
                    transfer["original_pickup_utc"] = ride.pickup_utc.isoformat()
                    draft.ground_transport.append(transfer)
                    draft.additional_cost_minor += transfer["cost_minor"]
                else:
                    draft.ground_transport_ok = False
                    draft.restrictions.append("No transfer available at the new arrival time.")

    def _new_legs_from(legs: list[ReplacementLeg], count: int = 1) -> list[ReplacementLeg]:
        return legs[:count]

    # --- A: same-day flight ---------------------------------------------
    same_day = _new_legs_from(same_day_flights)
    if same_day:
        arrival = same_day[-1].option.arrival_utc
        draft = PlanDraft(
            label="A",
            title=f"Same-day flight to {broken_leg.destination_code}",
            summary=(
                f"Rebook {broken_leg.origin_code} to {broken_leg.destination_code} on "
                f"{same_day[-1].option.service_number} departing "
                f"{same_day[-1].option.departure_utc:%H:%M}Z, and keep the rest of the trip."
            ),
            legs=same_day,
            replaces_segment_ids=[broken_leg.id],
            keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
            arrival_utc=arrival,
            additional_cost_minor=sum(l.option.cost_minor for l in same_day),
            connection_safety=same_day[-1].connection_safety,
            changes_count=1 + len(ground) // 2,
            uses_preferred_carrier=bool(
                preferred_airlines and same_day[-1].option.carrier_code in preferred_airlines
            ),
            uses_preferred_cabin=bool(preferred_cabin and same_day[-1].option.cabin == preferred_cabin),
            currency=currency,
        )
        _downstream(draft, arrival)
        _finalise(draft, original_final, original_duration, ordered, index)
        drafts.append(draft)

    # --- B: rail instead of a flight on that leg -------------------------
    rail = _new_legs_from(rail_legs)
    if rail:
        arrival = rail[-1].option.arrival_utc
        draft = PlanDraft(
            label="B",
            title=f"Rail to {broken_leg.destination_code}",
            summary=(
                f"Travel {broken_leg.origin_code} to {broken_leg.destination_code} by "
                f"{rail[-1].option.service_number} instead of a flight on that leg."
            ),
            legs=rail,
            replaces_segment_ids=[broken_leg.id],
            keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
            arrival_utc=arrival,
            additional_cost_minor=sum(l.option.cost_minor for l in rail),
            connection_safety=rail[-1].connection_safety,
            changes_count=1 + len(ground) // 2,
            currency=currency,
            restrictions=[
                "Rail is a different mode on this leg; the ticket is separate from the flight booking."
            ],
        )
        _downstream(draft, arrival)
        _finalise(draft, original_final, original_duration, ordered, index)
        drafts.append(draft)

    # --- B2: express bus alternative on that leg ------------------------
    bus = _new_legs_from(bus_legs)
    if bus:
        arrival = bus[-1].option.arrival_utc
        draft = PlanDraft(
            label="B2",
            title=f"Express Bus to {broken_leg.destination_code}",
            summary=(
                f"Travel {broken_leg.origin_code} to {broken_leg.destination_code} by "
                f"{bus[-1].option.service_number} express coach instead of a flight."
            ),
            legs=bus,
            replaces_segment_ids=[broken_leg.id],
            keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
            arrival_utc=arrival,
            additional_cost_minor=sum(l.option.cost_minor for l in bus),
            connection_safety=bus[-1].connection_safety,
            changes_count=1 + len(ground) // 2,
            currency=currency,
            restrictions=[
                "Bus is a different mode on this leg; the ticket is separate from the airline booking."
            ],
        )
        _downstream(draft, arrival)
        _finalise(draft, original_final, original_duration, ordered, index)
        drafts.append(draft)

    # --- C: next morning, with an overnight near the airport -------------
    next_day_flights = [
        leg
        for leg in same_day_flights
        if leg.option.departure_utc.date() > inbound_arrival.date()
    ]
    if next_day_flights:
        first = next_day_flights[0]
        arrival = first.option.arrival_utc
        draft = PlanDraft(
            label="C",
            title=f"Next-morning connection to {broken_leg.destination_code}",
            summary=(
                f"Stay overnight at {broken_leg.origin_code} and take "
                f"{first.option.service_number} at {first.option.departure_utc:%H:%M}Z the next morning."
            ),
            legs=[first],
            replaces_segment_ids=[broken_leg.id],
            keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
            arrival_utc=arrival,
            connection_safety=first.connection_safety,
            changes_count=2 + len(ground) // 2,
            hotel_nights_added=1,
            currency=currency,
        )
        if overnight_hotel:
            draft.hotel_changes.append(
                {
                    "hotel_id": None,
                    "name": overnight_hotel["name"],
                    "action": "book_extra_night",
                    "detail": (
                        f"One night at {overnight_hotel['name']} near the airport, "
                        f"{first.option.departure_utc:%d %b}."
                    ),
                    "cost_minor": overnight_hotel["cost_minor"],
                    "currency": overnight_hotel.get("cost_currency", currency),
                    "provenance": overnight_hotel.get("provenance", "UNAVAILABLE"),
                }
            )
            draft.additional_cost_minor += overnight_hotel["cost_minor"]
        # The destination hotel's first night is unusable; _downstream detects
        # the day change and records the shift.
        _downstream(draft, arrival)
        _finalise(draft, original_final, original_duration, ordered, index)
        drafts.append(draft)

    # --- D: later same-day flight, when one exists -----------------------
    #
    # A same-day flight already appears as plan A. Offering a second one is
    # only worth it when it is materially different: at least 90 minutes
    # later and with a better connection buffer. Otherwise the traveller is
    # choosing between two near-identical options.
    if len(same_day_flights) >= 2:
        first = same_day[0]
        later_candidates = [
            leg
            for leg in same_day_flights[1:]
            if leg.option.departure_utc - first.option.departure_utc >= timedelta(minutes=90)
            and leg.buffer_minutes > first.buffer_minutes
        ]
        if later_candidates:
            later = later_candidates[:1]
            arrival = later[-1].option.arrival_utc
            draft = PlanDraft(
                label="D",
                title=f"Later flight to {broken_leg.destination_code}",
                summary=(
                    f"Take {later[-1].option.service_number} later the same day. "
                    "More slack at the connection, later arrival."
                ),
                legs=later,
                replaces_segment_ids=[broken_leg.id],
                keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
                arrival_utc=arrival,
                additional_cost_minor=sum(l.option.cost_minor for l in later),
                connection_safety=later[-1].connection_safety,
                changes_count=1 + len(ground) // 2,
                currency=currency,
            )
            _downstream(draft, arrival)
            _finalise(draft, original_final, original_duration, ordered, index)
            drafts.append(draft)

    # --- Multimodal & Connecting ground alternatives --------------------
    if hub_itineraries:
        # Prioritize ground and multimodal itineraries
        ground_or_multimodal = [
            it for it in hub_itineraries
            if any(l.segment_type in (SegmentType.TRAIN, SegmentType.BUS) for l in it.legs)
        ]
        connecting_candidates = ground_or_multimodal if ground_or_multimodal else (hub_itineraries if not drafts else [])

        seen_modes: set[tuple[str, ...]] = set()
        for offset, itinerary in enumerate(connecting_candidates):
            modes_tuple = tuple(l.segment_type.value for l in itinerary.legs)
            if modes_tuple in seen_modes:
                continue
            seen_modes.add(modes_tuple)

            legs = [
                ReplacementLeg(
                    option=leg,
                    connection_safety=ConnectionSafety(itinerary.connection_safety),
                    buffer_minutes=itinerary.connection_buffer_minutes,
                    required_minutes=itinerary.connection_required_minutes,
                    note=itinerary.note,
                )
                for leg in itinerary.legs
            ]
            arrival = legs[-1].option.arrival_utc
            hub = require_place(itinerary.hub_code)
            first = legs[0].option
            second = legs[-1].option
            modes_desc = " + ".join(l.option.segment_type.value.capitalize() for l in legs)

            transfer_desc = f"Connection at {hub.name} with {itinerary.connection_buffer_minutes} min buffer."
            if first.destination_code != second.origin_code:
                transfer_desc += f" Transfer between {first.destination_code} and {second.origin_code}."

            draft = PlanDraft(
                label=chr(ord("E") + len(seen_modes) - 1),
                title=f"{modes_desc} via {hub.city} to {broken_leg.destination_code}",
                summary=(
                    f"Multimodal route via {hub.city}: take {first.carrier_name} {first.service_number} "
                    f"to {first.destination_code}, then {second.carrier_name} {second.service_number} "
                    f"to {second.destination_code}. {transfer_desc}"
                ),
                legs=legs,
                replaces_segment_ids=[broken_leg.id],
                keeps_original_segment_ids=[s.id for s in ordered if s.id != broken_leg.id],
                arrival_utc=arrival,
                additional_cost_minor=sum(l.option.cost_minor for l in legs),
                connection_safety=ConnectionSafety(itinerary.connection_safety),
                changes_count=len(legs) + len(ground) // 2,
                currency=currency,
                restrictions=[
                    f"Multimodal {modes_desc} via {hub.city}; tickets booked separately per operator."
                ],
            )
            _downstream(draft, arrival)
            _finalise(draft, original_final, original_duration, ordered, index)
            drafts.append(draft)
            if len(seen_modes) >= 2:
                break

    # Not every branch above fires for every disruption, so the fixed A/B/C/D
    # letters can leave gaps. Re-letter the surviving plans in order so the
    # comparison table never shows A, C, D.
    for offset, draft in enumerate(drafts):
        draft.label = chr(ord("A") + offset)

    return drafts


def _finalise(
    draft: PlanDraft,
    original_final_arrival: datetime,
    original_duration: int,
    ordered: list[SegmentSnapshot],
    index: int,
) -> None:
    """Fill in the derived fields once the legs are known."""
    if draft.arrival_utc is None:
        return
    arrival_shift = arrival_shift_minutes(original_final_arrival, draft.arrival_utc)
    draft.total_duration_minutes = max(
        0,
        minutes_between(ordered[0].effective_departure_utc, draft.arrival_utc),
    )
    draft.refund_estimate_minor = _refund_estimate(ordered, index)
    draft.risk_level = _risk_from_shift(arrival_shift, draft.connection_safety)
    draft.hotel_nights_lost = 0 if draft.hotel_nights_added == 0 else 0


def _refund_estimate(ordered: list[SegmentSnapshot], index: int) -> int:
    """Unused-ticket value, only where the original booking was refundable.

    Segment snapshots do not carry fares, so this stays zero unless the
    caller supplies a value; the plan detail screen shows "not estimated"
    rather than a made-up number.
    """
    del ordered, index
    return 0


def _risk_from_shift(shift_minutes: int, safety: ConnectionSafety) -> RiskLevel:
    if safety == ConnectionSafety.BROKEN:
        return RiskLevel.HIGH
    if shift_minutes > 12 * 60 or safety in {ConnectionSafety.AT_RISK, ConnectionSafety.TIGHT}:
        return RiskLevel.HIGH if shift_minutes > 12 * 60 else RiskLevel.MEDIUM
    if shift_minutes > 6 * 60:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def score_drafts(
    drafts: list[PlanDraft], original_duration_minutes: int, original_arrival_utc: datetime
) -> list[ScoredPlan]:
    """Score every draft with the deterministic scorer."""
    scored: list[ScoredPlan] = []
    for draft in drafts:
        if draft.arrival_utc is None:
            continue
        delay = arrival_shift_minutes(original_arrival_utc, draft.arrival_utc)
        worst_buffer = min((l.buffer_minutes for l in draft.legs), default=180)
        result = score_plan(
            ScoreInput(
                plan_id=draft.label,
                label=draft.label,
                arrival_delay_minutes=max(0, delay),
                total_duration_minutes=draft.total_duration_minutes or original_duration_minutes,
                original_duration_minutes=original_duration_minutes,
                additional_cost_minor=draft.additional_cost_minor,
                connection_safety=draft.connection_safety,
                worst_buffer_minutes=worst_buffer,
                changes_count=draft.changes_count,
                hotel_nights_added=draft.hotel_nights_added,
                hotel_nights_lost=draft.hotel_nights_lost,
                ground_transport_ok=draft.ground_transport_ok,
                uses_preferred_carrier=draft.uses_preferred_carrier,
                uses_preferred_cabin=draft.uses_preferred_cabin,
                visa_friction=draft.visa_friction,
                risk_level=draft.risk_level,
                disruption_probability=draft.disruption_probability,
            )
        )
        scored.append(ScoredPlan(draft=draft, score=result))
    return scored


def choose_recommended(scored: list[ScoredPlan]) -> ScoredPlan | None:
    if not scored:
        return None
    best = pick_recommended([s.score for s in scored])
    if best is None:
        return None
    return next(s for s in scored if s.draft.label == best.label)


def describe_arrival_delta(original_arrival_utc: datetime, plan_arrival_utc: datetime) -> str:
    """Copy like "Arrives 1h 20m earlier" or "Arrives 4h 30m later"."""
    delta = arrival_shift_minutes(original_arrival_utc, plan_arrival_utc)
    if delta == 0:
        return "Arrives as originally planned"
    if delta < 0:
        return f"Arrives {format_duration(abs(delta))} earlier"
    return f"Arrives {format_duration(delta)} later"


def money_for(minor: int, currency: str) -> str:
    return str(Money(minor, currency))


def place_name(code: str) -> str:
    return require_place(code).city
