"""API contract tests.

Run against a seeded SQLite database. They pin the request/response shapes the
frontend depends on, the role-based access rules, and the honest execution
states (nothing is ever reported as a real airline rebooking).
"""

from __future__ import annotations

from .conftest import TEST_PASSWORD


def sign_in(client, email: str, password: str = TEST_PASSWORD) -> dict:
    response = client.post("/api/auth/signin", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(client, email: str) -> dict:
    token = sign_in(client, email)["token"]
    return {"Authorization": f"Bearer {token}"}


def first_trip_id(client, headers: dict) -> str:
    response = client.get("/api/trips", headers=headers)
    assert response.status_code == 200, response.text
    trips = response.json()["trips"]
    assert trips, "the seed must create at least one trip"
    return trips[0]["id"]


def test_health_needs_no_authentication(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "data_status" in body


def test_protected_endpoint_rejects_anonymous_callers(client) -> None:
    # The shared client carries a session cookie from the fixture sign-ins;
    # drop it so this request is genuinely anonymous.
    client.cookies.clear()
    response = client.get("/api/trips")
    assert response.status_code == 401


def test_signin_returns_user_and_token(client) -> None:
    body = sign_in(client, "traveller@retryp.example")
    assert body["user"]["email"] == "traveller@retryp.example"
    assert body["user"]["role"] == "traveller"
    assert body["token"]


def test_signin_rejects_a_wrong_password(client) -> None:
    response = client.post(
        "/api/auth/signin", json={"email": "traveller@retryp.example", "password": "wrong"}
    )
    assert response.status_code == 401


def test_trip_payload_carries_provenance_and_local_zones(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, headers)

    response = client.get(f"/api/trips/{trip_id}/timeline", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    segments = body["segments"]
    assert len(segments) >= 2
    for segment in segments:
        assert segment["provenance"] in {"LIVE", "CACHED", "REFERENCE", "SIMULATED"}
        scheduled = segment["scheduled_departure_local"]
        # Times are rendered in the airport's own zone; the reference journey
        # touches MAA (IST, UTC+5:30) and Frankfurt/Berlin (CEST, UTC+2).
        assert any(zone in scheduled for zone in ("IST", "CEST", "CET"))


def test_dashboard_reports_the_active_disruption(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, headers)

    response = client.get(f"/api/trips/{trip_id}/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["trip"]
    assert body["trip"]["reference"]
    assert body["active_disruption"] is not None
    assert body["active_disruption"]["provenance"] == "SIMULATED"


def test_recovery_center_returns_three_or_more_comparable_plans(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, headers)

    response = client.get(f"/api/trips/{trip_id}/recovery", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disruption"] is not None
    assert len(body["plans"]) >= 3
    assert body["recommended_plan_id"] in {p["plan_id"] for p in body["plans"]}

    # The comparison table must line up with the plan cards.
    assert len(body["comparison"]) == len(body["plans"])

    for plan in body["plans"]:
        assert plan["additional_cost_display"]
        assert plan["arrival_delta_display"]
        assert plan["risk_level"] in {"low", "medium", "high"}
        assert plan["connection_safety"] in {"safe", "tight", "at_risk", "broken"}
        assert plan["compensation"]["outcome"]
        assert plan["provenance"] in {"LIVE", "CACHED", "REFERENCE", "SIMULATED"}


def test_plan_detail_is_reachable_from_the_center(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, headers)
    plans = client.get(f"/api/trips/{trip_id}/recovery", headers=headers).json()["plans"]
    plan_id = plans[0]["plan_id"]

    response = client.get(f"/api/plans/{plan_id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["plan_id"] == plan_id
    assert "original_itinerary" in body and "recovered_itinerary" in body
    assert body["original_itinerary"] and body["recovered_itinerary"]


def test_approval_requires_explicit_confirmation(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, headers)
    plans = client.get(f"/api/trips/{trip_id}/recovery", headers=headers).json()["plans"]
    plan_id = plans[0]["plan_id"]

    unconfirmed = client.post(
        f"/api/plans/{plan_id}/approve",
        json={"plan_id": plan_id, "confirmation": False},
        headers=headers,
    )
    assert unconfirmed.status_code == 400


def test_simulator_is_admin_only(client) -> None:
    traveller = auth_headers(client, "traveller@retryp.example")
    trip_id = first_trip_id(client, traveller)
    response = client.post(
        "/api/simulator/disruptions",
        json={"trip_id": trip_id, "kind": "flight_delay", "delay_minutes": 30},
        headers=traveller,
    )
    assert response.status_code == 403


def test_simulator_lists_injectable_kinds(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.get("/api/simulator/scenarios", headers=headers)
    assert response.status_code == 200
    kinds = {k["value"] for k in response.json()["kinds"]}
    assert {"flight_delay", "flight_cancellation", "weather", "visa_transit_restriction"} <= kinds


def test_inject_then_approve_then_execute_is_honest(client) -> None:
    """The full cycle: inject a disruption, approve a plan, apply it.

    Execution must never claim a real ticket was rebooked.
    """
    admin = auth_headers(client, "ops@retryp.example")
    trip_id = first_trip_id(client, admin)

    # Target the long-haul leg and delay it, as the acceptance scenario does.
    # The FRA -> BER connection then breaks and recovery rebuilds that leg.
    timeline = client.get(f"/api/trips/{trip_id}/timeline", headers=admin).json()
    segment_id = timeline["segments"][0]["id"]

    injected = client.post(
        "/api/simulator/disruptions",
        json={
            "trip_id": trip_id,
            "kind": "flight_delay",
            "segment_id": segment_id,
            "delay_minutes": 225,
            "auto_generate_plans": True,
        },
        headers=admin,
    )
    assert injected.status_code == 200, injected.text
    plans = injected.json()["plans"]
    assert len(plans) >= 3

    plan_id = plans[0]["plan_id"]
    approved = client.post(
        f"/api/plans/{plan_id}/approve",
        json={"plan_id": plan_id, "confirmation": True},
        headers=admin,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["plan"]["status"] == "approved"

    executed = client.post(f"/api/plans/{plan_id}/execute", headers=admin)
    assert executed.status_code == 200, executed.text
    body = executed.json()["plan"]
    assert body["status"] == "executed"

    # Honest states only.
    allowed = {
        "recorded_offline",
        "change_requested",
        "pending_provider_confirmation",
        "cancelled",
        "unchanged",
    }
    for action in body["actions"]:
        assert action["status"] in allowed


def test_audit_log_is_manager_only_and_enriches_the_actor(client) -> None:
    traveller = auth_headers(client, "traveller@retryp.example")
    forbidden = client.get("/api/audit", headers=traveller)
    assert forbidden.status_code == 403

    admin = auth_headers(client, "ops@retryp.example")
    response = client.get("/api/audit", headers=admin)
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert entries
    assert any(entry.get("actor_name") for entry in entries)


def test_notifications_are_readable_and_markable(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    listed = client.get("/api/notifications", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] >= 1
    assert body["notifications"][0]["body"]

    marked = client.post("/api/notifications/read", json={"all": True}, headers=headers)
    assert marked.status_code == 200
    after = client.get("/api/notifications", headers=headers).json()
    assert after["unread_count"] == 0


def test_provider_health_reports_fallback_without_keys(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    response = client.get("/api/providers/health", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "providers" in body
