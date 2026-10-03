"""A bookable transport option.

This is the currency the provider layer hands to the recovery planner. Any
provider produces these, so the planner never knows where an option came
from.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import SegmentType
from .reference import AIRLINES, BUS_OPERATORS, RAIL_OPERATORS


@dataclass(frozen=True, slots=True)
class OptionSegment:
    key: str
    segment_type: SegmentType
    carrier_code: str
    service_number: str
    origin_code: str
    destination_code: str
    departure_utc: object  # datetime; kept loose so the module stays import-light
    arrival_utc: object
    cost_minor: int
    currency: str
    refundable: bool
    cabin: str | None = None
    fare_class: str | None = None
    platform: str | None = None
    terminal: str | None = None
    gate: str | None = None
    booking_reference: str | None = None
    distance_km: float | None = None
    note: str = ""
    provenance: str = "UNAVAILABLE"
    # The operating carrier behind a codeshare, when the provider publishes the
    # marketing number. Used only to collapse duplicate rows in a search.
    operating_carrier: str | None = None
    operating_number: str | None = None
    # A provider row that describes a journey already finished is a stale
    # schedule reading, not a bookable service, so its badge is not live.
    stale_when_landed: bool = False

    @property
    def carrier_name(self) -> str:
        if self.segment_type == SegmentType.FLIGHT:
            return AIRLINES.get(self.carrier_code, self.carrier_code)
        if self.segment_type == SegmentType.BUS:
            return BUS_OPERATORS.get(self.carrier_code, self.carrier_code)
        return RAIL_OPERATORS.get(self.carrier_code, self.carrier_code)

    @property
    def duration_minutes(self) -> int:
        return int((self.arrival_utc - self.departure_utc).total_seconds() // 60)  # type: ignore[operator]
