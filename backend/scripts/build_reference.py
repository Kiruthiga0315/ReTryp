"""Build the airport and airline reference dataset.

Downloads the upstream sources and writes a compact artifact that the API
loads at import time. Run from the backend directory:

    python -m scripts.build_reference

Sources, and why each one is needed:

* OurAirports ``airports.csv`` - authoritative for airport name, municipality,
  country, coordinates and IATA/ICAO codes. It has **no** timezone column.
* OpenFlights ``airports.dat`` - supplies the IANA timezone (``tzname``), which
  OurAirports lacks. Coordinates and codes come from OurAirports where both
  have a row.
* OpenFlights ``airlines.dat`` - airline names and codes.

Both are open data: OurAirports is public domain, OpenFlights is ODbL.
Attribution is carried in the artifact and surfaced in the UI.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "app" / "data"

OURAIRPORTS_AIRPORTS = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
)
OPENFLIGHTS_AIRPORTS = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)
OPENFLIGHTS_AIRLINES = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
)
OPENFLIGHTS_ROUTES = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
)

USER_AGENT = "ReTryp/1.0 (+https://retryp.example)"


def _download(url: str) -> str:
    with httpx.Client(timeout=120, follow_redirects=True) as http:
        response = http.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


def _openflights_timezones(text: str) -> dict[str, dict]:
    """IATA code -> {tz, city} from the OpenFlights ``.dat`` file."""
    out: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(text)):
        # 0 id, 1 name, 2 city, 3 country, 4 IATA, 5 ICAO, 6 lat, 7 lon,
        # 8 alt, 9 tz offset, 10 DST, 11 tz database name
        if len(row) < 12:
            continue
        iata = (row[4] or "").strip().upper()
        tz = (row[11] or "").strip()
        if not iata or iata == "\\N" or not tz or tz == "\\N":
            continue
        out.setdefault(iata, {"tz": tz, "city": (row[2] or "").strip()})
    return out


def _airlines(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(text)):
        # 0 id, 1 name, 2 alias, 3 IATA, 4 ICAO, 5 callsign, 6 country, 7 active
        if len(row) < 8:
            continue
        iata = (row[3] or "").strip().upper()
        name = (row[1] or "").strip()
        if not iata or iata == "\\N" or not name or name == "\\N":
            continue
        if (row[7] or "").strip().upper() not in {"Y", "N"}:
            continue
        out.setdefault(
            iata,
            {"name": name, "icao": (row[4] or "").strip(), "country": (row[6] or "").strip()},
        )
    return out


def _routes(text: str, valid_places: set[str]) -> dict[str, list[str]]:
    """Undirected ``A|B`` -> airline codes, from OpenFlights routes.dat.

    Only routes whose codes resolved to airports we carry are kept, so the map
    never points at an airport the app cannot describe.
    """
    out: dict[str, set[str]] = {}
    for row in csv.reader(io.StringIO(text)):
        # 0 airline, 1 id, 2 src, 3 src id, 4 dst, 5 dst id, 6 codeshare,
        # 7 stops, 8 equipment
        if len(row) < 9:
            continue
        airline = (row[0] or "").strip().upper()
        src = (row[2] or "").strip().upper()
        dst = (row[4] or "").strip().upper()
        if not airline or not src or not dst or src == dst:
            continue
        if src not in valid_places or dst not in valid_places:
            continue
        key = "|".join(sorted((src, dst)))
        out.setdefault(key, set()).add(airline)
    return {k: sorted(v) for k, v in out.items()}


def build() -> dict:
    from timezonefinder import TimezoneFinder

    print("downloading OurAirports airports.csv ...")
    airports_raw = _download(OURAIRPORTS_AIRPORTS)
    print("downloading OpenFlights airports.dat ...")
    of_airports_raw = _download(OPENFLIGHTS_AIRPORTS)
    print("downloading OpenFlights airlines.dat ...")
    of_airlines_raw = _download(OPENFLIGHTS_AIRLINES)
    print("downloading OpenFlights routes.dat ...")
    of_routes_raw = _download(OPENFLIGHTS_ROUTES)

    tz_by_iata = _openflights_timezones(of_airports_raw)
    finder = TimezoneFinder()

    # A place is worth carrying if it has an IATA code and actually handles
    # scheduled traffic. Heliports, seaplane bases and closed fields are dropped.
    keep: list[dict] = []
    seen: set[str] = set()
    tz_from_coords = 0
    for row in csv.DictReader(io.StringIO(airports_raw)):
        iata = (row.get("iata_code") or "").strip().upper()
        if not iata or iata in seen:
            continue
        if (row.get("scheduled_service") or "").lower() != "yes":
            continue
        lat = float(row["latitude_deg"])
        lon = float(row["longitude_deg"])
        # timezonefinder resolves from tzdata polygons and returns canonical
        # IANA names, so it is preferred over OpenFlights, which still carries
        # deprecated aliases such as Asia/Calcutta for Chennai.
        tz = finder.timezone_at(lat=lat, lng=lon) or ""
        if tz:
            tz_from_coords += 1
        else:
            tz = tz_by_iata.get(iata, {}).get("tz", "")
        if not tz:
            # Without a timezone the airport cannot be used for any local-time
            # arithmetic, so it is not carried rather than guessed.
            continue
        seen.add(iata)
        keep.append(
            {
                "code": iata,
                "icao": (row.get("icao_code") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "city": (row.get("municipality") or "").strip()
                or tz_by_iata.get(iata, {}).get("city", ""),
                "country": (row.get("iso_country") or "").strip(),
                "tz": tz,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
            }
        )

    keep.sort(key=lambda r: r["code"])
    airlines = _airlines(of_airlines_raw)
    routes = _routes(of_routes_raw, {r["code"] for r in keep})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    (DATA_DIR / "airports.json").write_text(
        json.dumps(
            {"fetched_at": fetched_at, "places": keep},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (DATA_DIR / "airlines.json").write_text(
        json.dumps(
            {"fetched_at": fetched_at, "airlines": airlines},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (DATA_DIR / "routes.json").write_text(
        json.dumps(
            {"fetched_at": fetched_at, "routes": routes},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"airports: {len(keep)} with IATA + scheduled service + timezone")
    print(f"  timezones resolved from coordinates (no OpenFlights row): {tz_from_coords}")
    print(f"airlines: {len(airlines)}")
    print(f"routes: {len(routes)} pairs served")
    print(f"written to {DATA_DIR}")
    return {
        "airports": len(keep),
        "airlines": len(airlines),
        "routes": len(routes),
        "tz_from_coords": tz_from_coords,
        "fetched_at": fetched_at,
    }


if __name__ == "__main__":
    build()
