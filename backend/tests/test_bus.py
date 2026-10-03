from datetime import datetime, timezone

from app.domain import bus
from app.domain.enums import SegmentType


def test_bus_is_loaded() -> None:
    assert bus.BUS_LOADED
    assert len(bus.SERVICES) > 0


def test_bus_options_between_chennai_and_hyderabad() -> None:
    after_utc = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    options = bus.bus_options_between("MAA", "HYD", after_utc)
    assert len(options) > 0
    for opt in options:
        assert opt.segment_type == SegmentType.BUS
        assert opt.currency == "INR"
        assert opt.provenance == "REFERENCE"
        assert "bus" in opt.note.lower()
