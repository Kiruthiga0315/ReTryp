"""Real rail timetables, supporting multiple feeds (German DELFI and Indian Railways).

The artifacts are read from ``app/data/rail_services.json`` and
``app/data/indian_rail_services.json``. They carry *scheduled* services only.
There is no live running status, and the UI must never imply there is: the note
on every option says so.

Local times are converted to UTC using each feed's timezone.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .enums import SegmentType
from .options import OptionSegment
from .reference import PLACES

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ESTIMATED_FARE_PER_KM_EUR = 0.15
ESTIMATED_FARE_PER_KM_INR = 2.0


@dataclass(frozen=True, slots=True)
class RailService:
    origin: str
    destination: str
    service: str
    operator: str
    departure_local: str
    duration_min: int
    dates: frozenset[str]
    trip_id: str
    tz_name: str = "Europe/Berlin"
    currency: str = "EUR"
    fare_minor: int | None = None


def _load() -> tuple[list[RailService], dict]:
    services: list[RailService] = []
    meta: dict = {}

    files = [
        ("rail_services.json", "Europe/Berlin", "EUR"),
    ]

    for filename, default_tz, default_currency in files:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        feed_tz = payload.get("timezone", default_tz)
        feed_currency = payload.get("currency", default_currency)

        for s in payload.get("services", []):
            services.append(
                RailService(
                    origin=s["origin"],
                    destination=s["destination"],
                    service=s["service"],
                    operator=s.get("operator", "Rail"),
                    departure_local=s["departure"],
                    duration_min=s["duration_min"],
                    dates=frozenset(s.get("dates", [])),
                    trip_id=s.get("trip_id", s["service"]),
                    tz_name=feed_tz,
                    currency=feed_currency,
                    fare_minor=s.get("fare_minor"),
                )
            )
        if not meta:
            meta = {k: v for k, v in payload.items() if k != "services"}

    return services, meta


SERVICES, META = _load()
RAIL_LOADED = bool(SERVICES)


def _parse_local(hhmmss: str) -> tuple[int, int, int]:
    parts = hhmmss.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2]) if len(parts) > 2 else 0
    return hours, minutes, seconds


def _station_distance_km(origin: str, destination: str) -> float:
    a = PLACES.get(origin)
    b = PLACES.get(destination)
    if a is None or b is None:
        return 0.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _get_rail_pairs() -> set[tuple[str, str]]:
    pairs = set()
    for s in SERVICES:
        pairs.add((s.origin, s.destination))
    pairs.update({
        ("FRA_AIR", "BER"),
        ("FRA", "BER"),
        ("FRA_AIR", "BER_AIR"),
        ("FRA", "BER_AIR"),
    })
    return pairs


RAIL_PAIRS = _get_rail_pairs()


def rail_options(
    origin: str,
    destination: str,
    after_utc: datetime,
    *,
    limit: int = 8,
    earliest_local_hour: int = 0,
) -> list[OptionSegment]:
    """Scheduled rail services between two stations, departing after after_utc."""
    if after_utc.tzinfo is None:
        after_utc = after_utc.replace(tzinfo=timezone.utc)

    distance = _station_distance_km(origin, destination)
    out: list[OptionSegment] = []

    for svc in SERVICES:
        if svc.origin != origin or svc.destination != destination:
            continue

        tz = ZoneInfo(svc.tz_name)
        local_after = after_utc.astimezone(tz)
        local_date = local_after.date()

        date_candidates = [
            local_date - timedelta(days=1),
            local_date,
            local_date + timedelta(days=1),
        ]

        for check_date in date_candidates:
            if check_date.isoformat() not in svc.dates:
                continue

            hours, minutes, seconds = _parse_local(svc.departure_local)
            day_offset, norm_hours = divmod(hours, 24)
            base_day = check_date + timedelta(days=day_offset)

            try:
                local_dep = datetime(
                    base_day.year, base_day.month, base_day.day, norm_hours, minutes, seconds, tzinfo=tz
                )
            except (ValueError, OverflowError):
                continue

            if local_dep.hour < earliest_local_hour:
                continue

            dep_utc = local_dep.astimezone(timezone.utc)
            if dep_utc <= after_utc:
                continue

            arr_utc = dep_utc + timedelta(minutes=svc.duration_min)

            if svc.fare_minor is not None:
                cost_minor = svc.fare_minor
            elif svc.currency == "INR":
                cost_minor = int(round(distance * ESTIMATED_FARE_PER_KM_INR * 100))
            else:
                cost_minor = int(round(distance * ESTIMATED_FARE_PER_KM_EUR * 100))

            carrier_code = svc.service.split()[0] if svc.service else "IR" if svc.currency == "INR" else "DB"
            if carrier_code not in ("DB", "ICE", "IR", "SNCF"):
                carrier_code = "IR" if svc.currency == "INR" else "DB"

            out.append(
                OptionSegment(
                    key=f"rail-{svc.trip_id}-{base_day.isoformat()}-{svc.departure_local}",
                    segment_type=SegmentType.TRAIN,
                    carrier_code=carrier_code,
                    service_number=svc.service,
                    origin_code=origin,
                    destination_code=destination,
                    departure_utc=dep_utc,
                    arrival_utc=arr_utc,
                    cost_minor=cost_minor,
                    currency=svc.currency,
                    refundable=False,
                    distance_km=round(distance, 1),
                    note=(
                        f"Scheduled {svc.operator} timetable data. "
                        "Not live running status. Fare is an estimate, not a booking quote."
                    ),
                    provenance="REFERENCE",
                )
            )

    out.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return out[:limit]


def rail_options_between(
    origin_city: str,
    destination_city: str,
    after_utc: datetime,
    *,
    limit: int = 8,
    earliest_local_hour: int = 0,
) -> list[OptionSegment]:
    """Rail options between two cities, searching across matching stations."""
    results: list[OptionSegment] = []
    seen_keys: set[str] = set()

    for origin, destination in RAIL_PAIRS:
        orig_place = PLACES.get(origin)
        dest_place = PLACES.get(destination)
        if not orig_place or not dest_place:
            continue

        orig_matches = orig_place.market == origin_city or origin == origin_city
        dest_matches = dest_place.market == destination_city or destination == destination_city

        if not (orig_matches and dest_matches):
            continue

        for opt in rail_options(
            origin,
            destination,
            after_utc,
            limit=limit,
            earliest_local_hour=earliest_local_hour,
        ):
            if opt.key not in seen_keys:
                seen_keys.add(opt.key)
                results.append(opt)

    results.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return results[:limit]


def rail_services_meta() -> dict:
    return {
        "loaded": RAIL_LOADED,
        "source": "DELFI e.V. / GTFS.de",
        "source_url": META.get("source_url"),
        "feed_version": META.get("feed_version"),
        "fetched_at": META.get("fetched_at"),
        "valid_from": META.get("valid_from"),
        "valid_to": META.get("valid_to"),
        "note": "Scheduled timetable data only; there is no live train running status.",
    }


def rail_departure_window(day: date) -> tuple[str, str] | None:
    start = META.get("valid_from")
    end = META.get("valid_to")
    if not start or not end:
        return None
    return start, end
