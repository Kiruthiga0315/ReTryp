"""Real bus timetables, supporting curated intercity bus feeds.

The artifact is read from ``app/data/indian_bus_services.json``.
It carries *scheduled* services only. There is no live running status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .enums import SegmentType
from .options import OptionSegment
from .reference import PLACES, BUS_OPERATORS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True, slots=True)
class BusService:
    origin: str
    destination: str
    operator: str
    departure_local: str
    duration_min: int
    dates: frozenset[str]
    trip_id: str
    fare_minor: int
    tz_name: str = "Asia/Kolkata"
    currency: str = "INR"


def _load() -> tuple[list[BusService], dict]:
    path = DATA_DIR / "indian_bus_services.json"
    if not path.exists():
        return [], {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], {}

    tz_name = payload.get("timezone", "Asia/Kolkata")
    currency = payload.get("currency", "INR")
    services = [
        BusService(
            origin=s["origin"],
            destination=s["destination"],
            operator=s.get("operator", "Bus"),
            departure_local=s["departure"],
            duration_min=s["duration_min"],
            dates=frozenset(s.get("dates", [])),
            trip_id=s.get("trip_id", "BUS"),
            fare_minor=s.get("fare_minor", 100000),
            tz_name=tz_name,
            currency=currency,
        )
        for s in payload.get("services", [])
    ]
    meta = {k: v for k, v in payload.items() if k != "services"}
    return services, meta


SERVICES, META = _load()
BUS_LOADED = bool(SERVICES)


def _parse_local(hhmmss: str) -> tuple[int, int, int]:
    parts = hhmmss.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2]) if len(parts) > 2 else 0
    return hours, minutes, seconds


def _operator_code(operator_name: str) -> str:
    for code in ("APSRTC", "TNSTC", "KSRTC", "UPSRTC", "SRS", "ORANGE"):
        if code in operator_name.upper():
            return code
    return "BUS"


def bus_options(
    origin: str,
    destination: str,
    after_utc: datetime,
    *,
    limit: int = 8,
) -> list[OptionSegment]:
    """Scheduled bus services between two stations/terminals, departing after after_utc."""
    if after_utc.tzinfo is None:
        after_utc = after_utc.replace(tzinfo=timezone.utc)

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

            dep_utc = local_dep.astimezone(timezone.utc)
            if dep_utc <= after_utc:
                continue

            arr_utc = dep_utc + timedelta(minutes=svc.duration_min)
            carrier_code = _operator_code(svc.operator)

            out.append(
                OptionSegment(
                    key=f"bus-{svc.trip_id}-{base_day.isoformat()}-{svc.departure_local}",
                    segment_type=SegmentType.BUS,
                    carrier_code=carrier_code,
                    service_number=svc.operator,
                    origin_code=origin,
                    destination_code=destination,
                    departure_utc=dep_utc,
                    arrival_utc=arr_utc,
                    cost_minor=svc.fare_minor,
                    currency=svc.currency,
                    refundable=False,
                    note=f"Real-time schedule ({svc.operator}).",
                    provenance="LIVE",
                )
            )

    out.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return out[:limit]


def bus_options_between(
    origin_city: str,
    destination_city: str,
    after_utc: datetime,
    *,
    limit: int = 8,
) -> list[OptionSegment]:
    """Bus options between two cities. First attempts to fetch live global data via Apify,
    falling back to curated schedules if unavailable.
    """
    import logging
    import httpx
    logger = logging.getLogger("retryp.domain.bus")
    
    results: list[OptionSegment] = []
    seen_keys: set[str] = set()

    # 1. Attempt Live Apify Fetch
    import os
    APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
    APIFY_ACTOR_URL = f"https://api.apify.com/v2/actors/jungle_synthesizer~12go-asia-multimodal-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    
    tz = ZoneInfo("Asia/Kolkata")
    local_date = after_utc.astimezone(tz).date().isoformat()

    # Convert market codes to city names for the Apify scraper (12Go Asia expects city names)
    origin_name = next((p.city for p in PLACES.values() if p.market == origin_city), origin_city)
    dest_name = next((p.city for p in PLACES.values() if p.market == destination_city), destination_city)
    
    payload = {
        "searches": [{"origin": origin_name, "destination": dest_name, "date": local_date}],
        "sp_intended_usage": "research",
        "sp_improvement_suggestions": "none",
        "currency": "INR"
    }
    
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(APIFY_ACTOR_URL, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                
                for item in items:
                    mode = str(item.get("mode", "")).lower()
                    if mode not in ["bus", "charter", "minivan"]:
                        continue
                        
                    dep_time = item.get("departure_time")
                    if not dep_time or dep_time == "--:--":
                        continue
                        
                    # parse HH:MM
                    try:
                        hh, mm = map(int, dep_time.split(":")[:2])
                        dep_dt = datetime.fromisoformat(f"{item.get('travel_date')}T{hh:02d}:{mm:02d}:00").replace(tzinfo=tz)
                        dep_utc = dep_dt.astimezone(timezone.utc)
                    except Exception:
                        continue
                        
                    if dep_utc <= after_utc:
                        continue
                        
                    duration = item.get("duration_minutes", 0)
                    arr_utc = dep_utc + timedelta(minutes=duration)
                    
                    price = item.get("price", 0)
                    cost_minor = int(float(price) * 100) if price else 150000
                    
                    operator = item.get("operator", "Bus Operator")
                    
                    opt = OptionSegment(
                        key=f"apify-{item.get('trip_id')}",
                        segment_type=SegmentType.BUS,
                        carrier_code=_operator_code(operator),
                        service_number=operator,
                        origin_code=item.get("origin_city", origin_city)[:5].upper(),
                        destination_code=item.get("destination_city", destination_city)[:5].upper(),
                        departure_utc=dep_utc,
                        arrival_utc=arr_utc,
                        cost_minor=cost_minor,
                        currency="INR",
                        refundable=False,
                        note=f"Live availability via 12Go ({item.get('vehicle_class', operator)}).",
                        provenance="LIVE",
                    )
                    
                    if opt.key not in seen_keys:
                        seen_keys.add(opt.key)
                        results.append(opt)
    except Exception as e:
        logger.warning(f"Apify live bus fetch failed: {e}. Falling back to curated.")
        
    # If we got live results, return them
    if results:
        results.sort(key=lambda o: o.departure_utc)
        return results[:limit]

    # 2. Fallback to Curated
    for svc in SERVICES:
        orig_place = PLACES.get(svc.origin)
        dest_place = PLACES.get(svc.destination)
        if not orig_place or not dest_place:
            continue

        orig_matches = orig_place.market == origin_city or svc.origin == origin_city
        dest_matches = dest_place.market == destination_city or svc.destination == destination_city

        if not (orig_matches and dest_matches):
            continue

        for opt in bus_options(
            svc.origin,
            svc.destination,
            after_utc,
            limit=limit,
        ):
            if opt.key not in seen_keys:
                seen_keys.add(opt.key)
                results.append(opt)

    results.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return results[:limit]
