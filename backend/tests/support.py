"""Deterministic provider doubles for the test suite.

ReTryp has no demo catalogue, so the tests must not depend on a developer's
API keys or on a live provider's departure board. Instead the provider search
methods are replaced with synthetic schedules that exercise the real
pipeline - persistence, connection arithmetic, plan generation, scoring and
execution - without a network call.

Only the outermost provider boundary is replaced. Everything downstream of it
(parsing, merging, dedup, connection checks, scoring, the API layer, the UI
contracts) is the real code, and the provenance carried by the synthetic rows
is ``LIVE`` so the app behaves exactly as it does with a configured key.

Two things are deliberately *not* doubles: :func:`parse_flights_future_row`
tests the real AviationStack schedule parser against a recorded response, and
the reference/rail datasets are the real downloaded artifacts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.enums import SegmentType
from app.domain.options import OptionSegment

UTC = timezone.utc

# A small, fixed timetable. Times are UTC; the local-time rendering is exercised
# by the connection and departure-window tests, not fixed here.
#
# Each leg's departure sits inside its origin's **local** calendar day for
# 2026-09-28, which is the window the builder searches (MAA is UTC+5:30, so
# that window is 2026-09-27T18:30Z to 2026-09-28T18:30Z; FRA is UTC+2, so its
# window is 2026-09-27T22:00Z to 2026-09-28T22:00Z).
#
# MAA-FRA LH759 arrives 10:00Z against an 11:40Z onward departure: a 100 minute
# buffer at Frankfurt, which clears the 60 minute MCT. Delaying it by 225
# minutes makes that connection impossible, which is the scenario the recovery
# tests drive.
_TIMETABLE: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("MAA", "FRA", "LH", "759", "2026-09-28T02:00", "2026-09-28T10:00"),
    ("MAA", "FRA", "LH", "761", "2026-09-28T14:15", "2026-09-28T22:10"),
    ("FRA", "BER", "LH", "1004", "2026-09-28T11:40", "2026-09-28T12:50"),
    ("FRA", "BER", "LH", "1006", "2026-09-28T13:30", "2026-09-28T14:40"),
    ("FRA", "BER", "LH", "1010", "2026-09-28T16:00", "2026-09-28T17:10"),
    ("FRA", "BER", "LH", "1012", "2026-09-28T18:40", "2026-09-28T19:50"),
    ("FRA", "BER", "LH", "1016", "2026-09-29T05:40", "2026-09-29T06:50"),
    ("MAA", "COK", "AI", "601", "2026-09-28T06:00", "2026-09-28T07:30"),
    ("MAA", "COK", "AI", "603", "2026-09-28T10:00", "2026-09-28T11:30"),
    ("MAA", "COK", "IX", "441", "2026-09-28T14:00", "2026-09-28T15:30"),
    ("MAA", "COK", "AI", "605", "2026-09-29T06:30", "2026-09-29T08:00"),
)

FARE_MINOR = 14_000


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def schedule_options(
    origin: str, destination: str, after_utc: datetime, *, limit: int = 12
) -> list[OptionSegment]:
    """Synthetic options for a pair, departing at or after a given instant."""
    options: list[OptionSegment] = []
    for o, d, carrier, number, dep, arr in _TIMETABLE:
        if o != origin or d != destination:
            continue
        departure = _parse(dep)
        arrival = _parse(arr)
        if arrival <= departure or departure < after_utc:
            continue
        options.append(
            OptionSegment(
                key=f"test:{o}-{d}:{carrier}{number}:{departure.isoformat()}",
                segment_type=SegmentType.FLIGHT,
                carrier_code=carrier,
                service_number=f"{carrier}{number}",
                origin_code=o,
                destination_code=d,
                departure_utc=departure,
                arrival_utc=arrival,
                cost_minor=FARE_MINOR,
                currency="EUR",
                refundable=False,
                note="Synthetic test schedule.",
                provenance="LIVE",
            )
        )
    options.sort(key=lambda o: o.departure_utc)  # type: ignore[arg-type,return-value]
    return options[:limit]


def pair_by_number(service_number: str) -> tuple[str, str]:
    """The (origin, destination) a synthetic flight belongs to."""
    for o, d, carrier, number, _dep, _arr in _TIMETABLE:
        if f"{carrier}{number}" == service_number:
            return o, d
    raise KeyError(service_number)


def option_for(client, headers, origin: str, destination: str, service_number: str, date: str) -> dict:
    """Fetch one option from the API by service number, using its real key.

    Tests never assume the key format; they take what the API actually offered,
    exactly as the frontend does.
    """
    response = client.get(
        "/api/journey/options",
        params={"origin": origin, "destination": destination, "date": date},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    match = next(
        (o for o in response.json()["options"] if o["service_number"] == service_number),
        None,
    )
    assert match is not None, f"{service_number} missing from {origin}-{destination}"
    return match


def departure(service_number: str) -> datetime:
    for _o, _d, carrier, number, dep, _arr in _TIMETABLE:
        if f"{carrier}{number}" == service_number:
            return _parse(dep)
    raise KeyError(service_number)


# The first two legs of the reference journey, used by the trip fixture.
LONG_HAUL_NUMBER = "LH759"
CONNECTION_NUMBER = "LH1004"

# A recorded AviationStack ``flightsFuture`` row, used to test the real parser
# without a network call. Shape taken from the live endpoint.
RECORDED_FLIGHTS_FUTURE_ROW = {
    "weekday": "1",
    "departure": {
        "iataCode": "maa",
        "icaoCode": "vomm",
        "terminal": "2",
        "gate": "11b",
        "scheduledTime": "2026-10-05 00:50:00",
    },
    "arrival": {
        "iataCode": "fra",
        "icaoCode": "eddf",
        "terminal": "1",
        "gate": "",
        "scheduledTime": "2026-10-05 07:35:00",
    },
    "aircraft": {"modelCode": "b77w", "modelText": "boeing 777-300er"},
    "airline": {"name": "lufthansa", "iataCode": "lh", "icaoCode": "dlh"},
    "flight": {"number": "759", "iataNumber": "lh759", "icaoNumber": "dlh759"},
}


def install_provider_doubles(monkeypatch) -> None:
    """Replace the provider boundaries with the synthetic schedules above."""
    from app.providers import data as data_providers
    from app.providers import flights as flight_providers

    async def fake_search(self, *, origin, destination, depart_after_utc):
        return schedule_options(origin, destination, depart_after_utc)

    monkeypatch.setattr(
        flight_providers.AeroDataBoxProvider, "search", fake_search, raising=True
    )
    monkeypatch.setattr(
        flight_providers.AviationStackProvider, "search", fake_search, raising=True
    )
    monkeypatch.setattr(
        flight_providers.FlightAwareAeroAPIProvider, "search", fake_search, raising=True
    )

    async def fake_hotels(settings, city_code, nights=1):
        return [
            data_providers.HotelOption(
                key=f"test-hotel-{city_code}",
                name=f"{city_code} Central Hotel",
                city_code=city_code,
                city_name=city_code,
                timezone="Europe/Berlin",
                address="1 Teststrasse",
                latitude=52.52,
                longitude=13.405,
                cost_minor=18_500,
                currency="EUR",
                refundable=True,
                provenance="LIVE",
                source="Test hotel double",
                note="Synthetic test property.",
            )
        ]

    async def fake_transfers(settings, city_code, after_utc):
        return [
            data_providers.GroundOption(
                key=f"test-transfer-{city_code}",
                mode="transfer",
                provider_name="Test Express",
                from_label=f"{city_code} airport",
                to_label=f"{city_code} centre",
                city_code=city_code,
                timezone="Europe/Berlin",
                pickup_utc=after_utc + timedelta(minutes=45),
                dropoff_utc=after_utc + timedelta(minutes=75),
                cost_minor=3_900,
                currency="EUR",
                provenance="LIVE",
                source="Test transfer double",
                note="Synthetic test transfer.",
            )
        ]

    monkeypatch.setattr(data_providers, "search_hotels", fake_hotels, raising=True)
    monkeypatch.setattr(data_providers, "get_transfers", fake_transfers, raising=True)
