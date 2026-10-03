"""Autonomous Trip Recovery Agent demo: Chennai to Delhi flight cancellation.

Tests the full recovery pipeline with live RailRadar Indian Railways,
AeroDataBox flights, and intercity buses.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bootstrap
from app.agents import pipeline
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.domain import journey as builder
from app.domain.enums import DisruptionKind, SegmentStatus
from app.llm.router import build_router
from app.routers.journey import _persist_trip, _resolve_segments
from app.schemas import BuildJourneyRequest, JourneySegmentSelection

DAY = "2026-10-03"


async def main() -> None:
    settings = get_settings()
    print("=================================================================")
    print("  AUTONOMOUS TRIP RECOVERY AGENT DEMO: CHENNAI -> DELHI")
    print("=================================================================")
    print(f"Target Date: {DAY}")
    print(f"RailRadar Configured: {settings.railradar_enabled} (Key: {settings.effective_railradar_api_key[:6]}...)")
    print(f"Flight Provider: {settings.flight_provider or 'AeroDataBox'}")
    print("-----------------------------------------------------------------")

    # 1. Search live available options from Chennai to Delhi
    print("\n[Step 1] Querying Available Travel Options (Air & Ground)...")
    leg_options = await builder.search_options_live(
        "MAA", "DEL", on_date=date.fromisoformat(DAY)
    )
    print(f"Total options discovered: {len(leg_options.options)}")
    print(f"Data Sources: {leg_options.sources}")

    live_rail = [o for o in leg_options.options if o.segment_type.value == "train" and o.provenance == "LIVE"]
    ref_rail = [o for o in leg_options.options if o.segment_type.value == "train" and o.provenance == "REFERENCE"]
    buses = [o for o in leg_options.options if o.segment_type.value == "bus"]
    flights = [o for o in leg_options.options if o.segment_type.value == "flight"]

    print(f" - Live RailRadar Trains: {len(live_rail)}")
    for t in live_rail:
        print(f"   * [{t.provenance}] {t.service_number} dep {t.departure_utc.strftime('%H:%M UTC')} ({t.cost_minor/100:.0f} INR)")
        print(f"     Note: {t.note}")

    print(f" - Reference Trains: {len(ref_rail)}")
    for t in ref_rail[:2]:
        print(f"   * [{t.provenance}] {t.service_number} dep {t.departure_utc.strftime('%H:%M UTC')}")

    print(f" - Buses Available: {len(buses)}")
    print(f" - Flights Available: {len(flights)}")

    # 2. Build and persist a disrupted flight trip
    print("\n[Step 2] Passenger has a flight booked: Chennai (MAA) -> Delhi (DEL)...")
    session = SessionLocal()
    try:
        actor = bootstrap.create_accounts(session, "12345")[2]  # traveller account
        session.commit()

        # Build flight segment
        flight_opt = flights[0] if flights else None
        if flight_opt is None:
            # Fallback to direct service selection
            flight_key = "flight-6E204-2026-10-03-MAA-DEL"
            dep_utc = datetime(2026, 10, 3, 10, 0, 0, tzinfo=timezone.utc)
            arr_utc = datetime(2026, 10, 3, 12, 45, 0, tzinfo=timezone.utc)
        else:
            flight_key = flight_opt.key
            dep_utc = flight_opt.departure_utc
            arr_utc = flight_opt.arrival_utc

        payload = BuildJourneyRequest(
            name="Chennai to Delhi - Business Trip",
            reason="business",
            origin="MAA",
            destination="DEL",
            date=DAY,
            segments=[
                JourneySegmentSelection(
                    service_key=flight_key,
                    origin="MAA",
                    destination="DEL",
                    date=DAY,
                    mode="flight",
                ),
            ],
        )

        resolved = await _resolve_segments(payload)
        trip = _persist_trip(session, actor, payload, resolved)
        pipeline.ensure_baseline(session, trip=trip)
        session.commit()
        print(f"Trip created (ID: {trip.id}) with flight {trip.segments[0].service_number}")

        # 3. Simulate Flight Cancellation at Chennai Airport
        print("\n[Step 3] Flight Disruption Detected: Unexpected Flight CANCELLATION!")
        target_segment = trip.segments[0]
        target_segment.status = SegmentStatus.CANCELLED
        session.commit()

        # 4. Trigger Autonomous Trip Recovery Agent
        print("\n[Step 4] Running Autonomous Recovery Agent Pipeline...")
        disruption = pipeline.detect_disruption(
            session,
            trip=trip,
            kind=DisruptionKind.FLIGHT_CANCELLATION,
            segment_id=target_segment.id,
            delay_minutes=0,
            detail="Chennai to Delhi flight cancelled. Rerouting via ground and multimodal transport.",
            payload={"origin": "airport_terminal"},
            provenance="LIVE",
            source="AeroDataBox Live Telemetry",
        )
        impact = pipeline.assess_impact(session, trip=trip, disruption=disruption)
        constraints = pipeline.build_constraints(session, trip=trip)
        router = build_router(settings)

        plans = await pipeline.generate_plans(
            session,
            trip=trip,
            disruption=disruption,
            constraints=constraints,
            settings=settings,
            llm=router,
        )

        print("\n=================================================================")
        print("  RECOVERY ASSESSMENT & PLANS GENERATED BY AGENT")
        print("=================================================================")
        print(f"Total Alternative Plans Built: {len(plans)}")

        for idx, plan in enumerate(plans, 1):
            rec_tag = " [RECOMMENDED]" if plan.recommended else ""
            print(f"\n--- Plan {plan.label}: {plan.title}{rec_tag} (Score: {plan.score:.1f}) ---")
            print(f"Summary: {plan.summary or plan.explanation}")
            cost_display = f"{plan.additional_cost_minor/100:.2f} {plan.currency}"
            print(f"Duration: {plan.total_duration_minutes} min | Cost: {cost_display}")
            print("Legs:")
            for s_idx, leg in enumerate(plan.segments, 1):
                if isinstance(leg, dict):
                    prov_badge = f"[{leg.get('provenance', 'REFERENCE')}]"
                    m = leg.get('mode', leg.get('segment_type', 'transit')).upper()
                    svc = leg.get('service_number', leg.get('service', 'Service'))
                    orig = leg.get('origin', leg.get('origin_code', ''))
                    dest = leg.get('destination', leg.get('destination_code', ''))
                    dep = leg.get('departure_local', leg.get('departure', ''))
                    arr = leg.get('arrival_local', leg.get('arrival', ''))
                    notes = leg.get('notes', leg.get('note', ''))
                    print(f"  {s_idx}. {prov_badge} {m}: {svc} ({orig} -> {dest}) | Dep: {dep} -> Arr: {arr}")
                    if notes:
                        print(f"     Note: {notes}")
                else:
                    print(f"  {s_idx}. {leg}")

        print("\n=================================================================")
        print("  DEMO COMPLETED SUCCESSFULLY!")
        print("=================================================================")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
