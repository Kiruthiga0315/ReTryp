"""Minimum connection times (MCT) and inter-modal transfer allowances.

There is no open machine-readable dataset for airport minimum connection
times. This is a small curated table covering the airports the product
currently supports, with the source of each figure recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class MctRule:
    airport_code: str
    kind: str  # domestic | international_to_international | international_to_domestic | domestic_to_international
    minutes: int
    source: str
    verified_on: str
    note: str = ""


# Conservative planning values, minutes. Airline-agnostic.
MCT_TABLE: tuple[MctRule, ...] = (
    MctRule("FRA", "international_to_international", 60, "Frankfurt Airport transfer guidance", "2025-01-15",
            "Schengen-to-Schengen transfers at FRA are typically shorter than non-Schengen."),
    MctRule("FRA", "international_to_domestic", 60, "Frankfurt Airport transfer guidance", "2025-01-15"),
    MctRule("FRA", "domestic_to_international", 60, "Frankfurt Airport transfer guidance", "2025-01-15"),
    MctRule("MUC", "international_to_international", 60, "Munich Airport transfer guidance", "2025-01-15"),
    MctRule("BER", "domestic_to_domestic", 40, "Berlin Brandenburg transfer guidance", "2025-01-15"),
    MctRule("BER", "international_to_domestic", 50, "Berlin Brandenburg transfer guidance", "2025-01-15"),
    MctRule("AMS", "international_to_international", 50, "Amsterdam Schiphol transfer guidance", "2025-01-15"),
    MctRule("CDG", "international_to_international", 75, "Paris CDG transfer guidance", "2025-01-15"),
    MctRule("LHR", "international_to_international", 75, "London Heathrow transfer guidance", "2025-01-15"),
    MctRule("DXB", "international_to_international", 60, "Dubai International transfer guidance", "2025-01-15"),
    MctRule("IST", "international_to_international", 60, "Istanbul Airport transfer guidance", "2025-01-15"),
    MctRule("DEL", "international_to_domestic", 75, "Delhi IGI transfer guidance", "2025-01-15"),
    MctRule("MAA", "domestic_to_international", 75, "Chennai International transfer guidance", "2025-01-15"),
    MctRule("BOM", "international_to_domestic", 75, "Mumbai CSMIA transfer guidance", "2025-01-15"),
)

# Inter-modal transfer times between airport, railway station, and bus terminal
INTERMODAL_TRANSFER_MINUTES: dict[tuple[str, str], int] = {
    ("MAA", "MAS_RS"): 75,
    ("MAS_RS", "MAA"): 75,
    ("MAA", "MAS_BT"): 60,
    ("MAS_BT", "MAA"): 60,
    ("DEL", "NDLS"): 90,
    ("NDLS", "DEL"): 90,
    ("DEL", "DEL_BT"): 75,
    ("DEL_BT", "DEL"): 75,
    ("HYD", "SC_RS"): 60,
    ("SC_RS", "HYD"): 60,
    ("HYD", "HYD_BT"): 45,
    ("HYD_BT", "HYD"): 45,
    ("BLR", "SBC_RS"): 90,
    ("SBC_RS", "BLR"): 90,
    ("BLR", "BLR_BT"): 75,
    ("BLR_BT", "BLR"): 75,
    ("BOM", "MMCT"): 60,
    ("MMCT", "BOM"): 60,
    ("BOM", "BOM_BT"): 60,
    ("BOM_BT", "BOM"): 60,
    ("CCU", "HWH"): 60,
    ("HWH", "CCU"): 60,
    ("MAS_BT", "MAS_RS"): 20,
    ("MAS_RS", "MAS_BT"): 20,
    ("DEL_BT", "NDLS"): 25,
    ("NDLS", "DEL_BT"): 25,
    ("HYD_BT", "SC_RS"): 30,
    ("SC_RS", "HYD_BT"): 30,
    ("BLR_BT", "SBC_RS"): 15,
    ("SBC_RS", "BLR_BT"): 15,
}

# Fallback when an airport is not in the table.
DEFAULT_MCT_MINUTES = 75
DEFAULT_MCT_SOURCE = "ReTryp default planning buffer (no curated MCT for this airport)"

# Safety margin applied on top of the MCT before a connection is called tight.
TIGHT_MARGIN_MINUTES = 20


def _lookup(airport_code: str, kind: str) -> MctRule | None:
    code = airport_code.upper()
    for rule in MCT_TABLE:
        if rule.airport_code == code and rule.kind == kind:
            return rule
    for rule in MCT_TABLE:
        if rule.airport_code == code:
            return rule
    return None


def mct_for(airport_code: str, kind: str) -> tuple[int, str, str]:
    """Return (minutes, source, verified_on) for an airport and transfer kind."""
    rule = _lookup(airport_code, kind)
    if rule is None:
        return (
            DEFAULT_MCT_MINUTES,
            DEFAULT_MCT_SOURCE,
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
    return rule.minutes, rule.source, rule.verified_on


def intermodal_transfer_minutes(from_place: str, to_place: str) -> int:
    """Estimated transfer time in minutes between different terminals/stations in a city."""
    if from_place == to_place:
        return 0
    direct = INTERMODAL_TRANSFER_MINUTES.get((from_place, to_place))
    if direct is not None:
        return direct
    return 60


def transfer_kind(origin_country: str, destination_country: str, schengen: bool = True) -> str:
    if origin_country == destination_country:
        return "domestic_to_domestic"
    return "international_to_international"
