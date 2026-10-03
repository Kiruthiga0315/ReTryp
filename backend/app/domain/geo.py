"""Great-circle distance, used for EU261 bands and MCT sanity checks."""

from __future__ import annotations

import math

from .reference import require_place

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def distance_between_places(origin_code: str, destination_code: str) -> float:
    """Great-circle distance in km between two reference places."""
    a = require_place(origin_code)
    b = require_place(destination_code)
    return haversine_km(a.lat, a.lon, b.lat, b.lon)


def route_distance_km(legs: list[tuple[str, str]]) -> float:
    """Total great-circle distance for a multi-leg route."""
    return sum(distance_between_places(o, d) for o, d in legs)
