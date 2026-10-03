"""End-to-end recovery on a route outside the reference journey.

The specification's central promise is that ReTryp recovers any journey it can
source, not just the MAA-FRA-BER example. This builds an MAA-COK trip from the
provider's own schedule, injects a cancellation, and asserts a full recovery
cycle produces comparable plans that reach the destination.

MAA-COK is a single leg, so recovery has to find a whole replacement service
rather than just rebuild a connection. That is a different code path from the
two-leg reference journey and is worth pinning separately.
"""

from __future__ import annotations

from .conftest import CONNECTION_SERVICE as CONNECTION
from .conftest import LONG_HAUL_SERVICE as LONG_HAUL
from .conftest import TRIP_DATE
from .support import option_for
from .test_api import auth_headers

MAA_COK_SERVICE = "AI601"


def _single_leg_trip(client, headers) -> tuple[str, str]:
    first = option_for(client, headers, "MAA", "COK", MAA_COK_SERVICE, TRIP_DATE)

    payload = {
        "name": "Chennai to Kochi",
        "reason": "business",
        "origin": "MAA",
        "destination": "COK",
        "date": TRIP_DATE,
        "segments": [
            {
                "service_key": first["key"],
                "origin": "MAA",
                "destination": "COK",
                "date": TRIP_DATE,
                "mode": first["mode"],
            }
        ],
        "disrupted_service_key": first["key"],
        "disruption_kind": "flight_cancellation",
        "delay_minutes": 0,
    }
    built = client.post("/api/journey/build", headers=headers, json=payload)
    assert built.status_code == 201, built.text
    body = built.json()
    return body["trip"]["id"], first["key"]


def _single_leg_delay_trip(client, headers, delay_minutes: int = 225) -> str:
    """A one-leg trip whose only flight is delayed.

    There is no downstream connection to break, so this is the shape that used
    to produce zero plans: the traveller is stranded at the origin and the leg
    itself has to be recovered.
    """
    first = option_for(client, headers, "MAA", "COK", MAA_COK_SERVICE, TRIP_DATE)
    payload = {
        "name": "Chennai to Kochi (delayed)",
        "reason": "business",
        "origin": "MAA",
        "destination": "COK",
        "date": TRIP_DATE,
        "segments": [
            {
                "service_key": first["key"],
                "origin": "MAA",
                "destination": "COK",
                "date": TRIP_DATE,
                "mode": first["mode"],
            }
        ],
        "disrupted_service_key": first["key"],
        "disruption_kind": "flight_delay",
        "delay_minutes": delay_minutes,
    }
    built = client.post("/api/journey/build", headers=headers, json=payload)
    assert built.status_code == 201, built.text
    return built.json()["trip"]["id"]


def test_single_leg_builds_from_a_real_schedule(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id, _ = _single_leg_trip(client, headers)
    trip = client.get(f"/api/trips/{trip_id}", headers=headers)
    assert trip.status_code == 200, trip.text
    segments = trip.json()["trip"]["segments"]
    assert len(segments) == 1
    assert segments[0]["origin"]["code"] == "MAA"
    assert segments[0]["destination"]["code"] == "COK"
    assert segments[0]["provenance"] == "LIVE"


def test_cancellation_on_a_single_leg_produces_recovery_plans(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id, _ = _single_leg_trip(client, headers)

    plans = client.get(f"/api/trips/{trip_id}/recovery", headers=headers)
    assert plans.status_code == 200, plans.text
    rows = plans.json()["plans"]
    assert rows, "a cancellation must produce at least one recovery plan"

    for plan in rows:
        assert plan["arrival_utc"], "every plan must reach the destination"
        assert plan["segments"], "every plan must carry its replacement legs"


def test_recovery_reaches_the_destination_market(client) -> None:
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id, _ = _single_leg_trip(client, headers)
    rows = client.get(f"/api/trips/{trip_id}/recovery", headers=headers).json()["plans"]
    # Every replacement leg must arrive into the trip's final market, not just
    # somewhere nearby; a plan that strands the traveller is not a plan.
    for plan in rows:
        last = plan["segments"][-1]
        assert last["destination_code"] == "COK"


def test_delay_on_a_single_leg_still_produces_recovery_plans(client) -> None:
    """A delayed last leg has no connection to break, but still needs recovery.

    Regression: the target finder returned ``None`` whenever no downstream
    connection broke, so a one-leg (or final-leg) delay produced zero plans and
    the Recovery Center dead-ended.
    """
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = _single_leg_delay_trip(client, headers)

    body = client.get(f"/api/trips/{trip_id}/recovery", headers=headers).json()
    assert body["empty_reason"] is None
    assert len(body["plans"]) >= 1, "a delayed single leg must offer a recovery"

    for plan in body["plans"]:
        assert plan["segments"], "a replacement plan must carry its legs"
        assert plan["segments"][-1]["destination_code"] == "COK"
        # The disrupted service is not a recovery from itself.
        for segment in plan["segments"]:
            assert segment["service_number"] != MAA_COK_SERVICE


def test_absorbed_delay_offers_to_keep_the_itinerary(client) -> None:
    """A small delay that the connection absorbs yields one honest plan.

    The traveller should be told the rest of the journey stands, and the plan's
    arrival must be the real projected arrival, not the scheduled arrival with
    the delay counted a second time.
    """
    headers = auth_headers(client, "traveller@retryp.example")
    trip_id, _ = _two_leg_trip(client, headers, delay_minutes=30)

    body = client.get(f"/api/trips/{trip_id}/recovery", headers=headers).json()
    assert len(body["plans"]) == 1
    plan = body["plans"][0]
    assert plan["title"] == "Keep the existing itinerary"
    assert plan["segments"] == []
    assert plan["arrival_delta_minutes"] == 0
    assert plan["recommended"] is True


def _two_leg_trip(client, headers, *, delay_minutes: int) -> tuple[str, str]:
    long_haul = option_for(client, headers, "MAA", "FRA", LONG_HAUL, TRIP_DATE)
    connection = option_for(client, headers, "FRA", "BER", CONNECTION, TRIP_DATE)
    payload = {
        "name": "Reference Journey",
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
        "disrupted_service_key": long_haul["key"],
        "disruption_kind": "flight_delay",
        "delay_minutes": delay_minutes,
    }
    built = client.post("/api/journey/build", headers=headers, json=payload)
    assert built.status_code == 201, built.text
    return built.json()["trip"]["id"], long_haul["key"]
