"""Tests for RailRadar live Indian Railways provider and options integration."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from app.config import Settings
from app.domain.enums import SegmentType
from app.providers.options import search_recovery_options
from app.providers.railradar import RailRadarProvider, _map_to_ir_code, _map_to_retryp_code

SAMPLE_RAILRADAR_RESPONSE = {
    "success": True,
    "data": {
        "from": {"code": "MAS", "name": "MGR Chennai Central", "departure": "18:15"},
        "to": {"code": "NDLS", "name": "New Delhi", "arrival": "05:10"},
        "trains": [
            {
                "train": {
                    "number": "12615",
                    "name": "Grand Trunk Express",
                    "type": "Superfast Express",
                    "runDays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                },
                "from": {
                    "code": "MAS",
                    "name": "MGR Chennai Central",
                    "departure": "18:15",
                    "day": 1,
                },
                "to": {
                    "code": "NDLS",
                    "name": "New Delhi",
                    "arrival": "05:10",
                    "day": 3,
                },
                "distance": 2183,
                "duration": 2095,
                "live": {
                    "type": "running",
                    "delayMinutes": 15,
                    "platform": "4",
                },
            }
        ],
    },
}


def test_station_code_mapping():
    assert _map_to_ir_code("MAS_RS") == "MAS"
    assert _map_to_ir_code("MAA") == "MAS"
    assert _map_to_ir_code("NDLS") == "NDLS"
    assert _map_to_ir_code("DEL") == "NDLS"
    assert _map_to_ir_code("SC_RS") == "SC"
    assert _map_to_ir_code("HYD") == "SC"
    assert _map_to_ir_code("SBC_RS") == "SBC"
    assert _map_to_ir_code("BLR") == "SBC"

    assert _map_to_retryp_code("MAS", "FALLBACK") == "MAS_RS"
    assert _map_to_retryp_code("NDLS", "FALLBACK") == "NDLS"


def test_railradar_configuration():
    s_empty = Settings(railradar_api_key="", indianrailway="")
    p_empty = RailRadarProvider(s_empty)
    assert not p_empty.is_configured

    s_key = Settings(railradar_api_key="rg_test_key_123")
    p_key = RailRadarProvider(s_key)
    assert p_key.is_configured
    assert p_key._api_key == "rg_test_key_123"

    s_alias = Settings(indianrailway="rg_alias_key_456")
    p_alias = RailRadarProvider(s_alias)
    assert p_alias.is_configured
    assert p_alias._api_key == "rg_alias_key_456"


@pytest.mark.asyncio
async def test_railradar_search_trains_success():
    settings = Settings(railradar_api_key="rg_test_key")
    provider = RailRadarProvider(settings)

    mock_resp = httpx.Response(
        200,
        json=SAMPLE_RAILRADAR_RESPONSE,
        request=httpx.Request("GET", "https://api.railradar.in/v1/trains/between/MAS/NDLS"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        after_utc = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
        results = await provider.search_trains_between("MAS_RS", "NDLS", after_utc)

        assert len(results) == 1
        train = results[0]
        assert train.segment_type == SegmentType.TRAIN
        assert train.carrier_code == "IR"
        assert "12615" in train.service_number
        assert "Grand Trunk" in train.service_number
        assert train.provenance == "LIVE"
        assert "Platform 4" in train.note
        assert "late by 15m" in train.note
        assert train.currency == "INR"
        assert train.distance_km == 2183.0


@pytest.mark.asyncio
async def test_railradar_handles_errors_gracefully():
    settings = Settings(railradar_api_key="rg_test_key")
    provider = RailRadarProvider(settings)

    # 401 Unauthorized
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(
            401,
            json={"success": False, "error": "Unauthorized"},
            request=httpx.Request("GET", "https://api.railradar.in/v1/trains/between/MAS/NDLS"),
        )
        after_utc = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
        assert await provider.search_trains_between("MAS_RS", "NDLS", after_utc) == []

    # Network Exception
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        assert await provider.search_trains_between("MAS_RS", "NDLS", after_utc) == []


@pytest.mark.asyncio
async def test_search_recovery_options_includes_live_rail():
    settings = Settings(railradar_api_key="rg_test_key")
    after_utc = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)

    mock_resp = httpx.Response(
        200,
        json=SAMPLE_RAILRADAR_RESPONSE,
        request=httpx.Request("GET", "https://api.railradar.in/v1/trains/between/MAS/NDLS"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        options = await search_recovery_options(
            settings,
            origin="MAS_RS",
            destination="NDLS",
            depart_after_utc=after_utc,
        )

        train_options = [o for o in options if o.segment_type.value == "train"]
        assert len(train_options) >= 1
        live_trains = [o for o in train_options if o.provenance == "LIVE"]
        assert len(live_trains) >= 1
        assert "12615" in live_trains[0].service_number
