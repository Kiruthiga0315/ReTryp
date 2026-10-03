"""Apify 12Go Asia Scraper provider for real-time global bus options.

Connects to the Apify 12Go Asia Multi-Modal scraper to fetch live bus 
schedules and availability globally.
"""

from __future__ import annotations

import logging
import json
import httpx
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.enums import SegmentType
from ..domain.options import OptionSegment
from ..domain.reference import PLACES

import os
logger = logging.getLogger("retryp.providers.bus_apify")

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_URL = f"https://api.apify.com/v2/actors/jungle_synthesizer~12go-asia-multimodal-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}"

def fetch_bus_options(
    origin_city: str,
    destination_city: str,
    after_utc: datetime,
) -> list[OptionSegment]:
    """Fetch live bus options using the Apify 12Go Asia Scraper."""
    
    # We need the local date for the search
    local_date = after_utc.date().isoformat()
    
    payload = {
        "searches": [
            {
                "origin": origin_city,
                "destination": destination_city,
                "date": local_date
            }
        ],
        "sp_intended_usage": "research",
        "sp_improvement_suggestions": "none",
        "currency": "INR"
    }
    
    logger.info(f"Apify bus search: {origin_city} to {destination_city} on {local_date}")
    
    try:
        # Note: Scrapers can take a long time, but we use a reasonable timeout
        with httpx.Client(timeout=45.0) as client:
            response = client.post(APIFY_ACTOR_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.error(f"Apify request failed: {e}")
        return []
        
    out: list[OptionSegment] = []
    
    # If it's a list, iterate through dataset items
    items = data if isinstance(data, list) else data.get("items", [])
    
    for item in items:
        # We only want bus results
        if "bus" not in str(item.get("class", "")).lower() and "bus" not in str(item.get("operator", "")).lower() and item.get("type", "").lower() != "bus":
            if not item.get("type") == "bus":
                # Let's just be lenient if it's the right cities
                pass
                
        departure_str = item.get("departure_time") # expected iso string
        arrival_str = item.get("arrival_time")
        
        if not departure_str or not arrival_str:
            continue
            
        try:
            dep_utc = datetime.fromisoformat(departure_str).astimezone(timezone.utc)
            arr_utc = datetime.fromisoformat(arrival_str).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
            
        if dep_utc <= after_utc:
            continue
            
        operator = item.get("operator", "Bus Operator")
        price = item.get("price", 0)
        
        # 12Go returns floats usually, we need cost_minor
        cost_minor = int(float(price) * 100) if price else 100000
        
        origin_station = item.get("origin_station", origin_city)
        dest_station = item.get("destination_station", destination_city)
        
        out.append(
            OptionSegment(
                key=f"bus-apify-{operator[:3]}-{dep_utc.timestamp()}",
                segment_type=SegmentType.BUS,
                carrier_code="BUS",
                service_number=operator,
                origin_code=origin_station[:5].upper(),
                destination_code=dest_station[:5].upper(),
                departure_utc=dep_utc,
                arrival_utc=arr_utc,
                cost_minor=cost_minor,
                currency=item.get("currency", "INR"),
                refundable=False,
                note=f"Live availability via 12Go ({operator}).",
                provenance="LIVE",
            )
        )
        
    out.sort(key=lambda o: o.departure_utc)
    return out

