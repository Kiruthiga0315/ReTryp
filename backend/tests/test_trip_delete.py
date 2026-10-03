"""Trip deletion contract tests.

Deleting a trip removes everything derived from it, only the owner or an
administrator may do it, and a journey that is mid-recovery cannot be
discarded while a plan is being decided.
"""

from __future__ import annotations

from .conftest import CONNECTION_SERVICE, LONG_HAUL_SERVICE, TRIP_DATE
from .support import option_for
from .test_api import auth_headers


def _build(client, headers, *, name: str = "Deletable journey", delay: int = 0) -> str:
    long_haul = option_for(client, headers, "MAA", "FRA", LONG_HAUL_SERVICE, TRIP_DATE)
    connection = option_for(client, headers, "FRA", "BER", CONNECTION_SERVICE, TRIP_DATE)

    payload = {
        "name": name,
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
    if delay:
        payload["disrupted_service_key"] = long_haul["key"]
        payload["disruption_kind"] = "flight_delay"
        payload["delay_minutes"] = delay
    response = client.post("/api/journey/build", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["trip"]["id"]


def test_owner_can_delete_a_trip_and_its_records(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = _build(client, headers)

    response = client.delete(f"/api/trips/{trip_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    assert client.get(f"/api/trips/{trip_id}", headers=headers).status_code == 404

    listed = client.get("/api/trips", headers=headers).json()["trips"]
    assert all(trip["id"] != trip_id for trip in listed)


def test_delete_is_scoped_to_the_owner(client) -> None:
    traveller = auth_headers(client, "traveller@retryp.example")
    trip_id = _build(client, traveller, name="Traveller only")

    # A second traveller, unrelated to the trip, must not be able to remove it.
    created = client.post(
        "/api/auth/signup",
        json={
            "email": "other-traveller@retryp.example",
            "password": "Retryp-Test-2026",
            "full_name": "Other Traveller",
            "role": "traveller",
        },
    )
    assert created.status_code == 201, created.text
    signed_in = client.post(
        "/api/auth/signin",
        json={"email": "other-traveller@retryp.example", "password": "Retryp-Test-2026"},
    ).json()
    other = {"Authorization": f"Bearer {signed_in['token']}"}

    response = client.delete(f"/api/trips/{trip_id}", headers=other)
    assert response.status_code == 404, response.text
    # The trip is still there for its owner.
    assert client.get(f"/api/trips/{trip_id}", headers=traveller).status_code == 200


def test_delete_is_refused_while_a_recovery_is_in_progress(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = _build(client, headers, name="Mid recovery", delay=225)

    response = client.delete(f"/api/trips/{trip_id}", headers=headers)
    assert response.status_code == 409, response.text
    assert "recovery" in response.json()["detail"].lower()


def test_delete_records_an_audit_entry(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = _build(client, headers, name="Audited removal")

    assert client.delete(f"/api/trips/{trip_id}", headers=headers).status_code == 200

    manager = auth_headers(client, "manager@retryp.example")
    audit = client.get(
        "/api/audit", params={"action": "trip.deleted", "limit": 100}, headers=manager
    )
    assert audit.status_code == 200, audit.text
    entries = audit.json()["entries"]
    assert entries, "deleting a trip must leave an audit entry"
    assert all(entry["action"] == "trip.deleted" for entry in entries)
