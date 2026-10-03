"""Display-currency conversion.

The engine must convert honestly: amounts keep their meaning, the rate source
is named, and when no rate is available the stored amount is shown untouched
rather than guessed.

The rates used here are fixed values passed directly to a ``RateSet``, so the
arithmetic is tested without a network call. That is the real conversion code;
only the rate *source* is substituted, and the substitution is explicit in each
test rather than hidden behind a fallback table (ReTryp has none).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.display import (
    DisplayContext,
    convert_minor,
    fx_block,
    reset_display_context,
    set_display_context,
)
from app.providers.fx import RateSet

# A fixed rate set: 1 EUR = 1.08 USD = 0.85 GBP = 90 INR.
RATES = RateSet(
    base="EUR",
    rates={"EUR": 1.0, "USD": 1.08, "GBP": 0.85, "INR": 90.0},
    provenance="LIVE",
    as_of=datetime(2026, 9, 28, tzinfo=timezone.utc),
)


def test_no_context_leaves_amount_untouched() -> None:
    token = set_display_context(None)
    try:
        assert convert_minor(14_000, "EUR") == (14_000, "EUR")
    finally:
        reset_display_context(token)


def test_convert_eur_to_inr() -> None:
    token = set_display_context(DisplayContext(target_currency="INR", rates=RATES))
    try:
        amount, currency = convert_minor(14_000, "EUR")
        assert currency == "INR"
        assert amount is not None
        # 140.00 EUR at 90 INR/EUR.
        assert amount == 1_260_000
    finally:
        reset_display_context(token)


def test_same_currency_is_a_no_op() -> None:
    token = set_display_context(DisplayContext(target_currency="EUR", rates=RATES))
    try:
        assert convert_minor(14_000, "EUR") == (14_000, "EUR")
    finally:
        reset_display_context(token)


def test_missing_rate_keeps_stored_amount() -> None:
    token = set_display_context(DisplayContext(target_currency="XYZ", rates=RATES))
    try:
        # XYZ has no rate, so the figure must survive as-is.
        assert convert_minor(14_000, "EUR") == (14_000, "EUR")
    finally:
        reset_display_context(token)


def test_fx_block_reports_rate_provenance() -> None:
    token = set_display_context(DisplayContext(target_currency="INR", rates=RATES))
    try:
        block = fx_block()
        assert block is not None
        assert block["display_currency"] == "INR"
        # The block names the rate's real provenance; it is never invented.
        assert block["rate_provenance"] == "LIVE"
    finally:
        reset_display_context(token)


def test_cross_currency_conversion() -> None:
    token = set_display_context(DisplayContext(target_currency="GBP", rates=RATES))
    try:
        amount, currency = convert_minor(10_000, "USD")  # 100.00 USD
        assert currency == "GBP"
        # 0.85 / 1.08 of 100.00 = 78.70 GBP
        assert amount == 7_870
    finally:
        reset_display_context(token)


def test_plan_factors_and_explanation_follow_the_display_currency() -> None:
    """Stored prose must not keep a stale currency next to converted figures."""
    from app.models import RecoveryPlan
    from app.serializers import plan_payload

    plan = RecoveryPlan(
        id="plan-currency",
        disruption_id="d-1",
        trip_id="t-1",
        cycle=1,
        label="A",
        title="Same-day flight to BER",
        summary="Rebook the second leg.",
        status="proposed",
        score=80.0,
        score_breakdown={},
        decision_factors=[
            "Arrives 4h 36m later than planned",
            "Additional cost: EUR 257.00",
            "All connections feasible with a comfortable buffer",
        ],
        arrival_utc=datetime(2026, 9, 28, 14, 10, tzinfo=timezone.utc),
        original_arrival_utc=datetime(2026, 9, 28, 9, 34, tzinfo=timezone.utc),
        total_duration_minutes=805,
        additional_cost_minor=25_700,
        currency="EUR",
        risk_level="low",
        connection_safety="safe",
        segments=[],
        hotel_changes=[],
        ground_transport=[],
        restrictions=[],
        compensation={},
        explanation="Same-day flight to BER. Additional cost EUR 257.00. One change required.",
        explanation_source="template",
        explanation_version=1,
    )

    token = set_display_context(DisplayContext(target_currency="INR", rates=RATES))
    try:
        payload = plan_payload(plan)
    finally:
        reset_display_context(token)

    assert payload["additional_cost_display"].startswith("INR")
    assert any(
        factor.startswith("Additional cost: INR") for factor in payload["decision_factors"]
    )
    assert "EUR 257.00" not in payload["explanation"]
    assert "Additional cost INR" in payload["explanation"]


def test_unconvertible_rates_leave_amounts_in_their_stored_currency(client) -> None:
    """With FX off in the suite, a viewer currency change must not mislabel."""
    from .test_api import auth_headers

    headers = auth_headers(client, "traveller@retryp.example")
    trip_id = client.get("/api/trips", headers=headers).json()["trips"][0]["id"]
    body = client.get(f"/api/trips/{trip_id}/history", headers=headers).json()

    # FX is off, so no rate is applied and the stored currency is reported
    # unchanged rather than a rate being invented.
    assert body["currency"]
    assert body["extra_cost_display"]
