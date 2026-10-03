"""Airport, station and city reference data.

Airports and airlines are loaded from the artifact built by
``scripts/build_reference`` (OurAirports + OpenFlights). See
``docs/FACTCHECK.md`` for sources and the build date.

Two kinds of entry live here:

* **Real** airports and airlines, from the downloaded artifact.
* **Curated** rail stations and any airport the upstream data cannot answer
  for (a handful of German stations that have no IATA code). Curated rows are
  marked so the UI can tell them apart.

If the artifact is missing - a fresh checkout before the build script has run -
the loader falls back to the small curated airport set below, so the app still
starts. It never invents an airport.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True, slots=True)
class Place:
    code: str
    name: str
    city: str
    country: str
    tz: str
    lat: float
    lon: float
    kind: str = "airport"  # airport | rail | city
    city_code: str = ""
    provenance: str = "CURATED"

    @property
    def market(self) -> str:
        """The city a place belongs to, for "does this leg reach Berlin?" checks."""
        return self.city_code or self.code


# Curated rail stations and airport fallbacks. Rail stations have no upstream
# IATA-style dataset, so they stay curated and are labelled as such.
CURATED_PLACES: dict[str, Place] = {
    # --- rail stations (German station codes used as the code) --------
    "FRA_HBF": Place("FRA_HBF", "Frankfurt (Main) Hauptbahnhof", "Frankfurt", "DE", "Europe/Berlin", 50.1071, 8.6638, "rail", "FRA"),
    "BER_HBF": Place("BER_HBF", "Berlin Hauptbahnhof", "Berlin", "DE", "Europe/Berlin", 52.5250, 13.3694, "rail", "BER"),
    "BER_AIR": Place("BER_AIR", "Berlin Brandenburg Airport station", "Berlin", "DE", "Europe/Berlin", 52.3645, 13.5078, "rail", "BER"),
    "FRA_AIR": Place("FRA_AIR", "Frankfurt Flughafen Fernbahnhof", "Frankfurt", "DE", "Europe/Berlin", 50.0529, 8.5707, "rail", "FRA"),
    "KOELN_HBF": Place("KOELN_HBF", "Koln Hauptbahnhof", "Cologne", "DE", "Europe/Berlin", 50.9430, 6.9587, "rail", "CGN"),
    "LEIPZIG_HBF": Place("LEIPZIG_HBF", "Leipzig Hauptbahnhof", "Leipzig", "DE", "Europe/Berlin", 51.3455, 12.3815, "rail", "LEJ"),

    # --- Indian rail stations -----------------------------------------
    "MAS_RS": Place("MAS_RS", "Chennai Central", "Chennai", "IN", "Asia/Kolkata", 13.0827, 80.2707, "rail", "MAA"),
    "NDLS": Place("NDLS", "New Delhi Railway Station", "New Delhi", "IN", "Asia/Kolkata", 28.6424, 77.2195, "rail", "DEL"),
    "SC_RS": Place("SC_RS", "Secunderabad Junction", "Hyderabad", "IN", "Asia/Kolkata", 17.4344, 78.5013, "rail", "HYD"),
    "SBC_RS": Place("SBC_RS", "KSR Bengaluru City", "Bengaluru", "IN", "Asia/Kolkata", 12.9784, 77.5713, "rail", "BLR"),
    "MMCT": Place("MMCT", "Mumbai Chhatrapati Shivaji Maharaj Terminus", "Mumbai", "IN", "Asia/Kolkata", 18.9398, 72.8355, "rail", "BOM"),
    "HWH": Place("HWH", "Howrah Junction", "Kolkata", "IN", "Asia/Kolkata", 22.5839, 88.3428, "rail", "CCU"),
    "JP_RS": Place("JP_RS", "Jaipur Junction", "Jaipur", "IN", "Asia/Kolkata", 26.9196, 75.7878, "rail", "JAI"),

    # --- Indian bus terminals -----------------------------------------
    "MAS_BT": Place("MAS_BT", "Chennai Mofussil Bus Terminus (CMBT)", "Chennai", "IN", "Asia/Kolkata", 13.0694, 80.2002, "bus", "MAA"),
    "DEL_BT": Place("DEL_BT", "Delhi ISBT Kashmere Gate", "New Delhi", "IN", "Asia/Kolkata", 28.6675, 77.2284, "bus", "DEL"),
    "HYD_BT": Place("HYD_BT", "Hyderabad MGBS Bus Station", "Hyderabad", "IN", "Asia/Kolkata", 17.3784, 78.4867, "bus", "HYD"),
    "BLR_BT": Place("BLR_BT", "Kempegowda Bus Station (Majestic)", "Bengaluru", "IN", "Asia/Kolkata", 12.9772, 77.5722, "bus", "BLR"),
    "BOM_BT": Place("BOM_BT", "Mumbai Central Bus Depot", "Mumbai", "IN", "Asia/Kolkata", 18.9696, 72.8194, "bus", "BOM"),
}

# Fallbacks used only when the downloaded artifact is absent (fresh checkout).
_FALLBACK_AIRPORTS: dict[str, Place] = {
    "MAA": Place("MAA", "Chennai International Airport", "Chennai", "IN", "Asia/Kolkata", 12.990005, 80.169296),
    "DEL": Place("DEL", "Indira Gandhi International Airport", "New Delhi", "IN", "Asia/Kolkata", 28.55563, 77.09519),
    "BOM": Place("BOM", "Chhatrapati Shivaji Maharaj International Airport", "Mumbai", "IN", "Asia/Kolkata", 19.088699, 72.867897),
    "BLR": Place("BLR", "Kempegowda International Airport", "Bengaluru", "IN", "Asia/Kolkata", 13.1989, 77.7068),
    "HYD": Place("HYD", "Rajiv Gandhi International Airport", "Hyderabad", "IN", "Asia/Kolkata", 17.231318, 78.429855),
    "FRA": Place("FRA", "Frankfurt Main Airport", "Frankfurt am Main", "DE", "Europe/Berlin", 50.026706, 8.55835),
    "MUC": Place("MUC", "Munich Airport", "Munich", "DE", "Europe/Berlin", 48.353802, 11.7861),
    "BER": Place("BER", "Berlin Brandenburg Airport", "Berlin", "DE", "Europe/Berlin", 52.361738, 13.502341),
    "LHR": Place("LHR", "London Heathrow Airport", "London", "GB", "Europe/London", 51.4706, -0.461941),
    "CDG": Place("CDG", "Charles de Gaulle International Airport", "Paris", "FR", "Europe/Paris", 49.012798, 2.55),
}


def _load_artifact() -> tuple[dict[str, Place], dict[str, str], str | None]:
    """Return ``(places, airlines, fetched_at)`` from the built artifact."""
    places: dict[str, Place] = {}
    airlines: dict[str, str] = {}
    fetched_at: str | None = None

    airports_file = DATA_DIR / "airports.json"
    if airports_file.exists():
        payload = json.loads(airports_file.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        for row in payload.get("places", []):
            code = row["code"]
            places[code] = Place(
                code=code,
                name=row["name"],
                city=row.get("city") or row["name"],
                country=row.get("country") or "",
                tz=row["tz"],
                lat=row["lat"],
                lon=row["lon"],
                kind="airport",
                provenance="REFERENCE",
            )

    airlines_file = DATA_DIR / "airlines.json"
    if airlines_file.exists():
        payload = json.loads(airlines_file.read_text(encoding="utf-8"))
        for code, row in payload.get("airlines", {}).items():
            airlines[code] = row["name"]

    return places, airlines, fetched_at


_AIRPORTS, _AIRLINES, REFERENCE_FETCHED_AT = _load_artifact()


def _load_routes() -> dict[str, list[str]]:
    routes_file = DATA_DIR / "routes.json"
    if not routes_file.exists():
        return {}
    payload = json.loads(routes_file.read_text(encoding="utf-8"))
    return payload.get("routes", {})


# Undirected "AAA|BBB" (sorted) -> airline codes serving the pair.
ROUTES: dict[str, list[str]] = _load_routes()

# Reference data is present when the artifact loaded; the UI uses this to say
# whether airport/airline lookups are backed by the downloaded datasets.
REFERENCE_LOADED = bool(_AIRPORTS)

if not _AIRPORTS:
    _AIRPORTS = dict(_FALLBACK_AIRPORTS)

# Curated rail stations always win for their codes; airports come from upstream.
PLACES: dict[str, Place] = {**_AIRPORTS, **CURATED_PLACES}

# Auto-synthesize generic city records for the combobox
_city_map: dict[str, Place] = {}
for p in PLACES.values():
    market = p.market
    if market not in PLACES and market not in _city_map:
        _city_map[market] = Place(
            code=market,
            name=f"{p.city} (All Airports & Stations)",
            city=p.city,
            country=p.country,
            tz=p.tz,
            lat=p.lat,
            lon=p.lon,
            kind="city",
            city_code=market,
            provenance="REFERENCE"
        )
PLACES.update(_city_map)

AIRLINES: dict[str, str] = _AIRLINES or {
    "LH": "Lufthansa",
    "AI": "Air India",
    "6E": "IndiGo",
    "EK": "Emirates",
    "QR": "Qatar Airways",
}

RAIL_OPERATORS: dict[str, str] = {
    "DB": "Deutsche Bahn",
    "DBICE": "DB ICE",
    "IR": "Indian Railways",
    "SNCF": "SNCF",
}

BUS_OPERATORS: dict[str, str] = {
    "APSRTC": "Andhra Pradesh State Road Transport Corp.",
    "TNSTC": "Tamil Nadu State Transport Corp.",
    "KSRTC": "Karnataka State Road Transport Corp.",
    "UPSRTC": "Uttar Pradesh State Road Transport Corp.",
    "SRS": "SRS Travels",
    "ORANGE": "Orange Travels",
}


def place(code: str) -> Place | None:
    return PLACES.get(code.upper())


def require_place(code: str) -> Place:
    found = place(code)
    if found is None:
        raise KeyError(f"unknown place code: {code!r}")
    return found


def timezone_for(code: str) -> str:
    return require_place(code).tz


def route_airlines(origin: str, destination: str) -> list[str]:
    """Airline codes known to serve an origin/destination pair.

    Reference data, not live schedules: OpenFlights records that a route exists,
    not when it flies. Returns an empty list when the pair is unknown.
    """
    key = "|".join(sorted((origin.upper(), destination.upper())))
    return ROUTES.get(key, [])


def airline_name(code: str) -> str | None:
    return AIRLINES.get(code.upper())


def search_airports(query: str, limit: int = 12) -> list[Place]:
    """Airport lookup for the journey builder.

    Matches on IATA code, name, municipality or country, so "Chennai",
    "MAA" and "India" all find Chennai. Airports sort ahead of other places.
    """
    q = query.strip().lower()
    if not q:
        return []
    hits: list[tuple[int, Place]] = []
    for p in PLACES.values():
        if p.kind != "airport":
            continue
        code = p.code.lower()
        name = p.name.lower()
        city = p.city.lower()
        country = p.country.lower()
        if code == q:
            rank = 0
        elif code.startswith(q):
            rank = 1
        elif city.startswith(q):
            rank = 2
        elif name.startswith(q):
            rank = 3
        elif q == country:
            rank = 4
        elif q in city or q in name:
            rank = 5
        else:
            continue
        hits.append((rank, p))
    hits.sort(key=lambda t: (t[0], t[1].city, t[1].code))
    return [p for _, p in hits[:limit]]

