"""Connectable itineraries: stitch two real legs through a hub.

This module turns pairs of real legs (rail, bus, multimodal) into concrete,
timed itineraries the traveller can actually take: leg one into a hub,
a graded connection at the hub, leg two out to the destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import graph, rail
from .connections import assess_connection
from .options import OptionSegment
from .reference import PLACES, require_place
from .timeutil import zone_for

MAX_HUBS = 8
PER_HUB = 2
SEARCH_DAYS = 2


@dataclass(slots=True)
class Itinerary:
    hub_code: str
    legs: list[OptionSegment]
    connection_buffer_minutes: int
    connection_required_minutes: int
    connection_safety: str
    provenance: str
    note: str = ""

    @property
    def departure_utc(self) -> datetime:
        return self.legs[0].departure_utc

    @property
    def arrival_utc(self) -> datetime:
        return self.legs[-1].arrival_utc

    @property
    def duration_minutes(self) -> int:
        return int((self.arrival_utc - self.departure_utc).total_seconds() // 60)

    @property
    def cost_minor(self) -> int:
        return sum(leg.cost_minor for leg in self.legs)

    @property
    def currency(self) -> str:
        return self.legs[0].currency

    @property
    def key(self) -> str:
        return "+".join(leg.key for leg in self.legs)


def _weakest(provenances: list[str]) -> str:
    order = {"LIVE": 0, "CACHED": 1, "REFERENCE": 2, "SIMULATED": 3}
    return max(provenances, key=lambda p: order.get(p, 4))


def _legs_between(
    origin: str,
    destination: str,
    window_start: datetime,
    window_end: datetime,
) -> list[OptionSegment]:
    """Real services for one hop (rail or bus), inside a window."""
    legs: list[OptionSegment] = []
    if rail.RAIL_LOADED:
        legs.extend(rail.rail_options_between(origin, destination, window_start, limit=6))
    from . import bus
    if bus.BUS_LOADED:
        legs.extend(bus.bus_options_between(origin, destination, window_start, limit=6))

    filtered = [o for o in legs if o.departure_utc < window_end]
    filtered.sort(key=lambda o: o.departure_utc)
    return filtered


def hub_candidates(origin: str, destination: str, *, limit: int = MAX_HUBS) -> list[str]:
    """Hubs that can bridge a pair: reachable from origin's market and reaching destination's market."""
    try:
        target_market = require_place(destination).market
        origin_market = require_place(origin).market
    except KeyError:
        return []

    origin_nodes = {c for c, p in PLACES.items() if p.market == origin_market}
    origin_nodes.add(origin)
    target_nodes = {c for c, p in PLACES.items() if p.market == target_market}
    target_nodes.add(destination)

    hubs: set[str] = set()

    for orig_node in origin_nodes:
        for candidate in graph.neighbours(orig_node):
            cand_place = PLACES.get(candidate)
            if not cand_place or cand_place.market in {origin_market, target_market}:
                continue
            cand_nodes = {c for c, p in PLACES.items() if p.market == cand_place.market}
            cand_nodes.add(candidate)
            for cn in cand_nodes:
                if any(t in graph.neighbours(cn) for t in target_nodes):
                    hubs.add(candidate)
                    break

    orig_country = PLACES.get(origin).country if origin in PLACES else ""

    def _hub_rank(code: str) -> tuple[int, int, int]:
        p = PLACES.get(code)
        is_same_country = 1 if p and p.country == orig_country else 0
        is_ground = 1 if p and p.kind in ("rail", "bus") else 0
        return (-is_same_country, -is_ground, -graph.degree(code))

    hub_list = list(hubs)
    hub_list.sort(key=_hub_rank)
    return hub_list[:limit]


def _stitch(
    hub: str,
    first_legs: list[OptionSegment],
    second_legs: list[OptionSegment],
    *,
    require_immigration_at_hub: bool,
    per_hub: int,
) -> list[Itinerary]:
    """Time every feasible pairing of an inbound and an onward leg at a hub."""
    found: list[Itinerary] = []
    for inbound in first_legs:
        for onward in second_legs:
            if onward.departure_utc <= inbound.arrival_utc:
                continue
            assessment = assess_connection(
                airport_code=hub,
                arriving_at_utc=inbound.arrival_utc,
                departing_at_utc=onward.departure_utc,
                requires_immigration=require_immigration_at_hub,
                from_place=inbound.destination_code,
                to_place=onward.origin_code,
            )
            if not assessment.feasible:
                continue
            found.append(
                Itinerary(
                    hub_code=hub,
                    legs=[inbound, onward],
                    connection_buffer_minutes=assessment.buffer_minutes,
                    connection_required_minutes=assessment.required_minutes,
                    connection_safety=assessment.safety.value,
                    provenance=_weakest([inbound.provenance, onward.provenance]),
                    note=assessment.note,
                )
            )
    found.sort(key=lambda it: (it.arrival_utc, it.cost_minor))
    return found[:per_hub]


def connectable_itineraries(
    origin: str,
    destination: str,
    day: date,
    *,
    max_hubs: int = MAX_HUBS,
    per_hub: int = PER_HUB,
    require_immigration_at_hub: bool = False,
) -> list[Itinerary]:
    """Timed two-leg itineraries through a hub for a local departure day."""
    origin_market = require_place(origin).market
    destination_market = require_place(destination).market
    if origin_market == destination_market:
        return []

    tz = zone_for(origin)
    window_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    window_end = window_start + timedelta(days=SEARCH_DAYS)

    itineraries: list[Itinerary] = []
    for hub in hub_candidates(origin, destination, limit=max_hubs):
        hub_market = require_place(hub).market
        first_legs = _legs_between(origin_market, hub_market, window_start, window_end)
        if not first_legs:
            continue
        second_legs = _legs_between(hub_market, destination_market, window_start, window_end)
        if not second_legs:
            continue
        itineraries.extend(
            _stitch(
                hub,
                first_legs,
                second_legs,
                require_immigration_at_hub=require_immigration_at_hub,
                per_hub=per_hub,
            )
        )

    seen_keys: set[str] = set()
    unique: list[Itinerary] = []
    for it in itineraries:
        if it.key not in seen_keys:
            seen_keys.add(it.key)
            unique.append(it)

    unique.sort(key=lambda it: (it.arrival_utc, it.cost_minor))
    return unique


def flight_itineraries(
    origin: str,
    destination: str,
    hub: str,
    first_legs: list[OptionSegment],
    second_legs: list[OptionSegment],
    *,
    per_hub: int = PER_HUB,
    require_immigration_at_hub: bool = True,
) -> list[Itinerary]:
    if not first_legs or not second_legs:
        return []
    first = [o for o in first_legs if o.origin_code == origin and o.destination_code == hub]
    second = [o for o in second_legs if o.origin_code == hub and o.destination_code == destination]
    if not first or not second:
        return []
    first.sort(key=lambda o: o.departure_utc)
    second.sort(key=lambda o: o.departure_utc)
    return _stitch(
        hub,
        first,
        second,
        require_immigration_at_hub=require_immigration_at_hub,
        per_hub=per_hub,
    )


def itinerary_payload(itinerary: Itinerary) -> dict:
    from .timeutil import format_duration, format_local

    legs = []
    for leg in itinerary.legs:
        legs.append(
            {
                "key": leg.key,
                "mode": leg.segment_type.value,
                "carrier_code": leg.carrier_code,
                "carrier_name": leg.carrier_name,
                "service_number": leg.service_number,
                "origin_code": leg.origin_code,
                "destination_code": leg.destination_code,
                "departure_local": format_local(leg.departure_utc, leg.origin_code, with_date=True),
                "arrival_local": format_local(leg.arrival_utc, leg.destination_code, with_date=True),
                "duration_minutes": leg.duration_minutes,
                "cost_minor": leg.cost_minor,
                "currency": leg.currency,
                "provenance": leg.provenance,
                "note": leg.note,
            }
        )
    return {
        "key": itinerary.key,
        "hub_code": itinerary.hub_code,
        "hub_name": PLACES[itinerary.hub_code].name,
        "hub_city": PLACES[itinerary.hub_code].city,
        "hub_country": PLACES[itinerary.hub_code].country,
        "hub_tz": PLACES[itinerary.hub_code].tz,
        "legs": legs,
        "departure_local": format_local(itinerary.departure_utc, itinerary.legs[0].origin_code, with_date=True),
        "arrival_local": format_local(itinerary.arrival_utc, itinerary.legs[-1].destination_code, with_date=True),
        "duration_minutes": itinerary.duration_minutes,
        "duration_display": format_duration(itinerary.duration_minutes),
        "cost_minor": itinerary.cost_minor,
        "currency": itinerary.currency,
        "connection_buffer_minutes": itinerary.connection_buffer_minutes,
        "connection_required_minutes": itinerary.connection_required_minutes,
        "connection_safety": itinerary.connection_safety,
        "provenance": itinerary.provenance,
        "note": itinerary.note,
    }
