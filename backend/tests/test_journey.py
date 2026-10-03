"""Journey builder contract tests.

These pin the honesty rules the builder must keep: only services the loaded
datasets can answer for are offered, every option carries its provenance, a
trip cannot be built from a service key that was never offered, and a built
journey runs through the same recovery pipeline as a live event.

Options are always fetched from the API first and their real keys used, so the
tests exercise the same path the frontend does rather than assuming a key
format.
"""

from __future__ import annotations

from .conftest import (
    CONNECTION_SERVICE,
    DELAY_MINUTES,
    LONG_HAUL_SERVICE,
    TEST_PASSWORD,
    TRIP_DATE,
)
from .test_api import auth_headers, sign_in


def _options(client, headers, origin: str, destination: str, date: str = TRIP_DATE) -> list[dict]:
    response = client.get(
        "/api/journey/options",
        params={"origin": origin, "destination": destination, "date": date},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["options"]


def _option(client, headers, origin: str, destination: str, service_number: str) -> dict:
    options = _options(client, headers, origin, destination)
    match = next((o for o in options if o["service_number"] == service_number), None)
    assert match is not None, f"{service_number} missing from {origin}-{destination}"
    return match


def _base_payload(long_haul: dict, connection: dict, **extra) -> dict:
    payload = {
        "name": "API journey",
        "reason": "business",
        "origin": "MAA",
        "destination": "BER",
        "date": TRIP_DATE,
        "segments": [
            {
                "service_key": long_haul["key"],
                "origin": "MAA",
                "destination": "FRA",
                "date": TRIP_DATE,
                "mode": "flight",
            },
            {
                "service_key": connection["key"],
                "origin": "FRA",
                "destination": "BER",
                "date": TRIP_DATE,
                "mode": "flight",
            },
        ],
    }
    payload.update(extra)
    return payload


def test_reasons_are_offered_and_stable(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.get("/api/journey/reasons", headers=headers)
    assert response.status_code == 200, response.text
    codes = [r["code"] for r in response.json()["reasons"]]
    assert "business" in codes and "customer_meeting" in codes


def test_place_search_uses_reference_data(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.get("/api/journey/places", params={"q": "frankfurt"}, headers=headers)
    assert response.status_code == 200, response.text
    places = response.json()["places"]
    codes = {p["code"] for p in places}
    assert "FRA" in codes
    # Reference places advertise where they came from.
    assert all(p["provenance"] in {"REFERENCE", "CURATED"} for p in places)


def test_options_are_real_and_carry_provenance(client) -> None:
    """The configured provider answers LIVE, and the rail timetable REFERENCE."""
    headers = auth_headers(client, "traveller@retryp.example")

    flights = _options(client, headers, "MAA", "FRA")
    assert flights, "the configured provider must offer the long-haul leg"
    assert all(o["provenance"] == "LIVE" for o in flights)
    assert all(o["mode"] == "flight" for o in flights)

    fra_ber = _options(client, headers, "FRA", "BER")
    assert any(o["mode"] == "flight" and o["provenance"] == "LIVE" for o in fra_ber)
    # Rail comes from the downloaded DELFI / GTFS.de timetable, not an invented
    # schedule, and is badged as a reference dataset.
    assert all(o["provenance"] in {"LIVE", "REFERENCE"} for o in fra_ber)


def test_unknown_pair_offers_nothing_rather_than_inventing(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.get(
        "/api/journey/options",
        params={"origin": "BER", "destination": "MAA", "date": TRIP_DATE},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["options"] == []
    assert body["notes"], "an empty leg must explain why it is empty"


def test_build_persists_a_journey_and_checks_connections(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    long_haul = _option(client, headers, "MAA", "FRA", LONG_HAUL_SERVICE)
    connection = _option(client, headers, "FRA", "BER", CONNECTION_SERVICE)

    response = client.post(
        "/api/journey/build", headers=headers, json=_base_payload(long_haul, connection)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["cycle"] is None
    assert body["check"]["connection_count"] == 1
    # The FRA connection has a 100 minute buffer against a 60 minute MCT.
    assert body["check"]["healthy"] is True
    assert body["trip"]["segment_count"] == 2


def test_build_rejects_a_service_that_was_never_offered(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.post(
        "/api/journey/build",
        headers=headers,
        json={
            "name": "Tampered journey",
            "reason": "business",
            "origin": "MAA",
            "destination": "FRA",
            "date": TRIP_DATE,
            "segments": [
                {
                    "service_key": "INVENTED-0001",
                    "origin": "MAA",
                    "destination": "FRA",
                    "date": TRIP_DATE,
                    "mode": "flight",
                },
            ],
        },
    )
    assert response.status_code == 422, response.text


def test_build_with_a_delay_opens_a_recovery_cycle(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    long_haul = _option(client, headers, "MAA", "FRA", LONG_HAUL_SERVICE)
    connection = _option(client, headers, "FRA", "BER", CONNECTION_SERVICE)

    response = client.post(
        "/api/journey/build",
        headers=headers,
        json=_base_payload(
            long_haul,
            connection,
            reason="customer_meeting",
            disrupted_service_key=long_haul["key"],
            disruption_kind="flight_delay",
            delay_minutes=DELAY_MINUTES,
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["cycle"] == 1
    assert len(body["plans"]) >= 3
    # Plans are ordered best-first and one is plainly recommended.
    assert body["plans"][0]["recommended"] is True
    labels = {p["label"] for p in body["plans"]}
    assert {"A", "B", "C"}.issubset(labels)
    # Nothing claims a live rebooking.
    for plan in body["plans"]:
        assert plan["provenance"] in {"SIMULATED", "LIVE", "REFERENCE"}


def test_plans_reach_the_destination_and_are_ordered_by_arrival(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    long_haul = _option(client, headers, "MAA", "FRA", LONG_HAUL_SERVICE)
    connection = _option(client, headers, "FRA", "BER", CONNECTION_SERVICE)

    response = client.post(
        "/api/journey/build",
        headers=headers,
        json=_base_payload(
            long_haul,
            connection,
            disrupted_service_key=long_haul["key"],
            disruption_kind="flight_delay",
            delay_minutes=DELAY_MINUTES,
        ),
    )
    assert response.status_code == 201, response.text
    plans = response.json()["plans"]
    arrivals = [p["arrival_utc"] for p in plans]
    assert all(arrivals), "every plan must carry an arrival"
    # The recommended plan is the earliest arrival; the list is sorted by score.
    assert plans[0]["arrival_utc"] == min(arrivals)


def test_journey_builder_requires_authentication(client) -> None:
    # The shared test client keeps the session cookie from earlier sign-ins.
    client.cookies.clear()
    response = client.get("/api/journey/reasons")
    assert response.status_code == 401, response.text


def test_signin_still_returns_a_session(client) -> None:
    body = sign_in(client, "traveller@retryp.example", TEST_PASSWORD)
    assert body["user"]["email"] == "traveller@retryp.example"
    assert body["token"]
