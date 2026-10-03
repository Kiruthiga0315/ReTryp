"""Recovery reset and cycle isolation.

Re-injecting a disruption through the Scenario Simulator must supersede any
older open cycle rather than stacking a second live incident on the trip, and
a reset must return the itinerary to its baseline so the demonstration can be
replayed. These tests build their own trip so the shared seed stays intact.
"""

from __future__ import annotations

from .conftest import CONNECTION_SERVICE, LONG_HAUL_SERVICE, TRIP_DATE
from .support import option_for
from .test_api import auth_headers

OPEN_STATUSES = {"detected", "validated", "assessed", "recovering"}


def _build_trip(client, headers, *, disrupt: bool) -> str:
    long_haul = option_for(client, headers, "MAA", "FRA", LONG_HAUL_SERVICE, TRIP_DATE)
    connection = option_for(client, headers, "FRA", "BER", CONNECTION_SERVICE, TRIP_DATE)
    payload = {
        "name": "Reset fixture trip",
        "reason": "business",
        "origin": "MAA",
        "destination": "BER",
        "date": TRIP_DATE,
        "segments": [
            {"service_key": long_haul["key"], "origin": "MAA", "destination": "FRA", "date": TRIP_DATE, "mode": "flight"},
            {"service_key": connection["key"], "origin": "FRA", "destination": "BER", "date": TRIP_DATE, "mode": "flight"},
        ],
    }
    if disrupt:
        payload.update(
            {
                "disrupted_service_key": long_haul["key"],
                "disruption_kind": "flight_delay",
                "delay_minutes": 225,
            }
        )
    response = client.post("/api/journey/build", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["trip"]["id"]


def _disruptions(client, headers, trip_id):
    response = client.get(f"/api/trips/{trip_id}/disruptions", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["disruptions"]


def _open_disruptions(client, headers, trip_id):
    return [d for d in _disruptions(client, headers, trip_id) if d["status"] in OPEN_STATUSES]


def test_simulator_supersedes_the_previous_open_cycle(client) -> None:
    headers = auth_headers(client, "ops@retryp.example")
    trip_id = _build_trip(client, headers, disrupt=True)
    first = _open_disruptions(client, headers, trip_id)
    assert len(first) == 1

    injected = client.post(
        "/api/simulator/disruptions",
        headers=headers,
        json={
            "trip_id": trip_id,
            "kind": "flight_cancellation",
            "auto_generate_plans": False,
        },
    )
    assert injected.status_code == 200, injected.text
    new_id = injected.json()["disruption"]["id"]

    open_now = _open_disruptions(client, headers, trip_id)
    assert [d["id"] for d in open_now] == [new_id], "only the newest cycle stays open"
    superseded = [d for d in _disruptions(client, headers, trip_id) if d["id"] != new_id]
    assert superseded and all(d["status"] == "superseded" for d in superseded)


def test_reset_restores_the_baseline_itinerary(client) -> None:
    headers = auth_headers(client, "ops@retryp.example")
    trip_id = _build_trip(client, headers, disrupt=True)

    before = client.get(f"/api/trips/{trip_id}", headers=headers).json()["trip"]
    assert before["status"] in {"disrupted", "recovering"}

    reset = client.post(f"/api/trips/{trip_id}/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    removed = reset.json()["removed"]
    assert removed["disruptions"] >= 1
    assert reset.json()["disruptions"] == []

    after = client.get(f"/api/trips/{trip_id}", headers=headers).json()["trip"]
    assert after["segment_count"] == before["segment_count"]
    assert after["status"] in {"planned", "active"}


def test_reset_frees_the_next_cycle_to_start_at_one(client) -> None:
    headers = auth_headers(client, "ops@retryp.example")
    trip_id = _build_trip(client, headers, disrupt=True)

    assert client.post(f"/api/trips/{trip_id}/reset", headers=headers).status_code == 200
    second = client.post(f"/api/trips/{trip_id}/reset", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["removed"]["disruptions"] == 0

    injected = client.post(
        "/api/simulator/disruptions",
        headers=headers,
        json={
            "trip_id": trip_id,
            "kind": "flight_delay",
            "delay_minutes": 225,
            "auto_generate_plans": False,
        },
    )
    assert injected.status_code == 200, injected.text
    assert injected.json()["disruption"]["cycle"] == 1


def test_reset_requires_a_manager_or_admin(client) -> None:
    traveller = auth_headers(client, "traveller@retryp.example")
    trip_id = _build_trip(client, traveller, disrupt=False)
    response = client.post(f"/api/trips/{trip_id}/reset", headers=traveller)
    assert response.status_code == 403


def test_blank_target_defaults_to_the_first_disruptable_segment(client) -> None:
    """An operator can inject a scenario without picking a booking."""
    headers = auth_headers(client, "ops@retryp.example")
    trip_id = _build_trip(client, headers, disrupt=False)

    injected = client.post(
        "/api/simulator/disruptions",
        headers=headers,
        json={"trip_id": trip_id, "kind": "flight_delay", "delay_minutes": 225, "auto_generate_plans": True},
    )
    assert injected.status_code == 200, injected.text
    body = injected.json()
    assert body["disruption"]["segment_id"] is not None
    assert body["plans"], "the default target must still produce recovery plans"
