"""Passenger-rights compensation estimation.

Two regimes are implemented:

* **EU 261/2004** for flights departing the EU/EEA/UK or arriving into the EU
  on an EU/UK carrier. Verified against EUR-Lex and the CJEU Sturgeon reading.
* **DGCA CAR Section 3, Series M, Part IV** for flights departing India.
  India provides *care*, not fixed cash compensation, for delays; cash
  compensation applies to denied boarding and cancellations.

Everything below is an **estimate**, labelled as such in the API response.
The product never tells a traveller they are owed money; it says
"potential eligibility" with the factors that produced it, and a
not-a-guarantee disclaimer. See docs/FACTCHECK.md for sources and dates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import CompensationBasis, CompensationOutcome
from .money import Money

# --- verified constants -------------------------------------------------
# Regulation (EC) No 261/2004, Article 7(1). Amounts in EUR.
EU261_SHORT_HAUL_MAX_KM = 1500
EU261_MEDIUM_HAUL_MAX_KM = 3500
EU261_AMOUNT_SHORT_HAUL = Money(25000, "EUR")   # EUR 250
EU261_AMOUNT_MEDIUM_HAUL = Money(40000, "EUR")  # EUR 400
EU261_AMOUNT_LONG_HAUL = Money(60000, "EUR")    # EUR 600

# Article 7(2): the amount is halved when a re-routing keeps the arrival
# delay below the thresholds in Article 6.
EU261_LONG_HAUL_REDUCTION_BAND_MINUTES = (180, 240)  # 3h to under 4h
EU261_REDUCTION_FACTOR = 0.5

# Article 6: the delay thresholds at which compensation becomes due.
EU261_DELAY_THRESHOLD_MINUTES = 180  # 3 hours at final destination

# DGCA CAR Section 3, Series M, Part IV, para 3.2.2 / 3.3.2.
DGCA_DENIED_BOARDING_WITHIN_24H = Money(1000000, "INR")   # 200% of fare, cap INR 10,000
DGCA_DENIED_BOARDING_OVER_24H = Money(2000000, "INR")     # 400% of fare, cap INR 20,000
DGCA_DENIED_BOARDING_PCT_WITHIN_24H = 2.0
DGCA_DENIED_BOARDING_PCT_OVER_24H = 4.0
DGCA_DELAY_CARE_THRESHOLD_MINUTES = 120
DGCA_REFUND_OPTION_DELAY_MINUTES = 360  # para 3.4.2: >6h -> alternate or full refund

# CAR Section 3, Series M, Part IV, para 3.3.2: cancellation (and missed
# connection on the same ticket) pays a fixed band by block time, or the
# one-way basic fare plus fuel charge, whichever is less. Amounts in INR.
DGCA_CANCELLATION_BANDS: tuple[tuple[int | None, Money], ...] = (
    (60, Money(500000, "INR")),    # block time up to and including 1 hour
    (120, Money(750000, "INR")),   # more than 1 hour, up to and including 2 hours
    (None, Money(1000000, "INR")),  # more than 2 hours
)


def dgca_cancellation_amount(block_minutes: int | None, fare_minor: int) -> Money:
    """Para 3.3.2 band amount: min(band cap, one-way basic fare plus fuel charge)."""
    cap = DGCA_CANCELLATION_BANDS[-1][1]
    if block_minutes is not None:
        for upper, amount in DGCA_CANCELLATION_BANDS:
            if upper is None or block_minutes <= upper:
                cap = amount
                break
    return Money(min(cap.amount_minor, max(0, fare_minor)), "INR")

EU_DEPARTURE_REGIONS = {"EU", "EEA", "UK", "CH"}

# ISO 3166-1 alpha-2 codes for the EU/EEA, the UK and Switzerland. Callers
# pass ISO country codes (from the airport reference table), not the region
# tags above, so both forms must be recognised for the Article 3 scope test.
EU_EEA_UK_CH_COUNTRIES = {
    # European Union
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
    # EEA
    "IS", "LI", "NO",
    # United Kingdom
    "GB",
    # Switzerland (EU261 applies by analogy and is treated as in scope)
    "CH",
}


def in_eu261_scope(region_or_country: str | None) -> bool:
    """True for an EU/EEA/UK/CH country code or the equivalent region tag."""
    if not region_or_country:
        return False
    value = region_or_country.strip().upper()
    return value in EU_EEA_UK_CH_COUNTRIES or value in EU_DEPARTURE_REGIONS


@dataclass(slots=True)
class CompensationEstimate:
    outcome: CompensationOutcome
    basis: CompensationBasis
    amount: Money
    currency: str
    delay_minutes: int
    distance_km: float | None
    factors: list[str] = field(default_factory=list)
    care_entitlements: list[str] = field(default_factory=list)
    refund_available: bool = False
    regulation_reference: str = ""
    regulation_url: str = ""
    last_verified: str = ""
    disclaimer: str = (
        "Potential eligibility only. This is an estimate from published rules, "
        "not a guarantee of payment. Verify with the operating airline, and with "
        "the embassy or airline before travel where visa or transit rules apply."
    )

    def to_payload(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "basis": self.basis.value,
            "amount_minor": self.amount.amount_minor,
            "currency": self.amount.currency,
            "amount_display": str(self.amount),
            "delay_minutes": self.delay_minutes,
            "distance_km": round(self.distance_km, 1) if self.distance_km else None,
            "factors": self.factors,
            "care_entitlements": self.care_entitlements,
            "refund_available": self.refund_available,
            "regulation_reference": self.regulation_reference,
            "regulation_url": self.regulation_url,
            "last_verified": self.last_verified,
            "disclaimer": self.disclaimer,
        }


def eu261_band_amount(distance_km: float) -> Money:
    if distance_km <= EU261_SHORT_HAUL_MAX_KM:
        return EU261_AMOUNT_SHORT_HAUL
    if distance_km <= EU261_MEDIUM_HAUL_MAX_KM:
        return EU261_AMOUNT_MEDIUM_HAUL
    return EU261_AMOUNT_LONG_HAUL


def estimate_eu261(
    *,
    distance_km: float,
    delay_minutes: int,
    departure_region: str,
    carrier_region: str,
    extraordinary_circumstances: bool = False,
    re_routed: bool = False,
) -> CompensationEstimate:
    """Estimate EU261/2004 eligibility.

    ``distance_km`` is the great-circle distance of the whole journey where
    the itinerary ends outside the EU, or of the delayed flight otherwise.
    ``departure_region`` and ``carrier_region`` are ISO-ish region tags.
    """
    factors: list[str] = []
    care: list[str] = []
    in_scope = in_eu261_scope(departure_region) or in_eu261_scope(carrier_region)
    factors.append(
        f"Journey distance {distance_km:,.0f} km"
        + (" (within the EU/EEA/UK)" if in_eu261_scope(departure_region) else "")
    )
    factors.append(f"Departure region: {departure_region}; operating carrier region: {carrier_region}")

    if not in_scope:
        return CompensationEstimate(
            outcome=CompensationOutcome.NOT_ELIGIBLE,
            basis=CompensationBasis.EU261,
            amount=Money(0, "EUR"),
            currency="EUR",
            delay_minutes=delay_minutes,
            distance_km=distance_km,
            factors=factors + ["Flight falls outside EU261 scope (neither departing the EU/EEA/UK nor operated by an EU/EEA/UK carrier)"],
            regulation_reference="Regulation (EC) No 261/2004, Article 3",
            regulation_url="https://eur-lex.europa.eu/eli/reg/2004/261/oj",
            last_verified="2025-01-15",
        )

    if delay_minutes < EU261_DELAY_THRESHOLD_MINUTES:
        care = ["Meals and refreshments from 2 hours", "Hotel and transfers when an overnight stay becomes necessary"]
        return CompensationEstimate(
            outcome=CompensationOutcome.NOT_ELIGIBLE,
            basis=CompensationBasis.EU261,
            amount=Money(0, "EUR"),
            currency="EUR",
            delay_minutes=delay_minutes,
            distance_km=distance_km,
            factors=factors + [f"Arrival delay {delay_minutes} min is below the 3 hour threshold"],
            care_entitlements=care,
            regulation_reference="Regulation (EC) No 261/2004, Articles 6 and 7",
            regulation_url="https://eur-lex.europa.eu/eli/reg/2004/261/oj",
            last_verified="2025-01-15",
        )

    if extraordinary_circumstances:
        care = ["Meals and refreshments", "Hotel and transfers when an overnight stay becomes necessary"]
        return CompensationEstimate(
            outcome=CompensationOutcome.NOT_ELIGIBLE,
            basis=CompensationBasis.EU261,
            amount=Money(0, "EUR"),
            currency="EUR",
            delay_minutes=delay_minutes,
            distance_km=distance_km,
            factors=factors + ["Extraordinary circumstances beyond the carrier's control reduce eligibility to zero"],
            care_entitlements=care,
            regulation_reference="Regulation (EC) No 261/2004, Article 5(3)",
            regulation_url="https://eur-lex.europa.eu/eli/reg/2004/261/oj",
            last_verified="2025-01-15",
        )

    amount = eu261_band_amount(distance_km)
    factors.append(
        {
            EU261_AMOUNT_SHORT_HAUL: "Distance band: up to 1,500 km",
            EU261_AMOUNT_MEDIUM_HAUL: "Distance band: 1,500 to 3,500 km",
            EU261_AMOUNT_LONG_HAUL: "Distance band: over 3,500 km",
        }[amount]
    )

    reduced = False
    if (
        amount == EU261_AMOUNT_LONG_HAUL
        and re_routed
        and EU261_LONG_HAUL_REDUCTION_BAND_MINUTES[0] <= delay_minutes < EU261_LONG_HAUL_REDUCTION_BAND_MINUTES[1]
    ):
        amount = amount.scaled(EU261_REDUCTION_FACTOR)
        reduced = True
        factors.append(
            "Long-haul arrival delay between 3 and 4 hours with re-routing: Article 7(2) halves the amount"
        )
    elif re_routed and delay_minutes < EU261_DELAY_THRESHOLD_MINUTES + 60:
        factors.append("Re-routed, but the arrival delay still meets the 3 hour threshold, so no reduction applies")

    outcome = CompensationOutcome.ELIGIBLE if not reduced else CompensationOutcome.POSSIBLY_ELIGIBLE
    care = ["Meals and refreshments", "Hotel and transfers when an overnight stay becomes necessary"]
    return CompensationEstimate(
        outcome=outcome,
        basis=CompensationBasis.EU261,
        amount=amount,
        currency="EUR",
        delay_minutes=delay_minutes,
        distance_km=distance_km,
        factors=factors + [f"Arrival delay at final destination: {delay_minutes} min"],
        care_entitlements=care,
        regulation_reference="Regulation (EC) No 261/2004, Article 7",
        regulation_url="https://eur-lex.europa.eu/eli/reg/2004/261/oj",
        last_verified="2025-01-15",
    )


def estimate_dgca(
    *,
    delay_minutes: int,
    one_way_fare_minor: int,
    currency: str = "INR",
    block_minutes: int | None = None,
    denied_boarding: bool = False,
    cancelled: bool = False,
    alternate_within_24h: bool = True,
    accepted_alternate: bool = True,
    extraordinary_circumstances: bool = False,
    overnight_delay: bool = False,
) -> CompensationEstimate:
    """Estimate Indian DGCA CAR Section 3, Series M, Part IV entitlements.

    Key difference from EU261: a *delay* alone never triggers a cash payment
    in India. The traveller gets care (meals, hotel, transfers) and, past six
    hours, a refund or an alternate flight.
    """
    factors: list[str] = []
    care: list[str] = []

    if extraordinary_circumstances:
        return CompensationEstimate(
            outcome=CompensationOutcome.NOT_ELIGIBLE,
            basis=CompensationBasis.DGCA_INDIA,
            amount=Money(0, currency),
            currency=currency,
            delay_minutes=delay_minutes,
            distance_km=None,
            factors=["Extraordinary circumstances: the CAR expressly exempts the airline from compensation"],
            care_entitlements=["Meals and refreshments where the disruption was not avoidable are at the airline's discretion"],
            regulation_reference="CAR Section 3, Series M, Part IV, paras 3.4.4 and 3.3.4",
            regulation_url="https://www.dgca.gov.in/",
            last_verified="2025-01-15",
        )

    if denied_boarding:
        factors.append("Involuntary denied boarding with a confirmed ticket and timely check-in")
        cap = DGCA_DENIED_BOARDING_WITHIN_24H if alternate_within_24h else DGCA_DENIED_BOARDING_OVER_24H
        pct = (
            DGCA_DENIED_BOARDING_PCT_WITHIN_24H
            if alternate_within_24h
            else DGCA_DENIED_BOARDING_PCT_OVER_24H
        )
        if not accepted_alternate:
            pct = DGCA_DENIED_BOARDING_PCT_OVER_24H
            cap = DGCA_DENIED_BOARDING_OVER_24H
            factors.append("No alternate flight accepted, so the higher band applies alongside a full refund")
        computed = round(one_way_fare_minor * pct)
        amount = Money(min(computed, cap.amount_minor), currency)
        factors.append(
            f"{int(pct * 100)}% of one-way base fare plus fuel charge, capped at {cap}"
        )
        return CompensationEstimate(
            outcome=CompensationOutcome.ELIGIBLE,
            basis=CompensationBasis.DGCA_INDIA,
            amount=amount,
            currency=currency,
            delay_minutes=delay_minutes,
            distance_km=None,
            factors=factors,
            refund_available=not accepted_alternate,
            regulation_reference="CAR Section 3, Series M, Part IV, para 3.2.2",
            regulation_url="https://www.dgca.gov.in/",
            last_verified="2026-09-28",
        )

    if cancelled:
        factors.append("Flight cancelled within 14 days of departure without acceptable re-routing")
        amount = dgca_cancellation_amount(block_minutes, one_way_fare_minor)
        band_text = (
            "block time up to 1 hour"
            if block_minutes is not None and block_minutes <= 60
            else "block time 1 to 2 hours"
            if block_minutes is not None and block_minutes <= 120
            else "block time over 2 hours"
            if block_minutes is not None
            else "block time not supplied"
        )
        factors.append(
            f"Fixed band for {band_text}: {amount}, being the lower of the band cap and the one-way basic fare plus fuel charge"
        )
        return CompensationEstimate(
            outcome=CompensationOutcome.ELIGIBLE,
            basis=CompensationBasis.DGCA_INDIA,
            amount=amount,
            currency="INR",
            delay_minutes=delay_minutes,
            distance_km=None,
            factors=factors,
            refund_available=True,
            regulation_reference="CAR Section 3, Series M, Part IV, para 3.3.2",
            regulation_url="https://www.dgca.gov.in/",
            last_verified="2026-09-28",
        )

    # Delay only: care, not cash.
    care = ["Meals and refreshments after 2 hours of waiting", "Regular updates on the revised departure time"]
    if overnight_delay:
        care.append("Hotel accommodation when necessary, including transfers")
    refund_available = delay_minutes > DGCA_REFUND_OPTION_DELAY_MINUTES
    if refund_available:
        factors.append(
            "Delay exceeds 6 hours: an alternate flight within 6 hours or a full refund must be offered"
        )
    factors.append("Indian delay rules provide care rather than fixed cash compensation")
    return CompensationEstimate(
        outcome=CompensationOutcome.CARE_ONLY,
        basis=CompensationBasis.DGCA_INDIA,
        amount=Money(0, currency),
        currency=currency,
        delay_minutes=delay_minutes,
        distance_km=None,
        factors=factors,
        care_entitlements=care,
        refund_available=refund_available,
        regulation_reference="CAR Section 3, Series M, Part IV, paras 3.4 and 3.8",
        regulation_url="https://www.dgca.gov.in/",
        last_verified="2025-01-15",
    )


def estimate(
    *,
    departure_country: str,
    carrier_country: str,
    distance_km: float | None,
    delay_minutes: int,
    one_way_fare_minor: int | None = None,
    fare_currency: str = "INR",
    block_minutes: int | None = None,
    extraordinary_circumstances: bool = False,
    re_routed: bool = False,
    denied_boarding: bool = False,
    cancelled: bool = False,
    alternate_within_24h: bool = True,
    accepted_alternate: bool = True,
    overnight_delay: bool = False,
) -> CompensationEstimate:
    """Pick the applicable regime and estimate.

    An India-departing flight that is also within EU261 scope (for example a
    flight departing the EU) uses EU261, which is the more generous regime.
    """
    if in_eu261_scope(departure_country) or in_eu261_scope(carrier_country):
        if distance_km is not None:
            return estimate_eu261(
                distance_km=distance_km,
                delay_minutes=delay_minutes,
                departure_region=departure_country,
                carrier_region=carrier_country,
                extraordinary_circumstances=extraordinary_circumstances,
                re_routed=re_routed,
            )
    if departure_country == "IN":
        return estimate_dgca(
            delay_minutes=delay_minutes,
            one_way_fare_minor=one_way_fare_minor or 0,
            currency=fare_currency,
            block_minutes=block_minutes,
            denied_boarding=denied_boarding,
            cancelled=cancelled,
            alternate_within_24h=alternate_within_24h,
            accepted_alternate=accepted_alternate,
            extraordinary_circumstances=extraordinary_circumstances,
            overnight_delay=overnight_delay,
        )
    return CompensationEstimate(
        outcome=CompensationOutcome.NOT_ELIGIBLE,
        basis=CompensationBasis.NONE,
        amount=Money(0, "EUR"),
        currency="EUR",
        delay_minutes=delay_minutes,
        distance_km=distance_km,
        factors=[
            "No machine-readable passenger-rights regime is modelled for this departure region",
            "Check the operating carrier's conditions of carriage and your travel insurance",
        ],
        regulation_reference="",
        regulation_url="",
        last_verified="",
    )


def is_delay_extraordinary(kind: str) -> bool:
    """Whether a disruption kind counts as extraordinary circumstances.

    Weather, air traffic control restrictions, airport closure and security
    events are the recognised categories; technical faults and crew
    shortages are generally not.
    """
    return kind in {"weather", "airport_disruption", "airspace_closure", "security"}
