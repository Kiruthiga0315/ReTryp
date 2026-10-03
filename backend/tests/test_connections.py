"""Connection feasibility, including timezone and DST edge cases.

The spec calls these out explicitly: MCT arithmetic must be correct across
zones and across the Europe/Berlin DST transition that falls inside the demo
trip (25 October 2026).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.connections import (
    arrival_shift_minutes,
    assess_chain,
    assess_connection,
    worst_safety,
)
from app.domain.enums import ConnectionSafety
from app.domain.timeutil import minutes_between, to_local, zone_label


def dt(hour: int, minute: int = 0, *, day: int = 28, tz=timezone.utc) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=tz)


def test_fra_connection_is_broken_when_the_buffer_is_under_the_mct() -> None:
    # FRA international-to-international MCT is 60 min in the curated table.
    result = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 30),
        departing_at_utc=dt(11, 20),  # 50 minutes
        origin_country="IN",
        destination_country="DE",
    )
    assert result.required_minutes == 60
    assert result.buffer_minutes == 50
    assert result.shortfall_minutes == 10
    assert result.safety is ConnectionSafety.BROKEN
    assert result.feasible is False
    assert "Connection no longer feasible" == result.label


def test_fra_connection_is_tight_just_above_the_mct() -> None:
    result = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 30),
        departing_at_utc=dt(11, 35),  # 65 minutes: 60 required + 5, under the 20 min margin
        origin_country="IN",
        destination_country="DE",
    )
    assert result.buffer_minutes == 65
    assert result.safety is ConnectionSafety.TIGHT


def test_fra_connection_is_safe_with_a_comfortable_buffer() -> None:
    result = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 30),
        departing_at_utc=dt(12, 0),  # 90 minutes: 60 required + 30, over the margin
        origin_country="IN",
        destination_country="DE",
    )
    assert result.safety is ConnectionSafety.SAFE
    assert result.feasible is True


def test_baggage_recheck_adds_twenty_minutes_to_the_requirement() -> None:
    plain = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 30),
        departing_at_utc=dt(11, 50),
        origin_country="IN",
        destination_country="DE",
    )
    recheck = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 30),
        departing_at_utc=dt(11, 50),
        origin_country="IN",
        destination_country="DE",
        requires_baggage_recheck=True,
    )
    assert recheck.required_minutes == plain.required_minutes + 20


def test_timezone_offsets_do_not_change_utc_arithmetic() -> None:
    """A buffer is computed in UTC, so a zone offset on either end is irrelevant."""
    # 08:50 CEST arrival in Frankfurt, 12:20 CEST departure, both expressed in UTC.
    berlin = timezone(timedelta(hours=2))
    arrival_utc = datetime(2026, 9, 28, 6, 50, tzinfo=berlin).astimezone(timezone.utc)
    departure_utc = datetime(2026, 9, 28, 10, 20, tzinfo=berlin).astimezone(timezone.utc)
    result = assess_connection(
        airport_code="FRA",
        arriving_at_utc=arrival_utc,
        departing_at_utc=departure_utc,
        origin_country="IN",
        destination_country="DE",
    )
    assert result.buffer_minutes == 210
    assert result.safety is ConnectionSafety.SAFE


def test_dst_transition_does_not_break_the_buffer() -> None:
    """Europe/Berlin leaves DST at 03:00 CEST on 25 October 2026.

    The local calendar day is 25 hours long. Buffer arithmetic must be in real
    elapsed UTC minutes, not wall-clock differences, or a connection on that
    day would be misjudged by an hour.
    """
    from zoneinfo import ZoneInfo

    berlin = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 10, 25, 0, 0, tzinfo=berlin)
    end = datetime(2026, 10, 25, 23, 0, tzinfo=berlin)
    # 23:00 CET is 22:00 UTC; 00:00 CET is 23:00 UTC the previous day.
    assert minutes_between(start, end) == 24 * 60

    # A connection that spans the fall-back. 02:30 is ambiguous on this date;
    # the second pass through it (fold=1) is CET, two real hours after 01:30 CEST
    # even though the clock only reads one hour apart.
    before = datetime(2026, 10, 25, 1, 30, tzinfo=berlin, fold=0)
    after = datetime(2026, 10, 25, 2, 30, tzinfo=berlin, fold=1)
    result = assess_connection(
        airport_code="FRA",
        arriving_at_utc=before,
        departing_at_utc=after,
        origin_country="DE",
        destination_country="DE",
    )
    assert result.buffer_minutes == 120
    assert result.safety is ConnectionSafety.SAFE

    # And the same instants rendered back into local time keep the DST label.
    assert to_local(before, "FRA").hour == 1
    assert zone_label("Europe/Berlin", before) == "CEST"
    # 02:30 CET is the same instant as 03:30 CEST, so the label is CEST for it;
    # a clearly post-transition instant is labelled CET.
    late = datetime(2026, 10, 25, 23, 0, tzinfo=berlin)
    assert zone_label("Europe/Berlin", late) == "CET"


def test_worst_safety_ranks_broken_above_safe() -> None:
    safe = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 0),
        departing_at_utc=dt(12, 0),
        origin_country="DE",
        destination_country="DE",
    )
    broken = assess_connection(
        airport_code="FRA",
        arriving_at_utc=dt(10, 0),
        departing_at_utc=dt(10, 30),
        origin_country="DE",
        destination_country="DE",
    )
    assert worst_safety([safe, broken]) is ConnectionSafety.BROKEN
    assert worst_safety([]) is ConnectionSafety.SAFE


def test_assess_chain_returns_one_assessment_per_connection() -> None:
    chain = [
        ("FRA", dt(6, 50), dt(10, 20)),
        ("BER", dt(11, 40), dt(13, 0)),
    ]
    results = assess_chain(chain, requires_immigration_at={"FRA"})
    assert len(results) == 2
    assert [r.airport_code for r in results] == ["FRA", "BER"]


def test_arrival_shift_is_signed() -> None:
    assert arrival_shift_minutes(dt(12, 0), dt(13, 20)) == 80
    assert arrival_shift_minutes(dt(12, 0), dt(11, 0)) == -60
    assert arrival_shift_minutes(dt(12, 0), dt(12, 0)) == 0
