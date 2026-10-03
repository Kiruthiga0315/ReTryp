"""Real reference and rail data.

The product ships with downloaded reference artifacts (OurAirports, OpenFlights)
and, after ``scripts/build_rail``, real German timetables. These tests assert the
loader behaviour that the rest of the app depends on: a known airport resolves,
its timezone resolves, and rail lookups return real timetabled services with
honest provenance.

Tests that need the rail artifact skip when it has not been built, so the suite
stays green in a bare checkout while still proving the integration wherever the
artifact exists.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain import rail
from app.domain.reference import (
    REFERENCE_LOADED,
    airline_name,
    route_airlines,
    search_airports,
    timezone_for,
)


@pytest.mark.skipif(not REFERENCE_LOADED, reason="reference artifact not built")
def test_known_airports_resolve_with_timezones() -> None:
    assert timezone_for("MAA") == "Asia/Kolkata"
    assert timezone_for("FRA") == "Europe/Berlin"
    assert timezone_for("BER") == "Europe/Berlin"


@pytest.mark.skipif(not REFERENCE_LOADED, reason="reference artifact not built")
def test_airport_search_ranks_the_exact_code_first() -> None:
    results = search_airports("FRA")
    assert results
    assert results[0].code == "FRA"


@pytest.mark.skipif(not REFERENCE_LOADED, reason="reference artifact not built")
def test_openflights_routes_name_the_operating_airlines() -> None:
    # Chennai to Frankfurt is served by Air India and Lufthansa in the dataset.
    carriers = route_airlines("MAA", "FRA")
    assert "LH" in carriers
    assert "AI" in carriers
    assert airline_name("LH") == "Lufthansa"


@pytest.mark.skipif(not REFERENCE_LOADED, reason="reference artifact not built")
def test_unknown_route_returns_nothing_rather_than_a_guess() -> None:
    assert route_airlines("ZZZ", "QQQ") == []


pytestmark_rail = pytest.mark.skipif(not rail.RAIL_LOADED, reason="rail artifact not built")


@pytestmark_rail
def test_rail_options_are_real_reference_data_with_honest_provenance() -> None:
    after = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    options = rail.rail_options_between("FRA", "BER", after)
    assert options, "expected direct Frankfurt to Berlin services on a weekday"
    for option in options:
        assert option.departure_utc > after
        assert option.arrival_utc > option.departure_utc
        assert option.provenance == "REFERENCE"
        # The note must never imply live running status.
        assert "live" not in option.note.lower().replace("not live", "")


@pytestmark_rail
def test_rail_duration_matches_the_timetable_not_the_query_time() -> None:
    after = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
    options = rail.rail_options_between("FRA", "BER", after)
    assert options
    for option in options:
        # Frankfurt to Berlin by ICE is a little over four hours in reality.
        assert 200 <= option.duration_minutes <= 330


@pytestmark_rail
def test_rail_marks_fares_as_estimates() -> None:
    after = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    options = rail.rail_options_between("FRA", "BER", after)
    assert options
    assert all("estimate" in o.note.lower() for o in options)


@pytestmark_rail
def test_rail_returns_nothing_outside_the_feed_window() -> None:
    # The feed covers a rolling month; a date far outside it must yield nothing
    # rather than a stale or invented service.
    after = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert rail.rail_options_between("FRA", "BER", after) == []
