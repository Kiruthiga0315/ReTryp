"""Timezone and duration helpers.

Rule: the database always stores UTC. Anything shown to a human is converted
to the local zone of the relevant airport or station, with the zone label
attached ("14:30 IST"). ``zoneinfo`` handles DST from the IANA database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .reference import require_place

ZONE_ABBREVIATIONS: dict[str, str] = {
    "Asia/Kolkata": "IST",
    "Europe/Berlin": "CET",
    "Europe/Paris": "CET",
    "Europe/Amsterdam": "CET",
    "Europe/Zurich": "CET",
    "Europe/Vienna": "CET",
    "Europe/London": "UK",
    "Europe/Istanbul": "TRT",
    "Asia/Dubai": "GST",
    "UTC": "UTC",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to a naive value, or convert an aware value to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def zone_for(place_code: str) -> ZoneInfo:
    return ZoneInfo(require_place(place_code).tz)


def zone_label(tz_name: str, moment: datetime | None = None) -> str:
    """Short human zone label, DST aware.

    Prefers the common abbreviation ("IST", "CET") and switches to the
    summer form ("CEST", "BST") when the offset says so.
    """
    ref = ensure_utc(moment) if moment else utcnow()
    base = ZONE_ABBREVIATIONS.get(tz_name)
    if base is not None:
        tz = ZoneInfo(tz_name)
        offset = tz.utcoffset(ref)
        if base == "CET" and offset == timedelta(hours=2):
            return "CEST"
        if base == "UK" and offset == timedelta(hours=1):
            return "BST"
        return base
    tz = ZoneInfo(tz_name)
    return tz.tzname(ref) or "UTC"


def to_local(value: datetime, place_code: str) -> datetime:
    return ensure_utc(value).astimezone(zone_for(place_code))


def format_local(value: datetime, place_code: str, *, with_date: bool = False) -> str:
    """Format a UTC instant as local time with its zone label."""
    local = to_local(value, place_code)
    label = zone_label(require_place(place_code).tz, value)
    if with_date:
        return f"{local:%d %b %Y %H:%M} {label}"
    return f"{local:%H:%M} {label}"


def minutes_between(start: datetime, end: datetime) -> int:
    return int((ensure_utc(end) - ensure_utc(start)).total_seconds() // 60)


def format_duration(minutes: int) -> str:
    """Human duration: "3h 45m", "45m", "2d 4h"."""
    negative = minutes < 0
    minutes = abs(int(minutes))
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        text = f"{days}d {hours}h"
    elif hours:
        text = f"{hours}h {mins:02d}m" if mins else f"{hours}h"
    else:
        text = f"{mins}m"
    return f"-{text}" if negative else text


def format_signed_duration(minutes: int) -> str:
    """Signed duration for copy like "arrives 1h 20m later"."""
    if minutes == 0:
        return "on schedule"
    direction = "later" if minutes > 0 else "earlier"
    return f"{format_duration(abs(minutes))} {direction}"


def is_dst_transition_day(place_code: str, moment: datetime) -> bool:
    """True when the local calendar day contains a DST offset change."""
    tz = zone_for(place_code)
    local = ensure_utc(moment).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    offsets = {(start + timedelta(hours=h)).utcoffset() for h in range(0, 25)}
    return len(offsets) > 1
