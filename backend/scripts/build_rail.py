"""Build real rail timetables for the recovery corridor from German GTFS.

Downloads the DELFI / GTFS.de Germany feed and extracts the direct train
services between the corridor's stations, writing a compact artifact that the
API can query by date.

The feed is large (``stop_times.txt`` alone is about 2.3 GB uncompressed), so it
is streamed and reduced rather than loaded whole: only rail trips whose journey
touches a corridor station are kept, and only their first/last corridor stops.

Run from the backend directory:

    python -m scripts.build_rail

Source: DELFI e.V. / GTFS.de, ``https://download.gtfs.de/germany/free/latest.zip``,
licence CC-BY. Attribution is carried in the artifact and shown in the UI.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "app" / "data"

FEED_URL = "https://download.gtfs.de/germany/free/latest.zip"
USER_AGENT = "ReTryp/1.0 (+https://retryp.example)"

# GTFS route_type 2 is rail. Suburban rail (S-Bahn) is included so short hops
# to the airport are available as ground transport, but the long-distance
# corridor services are what the recovery plans use.
RAIL_ROUTE_TYPE = "2"

# Station names we group into a corridor node. Matching is on the lowercased
# stop name, and only parent stations (location_type 1) anchor a node.
CORRIDOR_NODES: dict[str, tuple[str, ...]] = {
    "FRA": ("frankfurt (main) hauptbahnhof",),
    "FRA_AIR": ("frankfurt (main) flughafen fernbahnhof",),
    "BER": ("berlin hauptbahnhof",),
    "BER_AIR": ("berlin brandenburg airport station", "flughafen ber"),
}


def _download(url: str) -> bytes:
    print(f"downloading {url} ...")
    with httpx.Client(timeout=600, follow_redirects=True) as http:
        response = http.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.content


def _rows(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def build() -> dict:
    payload = _download(FEED_URL)
    zf = zipfile.ZipFile(io.BytesIO(payload))

    feed_info = next(iter(_rows(zf, "feed_info.txt")), {})
    print("feed:", feed_info.get("feed_version"), "|", feed_info.get("feed_publisher_name"))

    agency_names: dict[str, str] = {
        r["agency_id"]: r["agency_name"] for r in _rows(zf, "agency.txt")
    }

    # --- stops: parent map and corridor node stop ids -------------------
    parent_of: dict[str, str] = {}
    name_of: dict[str, str] = {}
    node_stops: dict[str, set[str]] = defaultdict(set)
    node_parents: dict[str, set[str]] = defaultdict(set)
    for s in _rows(zf, "stops.txt"):
        sid = s["stop_id"]
        parent = (s.get("parent_station") or "").strip()
        parent_of[sid] = parent
        name_of[sid] = s["stop_name"] or ""
        low = (s["stop_name"] or "").lower()
        for node, needles in CORRIDOR_NODES.items():
            if any(n in low for n in needles):
                node_parents[node].add(parent or sid)

    # A corridor stop is any stop whose own id or parent id is a node parent.
    parent_nodes: dict[str, set[str]] = defaultdict(set)
    for node, parents in node_parents.items():
        for p in parents:
            parent_nodes[p].add(node)

    def node_of(stop_id: str) -> str | None:
        own = parent_of.get(stop_id) or stop_id
        direct = parent_nodes.get(own)
        if direct:
            return sorted(direct)[0]
        return None

    for node in CORRIDOR_NODES:
        print(f"node {node}: parent stations {sorted(node_parents[node])}")

    # --- calendar -------------------------------------------------------
    cal: dict[str, dict] = {r["service_id"]: r for r in _rows(zf, "calendar.txt")}
    cal_dates: dict[str, dict[str, str]] = defaultdict(dict)
    for r in _rows(zf, "calendar_dates.txt"):
        cal_dates[r["service_id"]][r["date"]] = r["exception_type"]

    feed_start = min((r["start_date"] for r in cal.values()), default=None)
    feed_end = max((r["end_date"] for r in cal.values()), default=None)
    print("calendar window:", feed_start, "->", feed_end)

    weekday_cols = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )

    def runs_on(service_id: str, day: date) -> bool:
        key = day.strftime("%Y%m%d")
        exc = cal_dates.get(service_id, {})
        if key in exc:
            return exc[key] == "1"
        spec = cal.get(service_id)
        if spec is None:
            return False
        if not (spec["start_date"] <= key <= spec["end_date"]):
            return False
        return spec[weekday_cols[day.weekday()]] == "1"

    # --- trips: keep only rail ------------------------------------------
    route_meta: dict[str, dict] = {}
    for r in _rows(zf, "routes.txt"):
        if r["route_type"] == RAIL_ROUTE_TYPE:
            route_meta[r["route_id"]] = r
    print("rail routes:", len(route_meta))

    trip_service: dict[str, tuple[str, str, str]] = {}  # trip -> (service, route, short_name)
    for t in _rows(zf, "trips.txt"):
        route = t["route_id"]
        if route in route_meta:
            meta = route_meta[route]
            trip_service[t["trip_id"]] = (
                t["service_id"],
                route,
                meta.get("route_short_name") or meta.get("route_long_name") or "Rail",
            )
    print("rail trips:", len(trip_service))

    # --- stop_times: reduce to corridor touch points --------------------
    # Per trip, remember the earliest stop at each corridor node, so a journey
    # that passes through both nodes can be ordered by stop_sequence.
    touches: dict[str, dict[str, tuple[int, str, str, str]]] = defaultdict(dict)

    with zf.open("stop_times.txt") as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        i_trip = idx["trip_id"]
        i_arr = idx["arrival_time"]
        i_dep = idx["departure_time"]
        i_stop = idx["stop_id"]
        i_seq = idx["stop_sequence"]
        seen = 0
        for row in reader:
            trip = row[i_trip]
            if trip not in trip_service:
                continue
            seen += 1
            node = node_of(row[i_stop])
            if node is None:
                continue
            seq = int(row[i_seq])
            bucket = touches[trip]
            current = bucket.get(node)
            if current is None or seq < current[0]:
                bucket[node] = (seq, row[i_stop], row[i_arr], row[i_dep])
        print(f"stop_times rows scanned for rail trips: {seen}")

    # --- assemble direct services --------------------------------------
    now_utc = datetime.now(timezone.utc)
    horizon_start = date.fromisoformat(f"{feed_start[:4]}-{feed_start[4:6]}-{feed_start[6:]}")
    horizon_end = date.fromisoformat(f"{feed_end[:4]}-{feed_end[4:6]}-{feed_end[6:]}")

    # Group services by a signature so a daily train becomes one entry with a
    # list of dates, not thirty near-identical entries.
    grouped: dict[tuple, dict] = {}
    for trip, nodes in touches.items():
        for origin, destination in (("FRA", "BER"), ("FRA_AIR", "BER"), ("FRA_AIR", "BER_AIR"), ("FRA", "BER_AIR")):
            a = nodes.get(origin)
            b = nodes.get(destination)
            if not a or not b or a[0] >= b[0]:
                continue
            service_id, route, short_name = trip_service[trip]
            dep = a[3]
            arr = b[2]
            if not dep or not arr:
                continue
            dep_min = _hhmm(dep)
            arr_min = _hhmm(arr)
            if dep_min is None or arr_min is None:
                continue
            duration = arr_min - dep_min
            if duration <= 0:
                duration += 24 * 60
            operator = agency_names.get(route_meta[route]["agency_id"], "")
            key = (origin, destination, short_name, dep, arr, operator)
            entry = grouped.setdefault(
                key, {"dates": set(), "trip_id": trip, "duration_min": duration}
            )
            entry["dates"].add(service_id)

    services: list[dict] = []
    for (origin, destination, short_name, dep, arr, operator), entry in grouped.items():
        active: list[str] = []
        day = horizon_start
        while day <= horizon_end:
            for service_id in entry["dates"]:
                if runs_on(service_id, day):
                    active.append(day.isoformat())
                    break
            day += timedelta(days=1)
        if not active:
            continue
        services.append(
            {
                "origin": origin,
                "destination": destination,
                "service": short_name,
                "operator": operator or "DELFI",
                "departure": dep,
                "arrival": arr,
                "duration_min": entry["duration_min"],
                "dates": active,
                "trip_id": entry["trip_id"],
            }
        )

    services.sort(key=lambda s: (s["origin"], s["destination"], s["departure"]))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = now_utc.isoformat()
    (DATA_DIR / "rail_services.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched_at,
                "feed_version": feed_info.get("feed_version"),
                "publisher": feed_info.get("feed_publisher_name"),
                "source_url": FEED_URL,
                "valid_from": horizon_start.isoformat(),
                "valid_to": horizon_end.isoformat(),
                "timezone": "Europe/Berlin",
                "services": services,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"direct services: {len(services)}")
    for s in services[:12]:
        print(
            f"  {s['origin']:7}->{s['destination']:7} {s['service']:6} "
            f"{s['departure']} -> {s['arrival']}  {s['duration_min']}m  "
            f"{len(s['dates'])} days  {s['operator']}"
        )
    return {"services": len(services), "fetched_at": fetched_at}


def _hhmm(value: str) -> int | None:
    try:
        hh, mm, *_ = value.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None


if __name__ == "__main__":
    build()
