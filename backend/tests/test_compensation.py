"""Passenger-rights estimates.

Thresholds are pinned against the official texts:

* EU261/2004, Articles 6 and 7 (EUR-Lex, Regulation (EC) No 261/2004).
* DGCA CAR Section 3, Series M, Part IV (India), paras 3.2.2, 3.3.2, 3.4.

If a test here fails, check the regulation before changing the number.
"""

from __future__ import annotations

from app.domain.compensation import (
    dgca_cancellation_amount,
    estimate,
    estimate_dgca,
    estimate_eu261,
    eu261_band_amount,
)
from app.domain.enums import CompensationOutcome


# --- EU261/2004 Article 7(1) distance bands ----------------------------


def test_eu261_band_amounts_by_distance() -> None:
    assert str(eu261_band_amount(400)) == "EUR 250.00"
    assert str(eu261_band_amount(1500)) == "EUR 250.00"     # boundary inclusive
    assert str(eu261_band_amount(1501)) == "EUR 400.00"
    assert str(eu261_band_amount(3500)) == "EUR 400.00"     # boundary inclusive
    assert str(eu261_band_amount(3501)) == "EUR 600.00"
    assert str(eu261_band_amount(7290)) == "EUR 600.00"     # MAA -> FRA


# --- EU261/2004 Article 6: three hours at the final destination --------


def test_eu261_short_delay_is_not_compensatable() -> None:
    result = estimate_eu261(
        distance_km=400,
        delay_minutes=150,
        departure_region="EU",
        carrier_region="EU",
    )
    assert result.outcome is CompensationOutcome.NOT_ELIGIBLE
    assert result.amount.is_zero
    assert result.care_entitlements, "care is still owed below the threshold"


def test_eu261_three_hour_delay_pays_short_haul() -> None:
    result = estimate_eu261(
        distance_km=400,
        delay_minutes=180,
        departure_region="EU",
        carrier_region="EU",
    )
    assert result.outcome is CompensationOutcome.ELIGIBLE
    assert str(result.amount) == "EUR 250.00"


def test_eu261_long_haul_three_to_four_hours_is_halved() -> None:
    """Article 7(2): a long-haul delay of 3h up to under 4h pays half of EUR 600."""
    result = estimate_eu261(
        distance_km=7290,
        delay_minutes=200,
        departure_region="EU",
        carrier_region="EU",
        re_routed=True,
    )
    assert result.outcome is CompensationOutcome.POSSIBLY_ELIGIBLE
    assert str(result.amount) == "EUR 300.00"


def test_eu261_long_haul_four_hours_pays_full() -> None:
    result = estimate_eu261(
        distance_km=7290,
        delay_minutes=240,
        departure_region="EU",
        carrier_region="EU",
        re_routed=True,
    )
    assert result.outcome is CompensationOutcome.ELIGIBLE
    assert str(result.amount) == "EUR 600.00"


def test_eu261_out_of_scope_flight_is_not_eligible() -> None:
    result = estimate_eu261(
        distance_km=400,
        delay_minutes=300,
        departure_region="IN",
        carrier_region="IN",
    )
    assert result.outcome is CompensationOutcome.NOT_ELIGIBLE
    assert result.amount.is_zero
    assert "outside EU261 scope" in " ".join(result.factors)


def test_eu261_extraordinary_circumstances_remove_compensation() -> None:
    result = estimate_eu261(
        distance_km=400,
        delay_minutes=300,
        departure_region="EU",
        carrier_region="EU",
        extraordinary_circumstances=True,
    )
    assert result.outcome is CompensationOutcome.NOT_ELIGIBLE
    assert result.amount.is_zero


# --- DGCA CAR Section 3, Series M, Part IV -----------------------------


def test_dgca_cancellation_bands_are_the_lower_of_cap_and_fare() -> None:
    # Band cap for block time over 2 hours is INR 10,000.
    assert str(dgca_cancellation_amount(180, 5_000_000)) == "INR 10,000.00"
    # Short flight, fare well below the cap: the fare is paid.
    assert str(dgca_cancellation_amount(45, 320_000)) == "INR 3,200.00"
    # 1h to 2h band cap is INR 7,500.
    assert str(dgca_cancellation_amount(90, 5_000_000)) == "INR 7,500.00"


def test_dgca_cancellation_pays_fixed_band_not_a_percentage() -> None:
    """Regression: cancellation is para 3.3.2, not the denied-boarding 200%/400%."""
    result = estimate_dgca(
        delay_minutes=0,
        one_way_fare_minor=5_000_000,  # INR 50,000, above every cap
        block_minutes=180,
        cancelled=True,
    )
    assert result.outcome is CompensationOutcome.ELIGIBLE
    assert str(result.amount) == "INR 10,000.00"
    assert "3.3.2" in result.regulation_reference


def test_dgca_denied_boarding_bands() -> None:
    within = estimate_dgca(
        delay_minutes=0,
        one_way_fare_minor=3_000_000,  # INR 30,000
        denied_boarding=True,
        alternate_within_24h=True,
    )
    # 200% of INR 30,000 = INR 60,000, capped at INR 10,000.
    assert str(within.amount) == "INR 10,000.00"
    assert within.outcome is CompensationOutcome.ELIGIBLE

    over = estimate_dgca(
        delay_minutes=0,
        one_way_fare_minor=3_000_000,
        denied_boarding=True,
        alternate_within_24h=False,
    )
    # 400% of INR 30,000 = INR 120,000, capped at INR 20,000.
    assert str(over.amount) == "INR 20,000.00"


def test_dgca_delay_alone_is_care_only() -> None:
    result = estimate_dgca(delay_minutes=300, one_way_fare_minor=3_000_000)
    assert result.outcome is CompensationOutcome.CARE_ONLY
    assert result.amount.is_zero
    assert result.refund_available is False
    assert result.care_entitlements


def test_dgca_delay_over_six_hours_offers_refund_or_alternate() -> None:
    result = estimate_dgca(delay_minutes=400, one_way_fare_minor=3_000_000)
    assert result.outcome is CompensationOutcome.CARE_ONLY
    assert result.refund_available is True


def test_dgca_extraordinary_circumstances_exempt_the_airline() -> None:
    result = estimate_dgca(
        delay_minutes=300,
        one_way_fare_minor=3_000_000,
        extraordinary_circumstances=True,
    )
    assert result.outcome is CompensationOutcome.NOT_ELIGIBLE
    assert result.amount.is_zero


# --- regime selection --------------------------------------------------


def test_india_departure_without_eu_scope_uses_dgca() -> None:
    result = estimate(
        departure_country="IN",
        carrier_country="IN",
        distance_km=1200,
        delay_minutes=240,
        one_way_fare_minor=3_000_000,
    )
    assert result.basis.value == "dgca_india"
    assert result.outcome is CompensationOutcome.CARE_ONLY


def test_eu_departure_uses_eu261() -> None:
    result = estimate(
        departure_country="DE",
        carrier_country="DE",
        distance_km=7290,
        delay_minutes=250,
    )
    assert result.basis.value == "eu261"
    assert result.outcome in (
        CompensationOutcome.ELIGIBLE,
        CompensationOutcome.POSSIBLY_ELIGIBLE,
    )


def test_unknown_region_has_no_modelled_regime() -> None:
    result = estimate(
        departure_country="US",
        carrier_country="US",
        distance_km=5000,
        delay_minutes=600,
    )
    assert result.outcome is CompensationOutcome.NOT_ELIGIBLE
    assert result.basis.value == "none"
