import pytest
from datetime import date, datetime, timedelta, timezone

from app.domain import itineraries
from app.domain.enums import ConnectionSafety, SegmentType
from app.domain.options import OptionSegment
from app.domain.recovery import PlanDraft, build_plan_drafts
from app.domain.impact import GroundSnapshot, HotelSnapshot, SegmentSnapshot


def _flight(origin: str, dest: str, dep: datetime, arr: datetime, svc: str = "AI 101") -> OptionSegment:
    return OptionSegment(
        key=f"flt-{svc}-{dep.isoformat()}",
        segment_type=SegmentType.FLIGHT,
        carrier_code="AI",
        service_number=svc,
        origin_code=origin,
        destination_code=dest,
        departure_utc=dep,
        arrival_utc=arr,
        cost_minor=500000,
        currency="INR",
        refundable=True,
        provenance="LIVE",
    )


def _train(origin: str, dest: str, dep: datetime, arr: datetime, svc: str = "12433 Rajdhani") -> OptionSegment:
    return OptionSegment(
        key=f"rail-{svc}-{dep.isoformat()}",
        segment_type=SegmentType.TRAIN,
        carrier_code="IR",
        service_number=svc,
        origin_code=origin,
        destination_code=dest,
        departure_utc=dep,
        arrival_utc=arr,
        cost_minor=320000,
        currency="INR",
        refundable=False,
        provenance="REFERENCE",
    )


def _bus(origin: str, dest: str, dep: datetime, arr: datetime, svc: str = "APSRTC Garuda") -> OptionSegment:
    return OptionSegment(
        key=f"bus-{svc}-{dep.isoformat()}",
        segment_type=SegmentType.BUS,
        carrier_code="APSRTC",
        service_number=svc,
        origin_code=origin,
        destination_code=dest,
        departure_utc=dep,
        arrival_utc=arr,
        cost_minor=120000,
        currency="INR",
        refundable=False,
        provenance="REFERENCE",
    )


def test_chennai_to_delhi_recovery_produces_train_and_multimodal_plans() -> None:
    # Disrupted flight: MAA -> DEL departing 2026-10-03 06:00 UTC
    dep = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
    arr = datetime(2026, 10, 3, 8, 45, tzinfo=timezone.utc)

    seg = SegmentSnapshot(
        id="seg-1",
        sequence=1,
        segment_type="flight",
        origin_code="MAA",
        destination_code="DEL",
        scheduled_departure_utc=dep,
        scheduled_arrival_utc=arr,
        effective_departure_utc=dep,
        effective_arrival_utc=arr,
        status="cancelled",
        carrier_code="6E",
        service_number="6E 2024",
        booking_reference="PNR123",
    )

    flight_replacements = [
        _flight("MAA", "DEL", dep + timedelta(hours=2), arr + timedelta(hours=2), "AI 2468"),
    ]
    rail_replacements = [
        # Leaves Chennai Central 7 hours after disruption: ample transfer time
        _train("MAS_RS", "NDLS", dep + timedelta(hours=7), dep + timedelta(hours=35), "GT Express 12615"),
    ]
    bus_replacements = [
        _bus("MAS_BT", "DEL_BT", dep + timedelta(hours=6), dep + timedelta(hours=40), "Intercity Express"),
    ]

    # Stitched multimodal: e.g. Bus to Hyderabad + Train to Delhi
    hub_itineraries = itineraries.connectable_itineraries("MAA", "DEL", date(2026, 10, 3))
    assert len(hub_itineraries) > 0

    drafts = build_plan_drafts(
        segments=[seg],
        hotels=[],
        ground=[],
        disrupted_segment_id="seg-1",
        delay_minutes=0,
        flight_options=flight_replacements,
        rail_options=rail_replacements,
        bus_options=bus_replacements,
        transfer_options=[],
        cancelled=True,
        currency="INR",
        hub_itineraries=hub_itineraries,
    )

    assert len(drafts) >= 3

    # Check for flight plan
    has_flight_plan = any(
        any(l.option.segment_type == SegmentType.FLIGHT for l in d.legs)
        for d in drafts
    )
    assert has_flight_plan

    # Check for direct rail plan
    has_rail_plan = any(
        all(l.option.segment_type == SegmentType.TRAIN for l in d.legs) and len(d.legs) == 1
        for d in drafts
    )
    assert has_rail_plan

    # Check for multimodal plan (e.g. Bus + Train or Train + Train via hub)
    has_multimodal_plan = any(
        len(d.legs) > 1 and any(l.option.segment_type in (SegmentType.TRAIN, SegmentType.BUS) for l in d.legs)
        for d in drafts
    )
    assert has_multimodal_plan
