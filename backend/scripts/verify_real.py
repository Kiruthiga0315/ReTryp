"""Verify a recovery cycle end to end against the configured providers.

Run from the backend directory:

    .venv/bin/python scripts/verify_real.py

The script builds a real two-leg journey (MAA-FRA-BER) from whatever the
configured flight provider and the downloaded rail timetable actually offer,
injects a 225 minute delay on the long-haul leg, and prints the resulting
impact, constraints and plans. It writes to a temporary database and makes no
change to the development database.

This is a smoke check, not a test: it talks to the network when a provider key
is configured, so its output depends on live data. The deterministic version of
the same pipeline is in ``tests/``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import date

db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["BOOTSTRAP_PASSWORD"] = "Retryp-Verify-2026"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bootstrap  # noqa: E402
from app.agents import pipeline  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.domain import journey as builder  # noqa: E402
from app.domain.enums import DisruptionKind  # noqa: E402
from app.llm.router import build_router  # noqa: E402
from app.routers.journey import (  # noqa: E402
    _attach_hotel_and_transfer,
    _persist_trip,
    _resolve_segments,
)
from app.schemas import BuildJourneyRequest, JourneySegmentSelection  # noqa: E402

DAY = "2026-09-28"


async def _first_option(origin: str, destination: str):
    leg = await builder.search_options_live(origin, destination, on_date=date.fromisoformat(DAY))
    return next(iter(leg.options), None)


async def main() -> None:
    Base.metadata.create_all(engine)
    bootstrap.main([])

    settings = get_settings()
    session = SessionLocal()
    try:
        actor = bootstrap.create_accounts(session, "Retryp-Verify-2026")[2]
        session.commit()

        long_haul = await _first_option("MAA", "FRA")
        connection = await _first_option("FRA", "BER")
        if long_haul is None or connection is None:
            print(
                "No schedule for MAA-FRA-BER from the configured provider. "
                "Set FLIGHT_PROVIDER and its API key in .env, then retry."
            )
            return

        payload = BuildJourneyRequest(
            name="Verification journey",
            reason="business",
            origin="MAA",
            destination="BER",
            date=DAY,
            segments=[
                JourneySegmentSelection(
                    service_key=long_haul.key,
                    origin="MAA",
                    destination="FRA",
                    date=DAY,
                    mode=long_haul.segment_type.value,
                ),
                JourneySegmentSelection(
                    service_key=connection.key,
                    origin="FRA",
                    destination="BER",
                    date=DAY,
                    mode=connection.segment_type.value,
                ),
            ],
        )
        resolved = await _resolve_segments(payload)
        trip = _persist_trip(session, actor, payload, resolved)
        await _attach_hotel_and_transfer(session, trip, resolved)
        pipeline.ensure_baseline(session, trip=trip)
        session.commit()

        print("trip:", trip.reference, "|", trip.name)
        for seg in trip.segments:
            print(
                f"  {seg.service_number:9} {seg.origin_code:6}->{seg.destination_code:6} "
                f"{seg.scheduled_departure_utc:%d %b %H:%M}Z prov={seg.provenance} "
                f"src={seg.source}"
            )

        long_haul_row = next(x for x in trip.segments if x.origin_code == "MAA")
        disruption = pipeline.detect_disruption(
            session,
            trip=trip,
            kind=DisruptionKind.FLIGHT_DELAY,
            segment_id=long_haul_row.id,
            delay_minutes=225,
            detail="Injected delay for verification",
            provenance="SIMULATED",
            source="verify_real",
        )
        session.commit()

        impact = pipeline.assess_impact(session, trip=trip, disruption=disruption)
        print("\nimpact:", impact["severity"], "| connection:", impact["connection_safety"])
        print("  ", impact["summary"])
        for item in impact["items"]:
            flag = "action" if item["requires_action"] else "note"
            print(f"   [{flag}] {item['kind']}: {item['title']}")
        for conn in impact["connections"]:
            print(
                f"   connection {conn['airport_code']}: feasible={conn['feasible']} "
                f"safety={conn['safety']} buffer={conn['buffer_minutes']}m "
                f"required={conn['required_minutes']}m"
            )

        constraints = pipeline.build_constraints(session, trip=trip)
        plans = asyncio.run(
            pipeline.generate_plans(
                session,
                trip=trip,
                disruption=disruption,
                constraints=constraints,
                settings=settings,
                llm=build_router(settings),
            )
        )
        session.commit()

        print(f"\nplans generated: {len(plans)}")
        for plan in sorted(plans, key=lambda p: p.score, reverse=True):
            print(
                f"  [{plan.label}] {plan.title} | score={plan.score:.3f} "
                f"risk={plan.risk_level} extra={plan.currency}"
                f"{plan.additional_cost_minor / 100:.0f} "
                f"connection={plan.connection_safety} prov={plan.provenance}"
            )
            for seg in plan.segments:
                origin = seg.get("origin_code") or seg.get("origin", {}).get("code")
                dest = seg.get("destination_code") or seg.get("destination", {}).get("code")
                print(
                    f"      {seg.get('segment_type', '?'):6} "
                    f"{seg.get('service_number', '?'):9} "
                    f"{str(origin):7}->{str(dest):7} prov={seg.get('provenance')} "
                    f"src={seg.get('source')}"
                )
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
