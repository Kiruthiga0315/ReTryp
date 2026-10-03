"""Rail stations and bus stops from OpenStreetMap Overpass.

The reference artifact already holds every airport with an IATA code. It holds
no rail stations or bus stops, because those have no equivalent global code
list. This module fills that gap from OpenStreetMap:

* ``railway=station`` and ``railway=halt`` for rail stations.
* ``highway=bus_stop`` and ``public_transport=stop_position`` for bus stops.

Two honesty rules apply, and they matter more here than anywhere else:

* A node's **presence** is real and comes from OSM, badged ``REFERENCE`` with
  its fetch time. A node's **timetable** is not: OSM has no departure times.
  A station found here never becomes a bookable service on its own.
* Overpass is donated infrastructure with a published usage policy. Queries
  are radius-bounded, cached to disk, and rate-limited to one in flight at a
  time. There is no bulk planet download in this build.

Results are cached under ``data/cache/`` so a repeated search costs nothing
and the app still answers when Overpass is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..config import Settings

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
USER_AGENT = "ReTryp/1.0 (+https://retryp.example)"

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# The public instance asks that clients stay modest. One query at a time and a
# small radius keep this inside the policy.
_QUERY_LOCK = asyncio.Lock()
_MIN_INTERVAL_SECONDS = 2.0
_last_query_at = 0.0

# Node presence changes slowly, so a long cache TTL is appropriate.
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_RADIUS_KM = 60.0


@dataclass(frozen=True, slots=True)
class TransitNode:
    osm_id: str
    name: str
    kind: str  # rail | bus
    lat: float
    lon: float
    operator: str | None = None
    network: str | None = None
    country: str | None = None


def _cache_path(lat: float, lon: float, radius_km: float) -> Path:
    key = f"{lat:.3f}_{lon:.3f}_{radius_km:.0f}"
    return CACHE_DIR / f"osm_transit_{key}.json"


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("stored_at", 0) > CACHE_TTL_SECONDS:
        return None
    return payload


def _cached_near(lat: float, lon: float, radius_km: float) -> dict | None:
    """The closest stored harvest that covers this point.

    A map click rarely lands on a previously cached centre, so a miss on the
    exact key is expected. Any cached harvest whose own radius reaches the
    point can still answer, filtered to the requested radius.
    """
    best: tuple[float, dict] | None = None
    for path in CACHE_DIR.glob("osm_transit_*.json"):
        parts = path.stem.split("_")
        if len(parts) < 5:
            continue
        try:
            clat, clon, cradius = float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            continue
        separation = haversine_km(lat, lon, clat, clon)
        if separation > cradius:
            continue
        if best is None or separation < best[0]:
            payload = _read_cache(path)
            if payload is not None:
                best = (separation, payload)
    if best is None:
        return None

    payload = best[1]
    nodes = [
        row
        for row in payload.get("nodes", [])
        if haversine_km(lat, lon, float(row["lat"]), float(row["lon"])) <= radius_km
    ]
    return {"payload": payload, "nodes": nodes}


def build_query(lat: float, lon: float, radius_m: int) -> str:
    """A radius-bounded Overpass query for rail stations and bus stops."""
    return f"""[out:json][timeout:25];
(
  node["railway"~"^(station|halt)$"](around:{radius_m},{lat},{lon});
  node["highway"="bus_stop"](around:{radius_m},{lat},{lon});
  node["public_transport"="station"](around:{radius_m},{lat},{lon});
);
out body 200;"""


def parse_overpass(payload: dict) -> list[TransitNode]:
    """Overpass elements to typed nodes. Untagged ways are skipped."""
    nodes: list[TransitNode] = []
    for element in payload.get("elements", []):
        if element.get("type") != "node":
            continue
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("ref") or ""
        if not name:
            # An unnamed stop cannot be shown to a traveller meaningfully.
            continue
        railway = tags.get("railway")
        if railway in {"station", "halt"}:
            kind = "rail"
        elif tags.get("highway") == "bus_stop" or tags.get("public_transport") == "stop_position":
            kind = "bus"
        elif tags.get("public_transport") == "station":
            kind = "rail" if tags.get("train") == "yes" else "bus"
        else:
            continue
        nodes.append(
            TransitNode(
                osm_id=f"{element.get('type')}/{element.get('id')}",
                name=name,
                kind=kind,
                lat=float(element.get("lat", 0.0)),
                lon=float(element.get("lon", 0.0)),
                operator=tags.get("operator"),
                network=tags.get("network"),
            )
        )
    return nodes


async def _query_overpass(query: str) -> dict:
    """Post one query, trying each public endpoint in turn."""
    global _last_query_at
    async with _QUERY_LOCK:
        elapsed = time.monotonic() - _last_query_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            await asyncio.sleep(_MIN_INTERVAL_SECONDS - elapsed)

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=20) as http:
            for endpoint in OVERPASS_ENDPOINTS:
                try:
                    response = await http.post(
                        endpoint,
                        data={"data": query},
                        headers={"User-Agent": USER_AGENT},
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = RuntimeError(f"Overpass {response.status_code}")
                        continue
                    response.raise_for_status()
                    _last_query_at = time.monotonic()
                    return response.json()
                except Exception as exc:  # noqa: BLE001 - provider boundary
                    last_error = exc
                    continue
        _last_query_at = time.monotonic()
        raise RuntimeError(f"Overpass unavailable: {last_error}")


async def transit_near(
    settings: Settings, *, lat: float, lon: float, radius_km: float = 25.0
) -> dict:
    """Rail stations and bus stops near a coordinate.

    Returns nodes with their provenance and the fetch time, or an empty result
    with a note when Overpass is unreachable. Never raises: the caller shows an
    honest empty state instead of failing the screen.
    """
    radius_km = max(1.0, min(radius_km, MAX_RADIUS_KM))
    radius_m = int(radius_km * 1000)
    path = _cache_path(lat, lon, radius_km)

    cached = _read_cache(path)
    if cached is not None:
        nodes = [TransitNode(**row) for row in cached.get("nodes", [])]
        return {
            "nodes": nodes,
            "provenance": "CACHED",
            "fetched_at": cached.get("fetched_at"),
            "source": cached.get("source", "OpenStreetMap contributors (ODbL)"),
            "radius_km": radius_km,
            "notes": ["Served from the local OpenStreetMap cache."],
        }

    try:
        payload = await _query_overpass(build_query(lat, lon, radius_m))
    except Exception as exc:  # noqa: BLE001 - provider boundary
        fallback = _cached_near(lat, lon, radius_km)
        if fallback is not None:
            stored = fallback["payload"]
            return {
                "nodes": [TransitNode(**row) for row in fallback["nodes"]],
                "provenance": "CACHED",
                "fetched_at": stored.get("fetched_at"),
                "source": stored.get("source", "OpenStreetMap contributors (ODbL)"),
                "radius_km": radius_km,
                "notes": [
                    "OpenStreetMap is not answering, so this is a stored harvest "
                    "nearby, not a fresh one."
                ],
            }
        return {
            "nodes": [],
            "provenance": "UNAVAILABLE",
            "fetched_at": None,
            "source": "OpenStreetMap contributors (ODbL)",
            "radius_km": radius_km,
            "notes": [
                "OpenStreetMap is not answering and nothing is stored for this "
                "area. No stations are shown rather than approximated."
            ],
        }

    nodes = parse_overpass(payload)
    fetched_at = datetime.now(timezone.utc).isoformat()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(
                {
                    "stored_at": time.time(),
                    "fetched_at": fetched_at,
                    "source": "OpenStreetMap contributors (ODbL), via Overpass",
                    "nodes": [
                        {
                            "osm_id": n.osm_id,
                            "name": n.name,
                            "kind": n.kind,
                            "lat": n.lat,
                            "lon": n.lon,
                            "operator": n.operator,
                            "network": n.network,
                            "country": n.country,
                        }
                        for n in nodes
                    ],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # A cache write failure must not fail the request.

    return {
        "nodes": nodes,
        "provenance": "REFERENCE",
        "fetched_at": fetched_at,
        "source": "OpenStreetMap contributors (ODbL), via Overpass",
        "radius_km": radius_km,
        "notes": [
            "Station and stop locations come from OpenStreetMap. Timetables are "
            "not part of OpenStreetMap, so these are places, not bookable services."
        ],
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def summarise(nodes: list[TransitNode]) -> dict:
    """Counts by kind, for the honest coverage readout."""
    rails = sum(1 for n in nodes if n.kind == "rail")
    buses = sum(1 for n in nodes if n.kind == "bus")
    return {"rail": rails, "bus": buses, "total": len(nodes)}
