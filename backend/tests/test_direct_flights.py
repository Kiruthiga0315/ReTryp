"""Direct flights must be searched as an exact pair, and scheduled for the right day.

Two defects made the Journey Builder look like it could only bridge flights:

* The AviationStack search read the origin's whole departure board and then
  filtered arrivals by *city market*, so any same-city airport matched. A
  request for a pair the schedule did not carry returned nothing at all, and
  the builder fell through to stitching a connection.
* ``flightsFuture`` publishes a bare wall-clock ``scheduledTime`` with no date,
  and the parser assumed the caller's UTC date. Any service whose local clock
  crosses midnight was placed on the wrong day.

The direct pair query, the schedule window and the row parser are driven here
with recorded payloads, so these tests never call the provider.
"""

from datetime import date, datetime, timezone

import pytest

from app.providers import flights


def _row(
    *,
    flight_date: str = "2026-09-29",
    dep_iata: str = "MAA",
    arr_iata: str = "DEL",
    number: str = "6E2369",
    dep: str = "2026-09-29T09:00:00+00:00",
    arr: str = "2026-09-29T11:30:00+00:00",
) -> dict:
    return {
        "flight_date": flight_date,
        "flight_status": "scheduled",
        "departure": {"iata": dep_iata, "scheduled": dep, "estimated": dep, "terminal": "1"},
        "arrival": {"iata": arr_iata, "scheduled": arr, "estimated": arr},
        "airline": {"name": "IndiGo", "iata": "6E"},
        "flight": {"number": "2369", "iata": number},
    }


def _provider() -> flights.AviationStackProvider:
    # Instantiated directly: no network, no registry traffic.
    return flights.AviationStackProvider("test-key")


def _search(
    payload: dict,
    *,
    origin: str = "MAA",
    destination: str = "DEL",
    after: datetime = datetime(2026, 9, 29, 0, tzinfo=timezone.utc),
    day: str = "2026-09-29",
):
    return _provider()._direct_options_from_payload(
        payload, "LIVE", None, origin, destination, day, after
    )


def test_a_direct_pair_returns_exactly_that_pair():
    payload = {"data": [_row(), _row(number="AI803", dep="2026-09-29T13:00:00+00:00",
                                       arr="2026-09-29T15:20:00+00:00")]}

    options = _search(payload)

    assert [o.service_number for o in options] == ["6E2369", "AI803"]
    assert all(o.origin_code == "MAA" and o.destination_code == "DEL" for o in options)


def test_a_row_landing_at_another_airport_is_not_the_requested_pair():
    """The pair query is exact, so a stray row for a different airport is dropped."""
    payload = {"data": [_row(arr_iata="BOM")]}

    assert _search(payload) == []


def test_a_row_for_another_date_is_not_offered():
    """The real-time endpoint can answer for a different day than was requested."""
    payload = {"data": [_row(flight_date="2026-09-28")]}

    assert _search(payload) == []


def test_a_service_that_has_already_departed_is_dropped():
    payload = {"data": [_row(dep="2026-09-29T01:00:00+00:00", arr="2026-09-29T03:30:00+00:00")]}

    options = _search(payload, after=datetime(2026, 9, 29, 8, tzinfo=timezone.utc))

    assert options == []


def test_a_non_positive_duration_is_dropped():
    payload = {"data": [_row(dep="2026-09-29T11:00:00+00:00", arr="2026-09-29T10:00:00+00:00")]}

    assert _search(payload) == []


def test_same_origin_and_destination_is_not_searched(monkeypatch):
    """A pair query for a place against itself is meaningless."""
    calls = {"n": 0}

    async def recorder(self, origin, destination):
        calls["n"] += 1
        return {"data": []}

    monkeypatch.setattr(flights.AviationStackProvider, "_direct_pair_payload", recorder)

    import asyncio

    result = asyncio.run(
        _provider()._search_direct_pair(
            "MAA", "MAA", datetime(2026, 9, 29, 0, tzinfo=timezone.utc)
        )
    )

    assert result == []
    assert calls["n"] == 0


def _codeshare_row(
    *,
    marketing: str,
    operating: str,
    dep: str = "2026-09-29T23:45:00+00:00",
    arr: str = "2026-09-30T02:40:00+00:00",
    status: str = "scheduled",
) -> dict:
    """One provider row, as AviationStack publishes it.

    The operator's own row carries ``codeshared: null``; a partner's marketing
    row names the operator in ``codeshared``.
    """
    row = _row(number=marketing, dep=dep, arr=arr)
    row["flight_status"] = status
    if marketing != operating:
        row["flight"]["codeshared"] = {
            "airline_iata": "".join(ch for ch in operating if ch.isalpha()),
            "flight_iata": operating,
        }
    return row


def test_codeshares_of_one_service_collapse_to_the_operating_flight():
    """A partner's marketing row is the same physical flight, shown once."""
    payload = {
        "data": [
            _codeshare_row(marketing="VS8401", operating="6E2369"),
            _codeshare_row(marketing="TK7813", operating="6E2369"),
            _codeshare_row(marketing="6E2369", operating="6E2369"),
        ]
    }

    options = _search(payload)

    assert len(options) == 1
    assert options[0].service_number == "6E2369"
    assert "VS8401" in options[0].note and "TK7813" in options[0].note


def test_the_operating_row_is_preferred_over_its_marketing_copies():
    payload = {
        "data": [
            _codeshare_row(marketing="VS8401", operating="6E2369"),
            _codeshare_row(marketing="6E2369", operating="6E2369"),
        ]
    }

    options = _search(payload)

    assert options[0].service_number == "6E2369"
    assert options[0].operating_number is None


def test_distinct_services_are_not_collapsed_together():
    payload = {
        "data": [
            _codeshare_row(marketing="VS8401", operating="6E2369"),
            _codeshare_row(
                marketing="AI2886",
                operating="AI2886",
                dep="2026-09-29T12:25:00+00:00",
                arr="2026-09-29T15:51:00+00:00",
            ),
        ]
    }

    options = _search(payload)

    assert len(options) == 2


def test_a_finished_journey_is_not_badged_live():
    """A landed reading is a past fact, so the option is badged cached."""
    payload = {"data": [_codeshare_row(marketing="6E937", operating="6E937", status="landed")]}

    option = _search(payload)[0]

    assert option.stale_when_landed is True
    assert option.provenance == "LIVE"  # provider provenance is unchanged...
    # ...the badge is demoted where the payload is rendered.


@pytest.mark.parametrize(
    "designator,expected",
    [
        ("6E2369", "6E"),
        ("B62220", "B6"),
        ("U24584", "U2"),
        ("LH759", "LH"),
        ("AI2886", "AI"),
        ("9W123", "9W"),
        ("DLH759", "DLH"),
        ("", "??"),
    ],
)
def test_carrier_codes_keep_their_leading_digit(designator, expected):
    """``6E`` is IndiGo; taking only letters would return ``E``."""
    assert flights._carrier_code(designator) == expected


def test_a_landed_option_is_not_live_in_the_payload():
    """The API demotes a finished reading to cached, so the badge is honest."""
    from app.routers.journey import _option_payload

    landed = _search(
        {"data": [_codeshare_row(marketing="6E937", operating="6E937", status="landed")]}
    )[0]
    live = _search({"data": [_codeshare_row(marketing="6E404", operating="6E404")]})[0]

    assert _option_payload(landed, origin_tz="Asia/Kolkata", destination_tz="Asia/Kolkata")[
        "provenance"
    ] == "CACHED"
    assert _option_payload(live, origin_tz="Asia/Kolkata", destination_tz="Asia/Kolkata")[
        "provenance"
    ] == "LIVE"


# ---------------------------------------------------------------------------
# The schedule window and the row date
# ---------------------------------------------------------------------------


def test_the_schedule_window_matches_the_published_rule():
    tz = flights.zone_for("MAA")
    today = datetime.now(timezone.utc).astimezone(tz).date()

    assert not flights._within_schedule_window(today, tz), "today is rejected"
    assert flights._within_schedule_window(date.fromordinal(today.toordinal() + 1), tz)
    assert flights._within_schedule_window(date.fromordinal(today.toordinal() + 7), tz)
    assert not flights._within_schedule_window(date.fromordinal(today.toordinal() + 8), tz)


def test_a_schedule_row_is_combined_with_its_own_date():
    """A 00:50 local departure stays on the published day, not the caller's."""
    row = {
        "date": "2026-10-05",
        "departure": {"iataCode": "MAA", "scheduledTime": "2026-10-05 00:50:00"},
        "arrival": {"iataCode": "DEL", "scheduledTime": "2026-10-05 03:40:00"},
        "flight": {"iataNumber": "6E1234"},
        "airline": {"name": "IndiGo"},
    }

    option = flights._option_from_flights_future(row, "LIVE", fallback_date=date(2026, 10, 5))

    assert option is not None
    # 00:50 in Asia/Kolkata (UTC+5:30) is 19:20 UTC on the previous day.
    assert option.departure_utc == datetime(2026, 10, 4, 19, 20, tzinfo=timezone.utc)
    assert option.arrival_utc == datetime(2026, 10, 4, 22, 10, tzinfo=timezone.utc)


def test_a_schedule_row_without_a_date_uses_the_requested_day():
    row = {
        "departure": {"iataCode": "FRA", "scheduledTime": "06:15:00"},
        "arrival": {"iataCode": "BER", "scheduledTime": "07:30:00"},
        "flight": {"iataNumber": "LH1004"},
        "airline": {"name": "Lufthansa"},
    }

    option = flights._option_from_flights_future(row, "LIVE", fallback_date=date(2026, 9, 29))

    assert option is not None
    # 06:15 in Europe/Berlin (CEST, UTC+2) on 2026-09-29.
    assert option.departure_utc == datetime(2026, 9, 29, 4, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-09-29T09:00:00+00:00", datetime(2026, 9, 29, 9, tzinfo=timezone.utc)),
        ("2026-09-29 09:00:00", datetime(2026, 9, 29, 9, tzinfo=timezone.utc)),
        (None, None),
        ("not a time", None),
    ],
)
def test_naive_time_parsing(value, expected):
    tz = timezone.utc
    assert flights._parse_naive_local(value, tz, on_date=date(2026, 9, 29)) == expected
