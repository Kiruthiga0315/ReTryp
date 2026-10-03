"""Shared fixtures.

Domain tests need no database. API contract tests run against a temporary
SQLite database with the application's user accounts bootstrapped, and a
journey built through the real Journey Builder so the app is exercised the
same way it runs locally.

There is no demo catalogue and the tests never call a live provider. Provider
boundaries are replaced by :mod:`tests.support` with fixed synthetic schedules
that carry ``LIVE`` provenance, so the pipeline downstream of the provider
(parsing, merging, connections, planning, scoring, execution, the API shapes)
is the real code. See :mod:`tests.support` for why that boundary is the only
one doubled.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

# Point the app at a throwaway database before importing it. The settings
# object is read at import time, so this must happen first.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="retryp-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ["DATA_MODE"] = "real"
os.environ["BOOTSTRAP_PASSWORD"] = "Retryp-Test-2026"

# Tests must be deterministic and offline. A developer's .env may hold live
# provider keys; blanking them here keeps every test on the synthetic provider
# doubles and the downloaded timetable, so no request leaves the machine.
for _key in (
    "AERODATABOX_API_KEY",
    "AVIATIONSTACK_API_KEY",
    "FLIGHTAWARE_API_KEY",
    "AMADEUS_CLIENT_ID",
    "AMADEUS_CLIENT_SECRET",
    "TRANSITLAND_API_KEY",
    "LLM_API_KEY",
):
    os.environ[_key] = ""
os.environ["FLIGHT_PROVIDER"] = "aerodatabox"
# The provider doubles are installed at the boundary, so a key must appear
# present for the factory to select a real provider class rather than the
# unconfigured placeholder.
os.environ["AERODATABOX_API_KEY"] = "test-key"
os.environ["FX_ENABLED"] = "false"

TEST_PASSWORD = "Retryp-Test-2026"

# The fixed journey the fixture builds. Times come from the synthetic schedule:
# MAA-FRA departs 20:25Z and arrives 06:10Z, and FRA-BER departs 07:50Z, a 100
# minute buffer at Frankfurt. A 225 minute delay breaks that connection.
TRIP_DATE = "2026-09-28"
LONG_HAUL_SERVICE = "LH759"
CONNECTION_SERVICE = "LH1004"
DELAY_MINUTES = 225


@pytest.fixture(scope="session")
def provider_doubles() -> Iterator[None]:
    """Install the synthetic provider schedules for the whole session."""
    from tests.support import install_provider_doubles

    mp = pytest.MonkeyPatch()
    install_provider_doubles(mp)
    yield
    mp.undo()


@pytest.fixture(scope="session")
def client(provider_doubles: None) -> Iterator:
    """Accounts bootstrapped, one reference journey built with a disruption."""
    from fastapi.testclient import TestClient

    from app import bootstrap
    from app.main import app

    bootstrap.main([])

    with TestClient(app) as test_client:
        _prefer_inr(test_client)
        _build_reference_journey(test_client)
        yield test_client


def _prefer_inr(client) -> None:
    """Give the test traveller a non-EUR display currency.

    History totals then have to be converted, which is what the currency tests
    check. This goes through the real settings endpoint.
    """
    traveller = _sign_in(client, "traveller@retryp.example")
    headers = {"Authorization": f"Bearer {traveller['token']}"}
    response = client.patch(
        "/api/auth/settings", headers=headers, json={"currency": "INR"}
    )
    assert response.status_code == 200, response.text


def _sign_in(client, email: str, password: str = TEST_PASSWORD) -> dict:
    response = client.post("/api/auth/signin", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _build_reference_journey(client) -> None:
    """Build the reference trip through the real builder endpoints."""
    traveller = _sign_in(client, "traveller@retryp.example")
    headers = {"Authorization": f"Bearer {traveller['token']}"}

    def options(origin: str, destination: str) -> list[dict]:
        response = client.get(
            "/api/journey/options",
            headers=headers,
            params={"origin": origin, "destination": destination, "date": TRIP_DATE},
        )
        assert response.status_code == 200, response.text
        return response.json()["options"]

    long_haul = next(
        o for o in options("MAA", "FRA") if o["service_number"] == LONG_HAUL_SERVICE
    )
    connection = next(
        o for o in options("FRA", "BER") if o["service_number"] == CONNECTION_SERVICE
    )

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
        "delay_minutes": DELAY_MINUTES,
    }
    response = client.post("/api/journey/build", headers=headers, json=payload)
    assert response.status_code == 201, response.text


@pytest.fixture()
def utc() -> callable:
    return lambda *args: datetime(*args, tzinfo=timezone.utc)
