"""Universal connectivity graph over the loaded reference data.

ReTryp has to answer "how can I get from anywhere to anywhere". This module
turns the loaded datasets into an undirected graph and provides the lookups the planner needs:

* :func:`is_served` - is there a known service between two places?
* :func:`neighbours` - which places does one place connect to?
* :func:`find_path` - a bounded multi-hop path, used when a leg is disrupted
  and no direct service exists.
* :func:`served_coverage` - what the graph can actually answer for, so the UI
  can be honest about extent.

Three edge sources are merged, each carrying its own provenance:

* ``REFERENCE`` - OpenFlights route pairs (global, but its vintage is old:
  routes that started after the dataset was last refreshed are absent).
* ``REFERENCE`` - the published GTFS rail timetable.
* ``LIVE`` - pairs confirmed by a configured schedule provider at query time
  (recorded in the in-process edge cache, never persisted as a claim).

Nothing here invents an edge. A pair with no source is reported as unserved.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

from . import rail
from .reference import PLACES, ROUTES, Place, require_place

# One hop limit for path search. Three legs is enough to bridge a hub and
# keeps the search bounded on a graph this size.
MAX_HOPS = 3


@dataclass(frozen=True, slots=True)
class Edge:
    origin: str
    destination: str
    modes: frozenset[str]
    provenance: str
    carriers: tuple[str, ...] = ()


@dataclass
class GraphStats:
    nodes: int = 0
    edges: int = 0
    flight_nodes: int = 0
    rail_nodes: int = 0
    live_pairs: int = 0
    sources: list[str] = field(default_factory=list)


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def _build() -> tuple[dict[str, set[str]], dict[str, tuple[str, ...]], GraphStats]:
    adjacency: dict[str, set[str]] = {}
    carriers: dict[str, tuple[str, ...]] = {}
    stats = GraphStats()

    for pair, codes in ROUTES.items():
        parts = pair.split("|")
        if len(parts) != 2:
            continue
        a, b = parts
        if a not in PLACES or b not in PLACES:
            continue
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
        carriers[_pair_key(a, b)] = tuple(codes)
        stats.edges += 1

    stats.flight_nodes = len(adjacency)

    if rail.RAIL_LOADED:
        for a, b in rail.RAIL_PAIRS:
            if a not in PLACES or b not in PLACES:
                continue
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
        stats.rail_nodes = len({c for pair in rail.RAIL_PAIRS for c in pair})

    from . import bus
    if bus.BUS_LOADED:
        for s in bus.SERVICES:
            a, b = s.origin, s.destination
            if a in PLACES and b in PLACES:
                adjacency.setdefault(a, set()).add(b)
                adjacency.setdefault(b, set()).add(a)
                stats.edges += 1

    # Cross-modal city links between airports and ground terminals
    for p_code, p_obj in PLACES.items():
        if p_obj.market and p_obj.market != p_code and p_obj.market in PLACES:
            adjacency.setdefault(p_code, set()).add(p_obj.market)
            adjacency.setdefault(p_obj.market, set()).add(p_code)

    stats.nodes = len(adjacency)
    stats.sources = []
    if ROUTES:
        stats.sources.append("OpenFlights route pairs")
    if rail.RAIL_LOADED:
        stats.sources.append("DELFI e.V. / GTFS.de & Indian Railways timetables")
    if bus.BUS_LOADED:
        stats.sources.append("Intercity Bus schedules")
    return adjacency, carriers, stats


_ADJACENCY, _CARRIERS, _STATS = _build()

# Pairs the schedule provider has answered for in this process. Held in memory
# only: it is evidence of what a provider returned, not a persisted claim.
_LIVE_PAIRS: set[str] = set()


def record_live_pair(origin: str, destination: str) -> None:
    """Remember that a provider confirmed service on a pair at query time."""
    _LIVE_PAIRS.add(_pair_key(origin, destination))


def is_live_pair(origin: str, destination: str) -> bool:
    return _pair_key(origin, destination) in _LIVE_PAIRS


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def is_served(origin: str, destination: str) -> bool:
    """Is there a known direct service between two places?"""
    if is_live_pair(origin, destination):
        return True
    try:
        a, b = require_place(origin).market, require_place(destination).market
    except KeyError:
        return False
    if a == b:
        return False
    # Accept any station in the same market, so a rail arrival at Berlin
    # Hauptbahnhof answers a search for BER.
    return any(
        require_place(n).market == b
        for n in _ADJACENCY.get(origin, ())
        if n in PLACES
    )


def neighbours(code: str) -> list[str]:
    """Every place directly reachable from ``code``."""
    return sorted(_ADJACENCY.get(code, ()))


def degree(code: str) -> int:
    return len(_ADJACENCY.get(code, ()))


def carriers_between(origin: str, destination: str) -> tuple[str, ...]:
    return _CARRIERS.get(_pair_key(origin, destination), ())


def hub_rank(limit: int = 10) -> list[tuple[str, int]]:
    """The best-connected places, used to suggest bridge airports."""
    ranked = sorted(_ADJACENCY.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [(code, len(peers)) for code, peers in ranked[:limit]]


def find_path(origin: str, destination: str, *, max_hops: int = MAX_HOPS) -> list[str] | None:
    """Shortest hop path between two places, or ``None`` if unconnected.

    Breadth-first, so the result is the fewest-hops route. Places are matched
    by market, so any station serving the destination city is a valid arrival.
    """
    if origin == destination:
        return [origin]
    try:
        target_market = require_place(destination).market
    except KeyError:
        return None
    if origin not in _ADJACENCY:
        return None

    queue: deque[list[str]] = deque([[origin]])
    seen = {origin}
    while queue:
        path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for nxt in _ADJACENCY.get(path[-1], ()):
            if nxt in seen:
                continue
            if nxt in PLACES and require_place(nxt).market == target_market:
                return [*path, nxt]
            seen.add(nxt)
            queue.append([*path, nxt])
    return None


def suggest_bridges(origin: str, destination: str, *, limit: int = 6) -> list[dict]:
    """Two-hop connections through a hub, for when no direct service exists.

    Returns the connecting places with the hop counts, so the UI can offer a
    concrete route instead of a bare "no service" message.
    """
    if origin not in _ADJACENCY:
        return []
    try:
        target_market = require_place(destination).market
    except KeyError:
        return []

    reached: dict[str, int] = {}
    frontier = {origin}
    for hop in (1, 2):
        nxt_frontier: set[str] = set()
        for node in frontier:
            for nxt in _ADJACENCY.get(node, ()):
                if nxt in reached or nxt == origin:
                    continue
                reached[nxt] = hop
                nxt_frontier.add(nxt)
        frontier = nxt_frontier

    bridges: list[dict] = []
    for node, hops in reached.items():
        if node not in PLACES or hops != 1:
            continue
        for onward in _ADJACENCY.get(node, ()):
            if onward in PLACES and require_place(onward).market == target_market:
                bridges.append(
                    {
                        "via": node,
                        "via_name": PLACES[node].name,
                        "via_city": PLACES[node].city,
                        "hops": 2,
                        "carriers": list(carriers_between(origin, node)),
                    }
                )
                break

    # Best-connected bridges first: fewer onward changes for the traveller.
    bridges.sort(key=lambda b: (-degree(b["via"]), b["via"]))
    return bridges[:limit]


def nearest_nodes(lat: float, lon: float, *, limit: int = 5, kinds: set[str] | None = None) -> list[dict]:
    """Closest places to a coordinate, for "gather everything near here"."""
    from .geo import haversine_km

    scored: list[tuple[float, Place]] = []
    for place in PLACES.values():
        if kinds and place.kind not in kinds:
            continue
        scored.append((haversine_km(lat, lon, place.lat, place.lon), place))
    scored.sort(key=lambda t: t[0])
    return [
        {
            "code": place.code,
            "name": place.name,
            "city": place.city,
            "country": place.country,
            "kind": place.kind,
            "distance_km": round(distance, 1),
            "lat": place.lat,
            "lon": place.lon,
        }
        for distance, place in scored[:limit]
    ]


def to_hub(code: str, hubs: list[str] | None = None, *, limit: int = 5) -> list[dict]:
    """Reachable hub airports from a place, cheapest-hops first.

    Used when a traveller is stranded somewhere with no useful direct service.
    """
    if hubs is None:
        hubs = [c for c, _ in hub_rank(limit=60)]
    elsewhere = set(hubs)
    direct = [n for n in neighbours(code) if n in elsewhere]
    out: list[dict] = []
    for hub in direct[:limit]:
        place = PLACES.get(hub)
        if place is None:
            continue
        out.append(
            {
                "code": hub,
                "name": place.name,
                "city": place.city,
                "onward": degree(hub),
                "carriers": list(carriers_between(code, hub)),
            }
        )
    return out


def served_coverage() -> dict:
    """What the graph can answer for, for the honest empty state."""
    return {
        "nodes": _STATS.nodes,
        "edges": _STATS.edges,
        "flight_nodes": _STATS.flight_nodes,
        "rail_nodes": _STATS.rail_nodes,
        "live_pairs": len(_LIVE_PAIRS),
        "sources": list(_STATS.sources),
    }


def path_summary(path: list[str]) -> list[dict]:
    """Render a hop path with names and carriers, for display in a plan."""
    rows: list[dict] = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        rows.append(
            {
                "origin": a,
                "destination": b,
                "origin_name": PLACES[a].name if a in PLACES else a,
                "destination_name": PLACES[b].name if b in PLACES else b,
                "carriers": list(carriers_between(a, b)),
            }
        )
    return rows
