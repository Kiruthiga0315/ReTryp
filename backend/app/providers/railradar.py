"""RailRadar provider for live Indian Railways telemetry.

Connects to https://api.railradar.in/v1 to retrieve real-time train schedules,
live delay tracking, platform numbers, and corridor services between Indian
railway stations for today's date.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings
from ..domain.enums import SegmentType
from ..domain.options import OptionSegment
from ..domain.reference import PLACES

logger = logging.getLogger("retryp.providers.railradar")

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

# Mapping from ReTryp / IATA codes to Indian Railways station codes used by RailRadar
STATION_CODE_MAP: dict[str, str] = {
    # Chennai
    "MAS_RS": "MAS",
    "MAS_BT": "MAS",
    "MAA": "MAS",
    "MAS": "MAS",
    "MS": "MS",
    # Delhi
    "NDLS": "NDLS",
    "DEL_BT": "NDLS",
    "DEL": "NDLS",
    "NZM": "NZM",
    "DLI": "DLI",
    # Hyderabad / Secunderabad
    "SC_RS": "SC",
    "HYD_BT": "SC",
    "HYD": "SC",
    "SC": "SC",
    "HYB": "HYB",
    # Bengaluru
    "SBC_RS": "SBC",
    "BLR_BT": "SBC",
    "BLR": "SBC",
    "SBC": "SBC",
    "YPR": "YPR",
    # Mumbai
    "MMCT": "MMCT",
    "BOM_BT": "MMCT",
    "BOM": "MMCT",
    "CSMT": "CSMT",
    # Kolkata
    "HWH": "HWH",
    "CCU": "HWH",
    "SDAH": "SDAH",
    # Jaipur
    "JP_RS": "JP",
    "JAI": "JP",
    "JP": "JP",
}

# Reverse mapping back to canonical ReTryp railway station code where appropriate
REVERSE_MAP: dict[str, str] = {
    "MAS": "MAS_RS",
    "MS": "MAS_RS",
    "NDLS": "NDLS",
    "NZM": "NDLS",
    "DLI": "NDLS",
    "SC": "SC_RS",
    "HYB": "SC_RS",
    "CHZ": "SC_RS",
    "SBC": "SBC_RS",
    "YPR": "SBC_RS",
    "MMCT": "MMCT",
    "CSMT": "MMCT",
    "HWH": "HWH",
    "SDAH": "HWH",
    "JP": "JP_RS",
}


def _map_to_ir_code(code: str) -> str | None:
    return STATION_CODE_MAP.get(code.upper().strip())


def _map_to_retryp_code(ir_code: str, fallback: str) -> str:
    return REVERSE_MAP.get(ir_code.upper().strip(), fallback)


class RailRadarProvider:
    """Async client for RailRadar Indian Railways REST API."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.effective_railradar_api_key
        self._base_url = settings.railradar_base_url.rstrip("/")
        self._timeout = settings.railradar_timeout_seconds
        self._cache_ttl = settings.provider_cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[OptionSegment]]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search_trains_between(
        self,
        origin_code: str,
        destination_code: str,
        after_utc: datetime,
        *,
        limit: int = 8,
    ) -> list[OptionSegment]:
        """Search live trains between two stations/cities for today's date."""
        if not self.is_configured:
            logger.debug("RailRadar API key not configured; skipping live rail search.")
            return []

        from_ir = _map_to_ir_code(origin_code)
        to_ir = _map_to_ir_code(destination_code)

        if not from_ir or not to_ir or from_ir == to_ir:
            return []

        # Determine target date in Indian Standard Time (IST)
        local_dt = after_utc.astimezone(KOLKATA_TZ)
        date_str = local_dt.strftime("%Y-%m-%d")

        cache_key = f"{from_ir}:{to_ir}:{date_str}"
        now = time.time()
        if cache_key in self._cache:
            cached_at, cached_items = self._cache[cache_key]
            if now - cached_at < self._cache_ttl:
                # Filter cached items to those departing after requested UTC
                return [i for i in cached_items if i.departure_utc > after_utc][:limit]

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ReTryp/1.0 (+https://retryp.example)",
            "Accept": "application/json",
        }

        url = f"{self._base_url}/trains/between/{from_ir}/{to_ir}"
        params = {
            "date": date_str,
            "live": "true",
            "byCity": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code == 401:
                    logger.warning("RailRadar API key unauthorized (401). Check indianrailway key in .env.")
                    return []
                if resp.status_code == 429:
                    logger.warning("RailRadar rate limit reached (429).")
                    return []
                if resp.status_code >= 400:
                    logger.warning("RailRadar API returned HTTP %s for %s->%s: %s", resp.status_code, from_ir, to_ir, resp.text[:200])
                    return []

                data = resp.json()
        except Exception as exc:
            logger.warning("Failed to query RailRadar for %s->%s: %s", from_ir, to_ir, exc)
            return []

        if not data.get("success"):
            logger.debug("RailRadar returned success=false: %s", data.get("error"))
            return []

        train_items = data.get("data", {}).get("trains", [])
        if not train_items:
            logger.debug("No trains found on RailRadar for %s->%s on %s", from_ir, to_ir, date_str)
            return []

        journey_date = local_dt.date()
        results: list[OptionSegment] = []

        for item in train_items:
            try:
                t_info = item.get("train", {})
                f_info = item.get("from", {})
                t_info_to = item.get("to", {})
                live_info = item.get("live", {})

                train_num = str(t_info.get("number", "")).strip()
                train_name = t_info.get("name", "Express").strip()
                train_type = t_info.get("type", "Express").strip()

                if not train_num:
                    continue

                dep_station_code = f_info.get("code", from_ir)
                arr_station_code = t_info_to.get("code", to_ir)

                dep_time_str = f_info.get("departure", "00:00")
                dep_parts = dep_time_str.split(":")
                dep_h, dep_m = int(dep_parts[0]), int(dep_parts[1])
                dep_day_offset = max(0, int(f_info.get("day", 1)) - 1)

                local_dep = datetime(
                    journey_date.year,
                    journey_date.month,
                    journey_date.day,
                    dep_h,
                    dep_m,
                    0,
                    tzinfo=KOLKATA_TZ,
                ) + timedelta(days=dep_day_offset)

                dep_utc = local_dep.astimezone(timezone.utc)
                if dep_utc <= after_utc:
                    continue

                duration_min = int(item.get("duration", 0))
                if duration_min <= 0:
                    duration_min = 120  # fallback 2 hours

                arr_utc = dep_utc + timedelta(minutes=duration_min)
                distance_km = float(item.get("distance", 0.0))

                # Fare calculation: estimated ₹2.0/km (3AC planning estimate)
                if distance_km > 0:
                    fare_inr = max(500, int(round(distance_km * 2.0)))
                else:
                    fare_inr = 1500
                cost_minor = fare_inr * 100

                # Live status details
                live_type = live_info.get("type", "scheduled")
                delay_min = int(live_info.get("delayMinutes", 0))
                platform = live_info.get("platform")

                note_parts = [
                    f"RailRadar Live: Indian Railways #{train_num} {train_name} ({train_type}).",
                    f"Status: {live_type}."
                ]
                if delay_min > 0:
                    note_parts.append(f"Running late by {delay_min}m.")
                elif delay_min == 0 and live_type != "not-running":
                    note_parts.append("Running on time.")
                if platform:
                    note_parts.append(f"Departs Platform {platform}.")
                note_parts.append("Real-time telemetry via api.railradar.in.")

                origin_mapped = _map_to_retryp_code(dep_station_code, origin_code)
                dest_mapped = _map_to_retryp_code(arr_station_code, destination_code)

                segment = OptionSegment(
                    key=f"railradar-{train_num}-{journey_date.isoformat()}-{dep_station_code}-{arr_station_code}",
                    segment_type=SegmentType.TRAIN,
                    carrier_code="IR",
                    service_number=f"{train_num} {train_name}",
                    origin_code=origin_mapped,
                    destination_code=dest_mapped,
                    departure_utc=dep_utc,
                    arrival_utc=arr_utc,
                    cost_minor=cost_minor,
                    currency="INR",
                    refundable=False,
                    distance_km=round(distance_km, 1) if distance_km > 0 else 500.0,
                    note=" ".join(note_parts),
                    provenance="LIVE",
                )
                results.append(segment)
            except Exception as parse_exc:
                logger.debug("Failed to parse train item: %s", parse_exc)
                continue

        results.sort(key=lambda o: o.departure_utc)
        self._cache[cache_key] = (now, results)
        return results[:limit]
