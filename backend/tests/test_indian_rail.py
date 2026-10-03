from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain import rail
from app.domain.enums import SegmentType


def test_indian_rail_is_loaded() -> None:
    assert rail.RAIL_LOADED
    meta = rail.rail_services_meta()
    assert meta["loaded"]
    assert "Indian Railways" in meta["source"]


def test_indian_rail_options_between_chennai_and_delhi() -> None:
    after_utc = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    options = rail.rail_options_between("MAA", "DEL", after_utc)
    assert len(options) > 0
    # Should include Rajdhani Express or GT Express or Tamil Nadu Express
    service_numbers = [o.service_number for o in options]
    assert any("Rajdhani" in s or "GT Express" in s or "Tamil Nadu" in s for s in service_numbers)
    for opt in options:
        assert opt.segment_type == SegmentType.TRAIN
        assert opt.currency == "INR"
        assert opt.provenance == "REFERENCE"
        assert opt.cost_minor > 0


def test_indian_rail_intermediate_corridor() -> None:
    after_utc = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    options = rail.rail_options_between("MAA", "HYD", after_utc)
    assert len(options) > 0
    service_numbers = [o.service_number for o in options]
    assert any("Charminar" in s or "Duronto" in s for s in service_numbers)
