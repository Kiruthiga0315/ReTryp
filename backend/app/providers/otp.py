"""OpenTripPlanner (OTP) provider for global multi-modal ground transit.

This module integrates with a self-hosted OpenTripPlanner instance 
loaded with global GTFS (General Transit Feed Specification) data.
OTP provides highly accurate, multi-modal itineraries (bus, rail, tram, walking)
across international boundaries.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings
from ..domain.enums import SegmentType
from ..domain.options import OptionSegment
from ..domain.reference import PLACES

logger = logging.getLogger("retryp.providers.otp")

# In production, this points to our internal OTP cluster
# e.g., http://otp-cluster.internal:8080/otp/routers/default
OTP_BASE_URL = "http://localhost:8080/otp/routers/default"

def get_otp_options(
    origin_city: str,
    destination_city: str,
    after_utc: datetime,
    limit: int = 5,
) -> list[OptionSegment]:
    """Query OpenTripPlanner for ground transit options."""
    
    orig_place = PLACES.get(origin_city)
    dest_place = PLACES.get(destination_city)
    
    if not orig_place or not dest_place:
        logger.warning(f"OTP routing requires valid places. Unknown: {origin_city} -> {destination_city}")
        return []

    # OTP requires lat/lon for routing
    fromPlace = f"{orig_place.lat},{orig_place.lon}"
    toPlace = f"{dest_place.lat},{dest_place.lon}"
    
    # Format times for OTP query
    date_str = after_utc.strftime("%Y-%m-%d")
    time_str = after_utc.strftime("%H:%M")
    
    query_params = {
        "fromPlace": fromPlace,
        "toPlace": toPlace,
        "date": date_str,
        "time": time_str,
        "mode": "TRANSIT,WALK", # Request global GTFS transit
        "maxWalkDistance": 1000,
        "arriveBy": "false",
        "numItineraries": limit
    }
    
    url = f"{OTP_BASE_URL}/plan?{urllib.parse.urlencode(query_params)}"
    logger.info(f"Querying OpenTripPlanner: {url}")
    
    results: list[OptionSegment] = []
    
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            # If our OTP cluster is offline during the demo, return empty gracefully
            if resp.status_code != 200:
                logger.warning(f"OTP returned {resp.status_code}")
                return []
                
            data = resp.json()
            
            # OTP returns an array of itineraries
            itineraries = data.get("plan", {}).get("itineraries", [])
            
            for idx, itin in enumerate(itineraries):
                # OTP times are epoch milliseconds
                start_time_ms = itin.get("startTime", 0)
                end_time_ms = itin.get("endTime", 0)
                
                if not start_time_ms or not end_time_ms:
                    continue
                    
                dep_utc = datetime.fromtimestamp(start_time_ms / 1000.0, tz=timezone.utc)
                arr_utc = datetime.fromtimestamp(end_time_ms / 1000.0, tz=timezone.utc)
                
                # Extract the primary transit operator from the legs
                legs = itin.get("legs", [])
                transit_legs = [leg for leg in legs if leg.get("mode") in ("BUS", "RAIL", "TRAM", "SUBWAY")]
                
                if not transit_legs:
                    continue
                    
                primary_leg = transit_legs[0]
                operator = primary_leg.get("agencyName", "Global Transit")
                route_num = primary_leg.get("routeShortName", "")
                
                results.append(
                    OptionSegment(
                        key=f"otp-{orig_place.market}-{dest_place.market}-{start_time_ms}",
                        segment_type=SegmentType.BUS,
                        carrier_code="OTP",
                        service_number=f"{operator} {route_num}".strip(),
                        origin_code=origin_city,
                        destination_code=destination_city,
                        departure_utc=dep_utc,
                        arrival_utc=arr_utc,
                        cost_minor=200000, # OTP doesn't always have fares; use a fallback estimate
                        currency="INR",
                        refundable=False,
                        note=f"Routed via OpenTripPlanner ({len(transit_legs)} transfers)",
                        provenance="LIVE",
                    )
                )
    except Exception as e:
        logger.warning(f"OTP cluster unreachable: {e}. Ensure GTFS data is loaded and server is running.")
        
    return results
