"""Seed the Chennai to Delhi flight disruption demo trip into retryp.db.

This pre-populates the exact prompt scenario:
- Confirmed long-distance flight from Chennai (MAA) to Delhi (DEL) for today (2026-10-03)
- Disrupted by an unexpected flight cancellation after reaching the airport
- Autonomous Agent analysis and ranked multimodal recovery alternatives
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bootstrap
from app.config import get_settings
from app.db import SessionLocal
from app.domain.enums import DisruptionKind, SegmentStatus
from app.models import Disruption, RecoveryPlan, Segment, Trip
from app.routers.journey import _open_recovery, _persist_trip, _resolve_segments
from app.schemas import BuildJourneyRequest, JourneySegmentSelection

DAY = "2026-10-03"


async def seed() -> None:
    session = SessionLocal()
    settings = get_settings()

    try:
        # 1. Ensure user accounts exist
        actor = bootstrap.create_accounts(session, "12345")[2]  # traveller account
        session.commit()

        # 2. Clean up previous demo trips for this user
        existing = session.query(Trip).filter(Trip.traveller_id == actor.id).all()
        for t in existing:
            session.delete(t)
        session.commit()

        # 3. Create the confirmed flight journey: MAA -> DEL
        flight_key = "flight-6E953-2026-10-03-MAA-DEL"
        # Search live options to get exact flight key for today
        from app.domain import journey as builder
        leg_opts = await builder.search_options_live("MAA", "DEL", on_date=date.fromisoformat(DAY))
        matching_flight = next((o for o in leg_opts.options if o.segment_type.value == "flight"), None)
        if matching_flight:
            flight_key = matching_flight.key

        payload = BuildJourneyRequest(
            name="Chennai to Delhi - Long Distance Recovery Demo",
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
        trip.reference = "RTY-CHE-DEL"
        session.commit()
        session.refresh(trip)

        # 4. Trigger Flight Cancellation & Autonomous Recovery Agent
        target_segment = trip.segments[0]
        target_segment.status = SegmentStatus.CANCELLED
        session.commit()

        outcome = await _open_recovery(
            session,
            trip=trip,
            actor=actor,
            kind=DisruptionKind.FLIGHT_CANCELLATION.value,
            segment=target_segment,
            delay_minutes=0,
        )
        session.commit()
        session.refresh(trip)

        print("\n=============================================================")
        print("  DEMO TRIP SEEDED SUCCESSFULLY IN DATABASE!")
        print("=============================================================")
        print(f"Trip ID:        {trip.id}")
        print(f"Reference:      {trip.reference}")
        print(f"Status:         {trip.status}")
        print(f"Disruption:     Flight Cancellation on {target_segment.service_number}")
        print(f"Plans Created:  {len(outcome.get('plans', []))}")
        for p in outcome.get("plans", []):
            rec = " [RECOMMENDED]" if p.recommended else ""
            print(f"  * Plan {p.label}: {p.title}{rec} (Score: {p.score:.1f}, {p.additional_cost_minor/100:.2f} {p.currency})")
        print("=============================================================\n")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(seed())
