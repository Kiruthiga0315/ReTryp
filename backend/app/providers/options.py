"""The recovery-alternative search, real sources first.

Three providers are combined:

* **Flights** come from the flight provider.
* **Rail** comes from the DELFI / GTFS.de and Indian Railways timetables.
* **Buses** come from curated intercity bus schedules.

Everything returned carries ``provenance`` and a ``note`` naming its source, so
the planner and the UI never have to guess where an option came from.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..domain import bus, rail
from ..domain.options import OptionSegment
from .flights import build_flight_provider


async def search_recovery_options(
    settings: Settings,
    *,
    origin: str,
    destination: str,
    depart_after_utc: datetime,
) -> list[OptionSegment]:
    """Every option on a leg, flights, rail and bus, real sources first."""
    provider = build_flight_provider(settings)
    options = list(
        await provider.search(
            origin=origin,
            destination=destination,
            depart_after_utc=depart_after_utc,
        )
    )

    # 1. Live Indian Railways telemetry via RailRadar API if configured
    if settings.railradar_enabled:
        from .railradar import RailRadarProvider
        rr_provider = RailRadarProvider(settings)
        try:
            live_trains = await rr_provider.search_trains_between(
                origin, destination, depart_after_utc
            )
            options.extend(live_trains)
        except Exception:
            pass

    # 2. Timetable Rail (German DELFI and Indian Railways timetable)
    if rail.RAIL_LOADED:
        timetable_trains = rail.rail_options_between(origin, destination, depart_after_utc)
        live_numbers = {
            o.service_number.split()[0]
            for o in options
            if o.segment_type.value == "train" and o.provenance == "LIVE"
        }
        for tt in timetable_trains:
            tt_num = tt.service_number.split()[0]
            if tt_num not in live_numbers:
                options.append(tt)

    # 3. Intercity Buses (curated state & private operators)
    if bus.BUS_LOADED:
        options = [o for o in options if o.segment_type.value != "bus"]
        options += bus.bus_options_between(origin, destination, depart_after_utc)

    options.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return options
