"""Visa and transit compliance rules.

There is no free, official, machine-readable visa API. This is a small
curated rule table. Every rule carries a source URL and a "last verified"
date, and every surface that shows a rule also shows the reminder to
verify with the embassy or the airline.

The table is deliberately small and narrow: it covers the nationalities and
corridors the product supports today. Adding a route without adding its
rule means the UI shows "not modelled" rather than guessing.

TODO: verify - visa rules change frequently and without notice. The dates
below record when the entry was last checked, not a guarantee of accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

VERIFY_REMINDER = "Verify with the embassy or airline before travel."


@dataclass(frozen=True, slots=True)
class VisaRule:
    nationality: str          # ISO 3166-1 alpha-2 passport nationality
    destination: str          # ISO 3166-1 alpha-2 country
    purpose: str              # "transit_airside" | "transit_landside" | "short_visit" | "business"
    requirement: str          # "visa_free" | "visa_required" | "eta_required" | "transit_visa_required"
    max_stay_days: int | None
    detail: str
    source_url: str
    verified_on: str
    caveat: str = ""


RULES: tuple[VisaRule, ...] = (
    VisaRule(
        nationality="IN",
        destination="DE",
        purpose="transit_airside",
        requirement="visa_free",
        max_stay_days=None,
        detail=(
            "Airside transit through a German airport without leaving the international "
            "transit area generally does not require an airport transit visa for Indian "
            "passport holders holding a valid visa or residence permit for an EU/EEA "
            "state, the USA, Canada, Japan or the UK."
        ),
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
        caveat="Airside transit is only possible where the airport has an international transit area and the connection is on one ticket.",
    ),
    VisaRule(
        nationality="IN",
        destination="DE",
        purpose="short_visit",
        requirement="visa_required",
        max_stay_days=90,
        detail="Indian passport holders require a Schengen short-stay visa for visits to Germany.",
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="IN",
        destination="DE",
        purpose="business",
        requirement="visa_required",
        max_stay_days=90,
        detail="A Schengen business visa is required; an invitation letter is normally requested.",
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="IN",
        destination="DE",
        purpose="transit_landside",
        requirement="transit_visa_required",
        max_stay_days=None,
        detail=(
            "Leaving the international transit area in Germany to re-check baggage or "
            "change terminals on separate tickets requires a valid Schengen visa or an "
            "airport transit visa."
        ),
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
        caveat="If the recovery plan requires an overnight in Frankfurt, this becomes a landside entry, not a transit.",
    ),
    VisaRule(
        nationality="GB",
        destination="DE",
        purpose="short_visit",
        requirement="visa_free",
        max_stay_days=90,
        detail="UK passport holders may stay in the Schengen area for up to 90 days in any 180-day period.",
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="US",
        destination="DE",
        purpose="short_visit",
        requirement="visa_free",
        max_stay_days=90,
        detail="US passport holders may stay in the Schengen area for up to 90 days in any 180-day period.",
        source_url="https://www.auswaertiges-amt.de/en/visa-service",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="IN",
        destination="FR",
        purpose="transit_airside",
        requirement="transit_visa_required",
        max_stay_days=None,
        detail="An airport transit visa is required for Indian passport holders transiting France in most cases.",
        source_url="https://france-visas.gouv.fr/en/",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="IN",
        destination="AE",
        purpose="transit_airside",
        requirement="visa_free",
        max_stay_days=None,
        detail="Airside transit at Dubai is generally visa free; landside entry requires a visa or visa on arrival.",
        source_url="https://u.ae/en/information-and-services/visa-and-emirates-id",
        verified_on="2025-01-15",
    ),
    VisaRule(
        nationality="IN",
        destination="IN",
        purpose="short_visit",
        requirement="visa_free",
        max_stay_days=None,
        detail="Indian nationals do not require a visa to enter India.",
        source_url="https://www.mha.gov.in/",
        verified_on="2025-01-15",
    ),
)

# Countries whose airside transit counts as "inside the Schengen area".
# Used only for explanatory copy; not an authoritative entry rule.
SCHENGEN = {"DE", "FR", "NL", "AT", "CH", "BE", "ES", "IT", "PT", "SE", "NO", "DK", "FI", "PL", "CZ"}


def find_rule(nationality: str, destination: str, purpose: str) -> VisaRule | None:
    nat = nationality.upper()
    dest = destination.upper()
    for rule in RULES:
        if rule.nationality == nat and rule.destination == dest and rule.purpose == purpose:
            return rule
    return None


def applicable_rules(nationality: str, destinations: list[str]) -> list[VisaRule]:
    nat = nationality.upper()
    wanted = {d.upper() for d in destinations}
    return [r for r in RULES if r.nationality == nat and r.destination in wanted]


def is_expiring_soon(expiry_iso: str | None, *, travel_date: date, min_validity_days: int = 90) -> bool:
    """Schengen entry normally wants three months of validity beyond exit."""
    if not expiry_iso:
        return False
    try:
        expiry = date.fromisoformat(expiry_iso)
    except ValueError:
        return False
    return (expiry - travel_date).days < min_validity_days
