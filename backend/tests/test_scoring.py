"""Plan scoring.

The scorer is deterministic policy, so these tests pin the behaviour that
matters: better plans score higher, the components stay in range, and the
explanation text is plain-language with no confidence percentages.
"""

from __future__ import annotations

import re

from app.domain.enums import ConnectionSafety, RiskLevel
from app.domain.optimization import WEIGHTS, ScoreInput, score_plan


def base_input(**overrides) -> ScoreInput:
    data = dict(
        plan_id="plan-1",
        label="Plan A",
        arrival_delay_minutes=0,
        total_duration_minutes=1000,
        original_duration_minutes=1000,
        additional_cost_minor=0,
        connection_safety=ConnectionSafety.SAFE,
        worst_buffer_minutes=120,
        changes_count=0,
        hotel_nights_added=0,
        hotel_nights_lost=0,
        ground_transport_ok=True,
        uses_preferred_carrier=True,
        uses_preferred_cabin=True,
        visa_friction=False,
        risk_level=RiskLevel.LOW,
        disruption_probability=0.1,
    )
    data.update(overrides)
    return ScoreInput(**data)


def test_weights_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_ideal_plan_scores_full_marks() -> None:
    result = score_plan(base_input())
    assert result.total == 100.0
    assert all(0.0 <= v <= 1.0 for v in result.components.values())


def test_later_arrival_scores_lower_than_on_time() -> None:
    on_time = score_plan(base_input())
    late = score_plan(base_input(arrival_delay_minutes=8 * 60))
    assert late.total < on_time.total


def test_extra_cost_scores_lower() -> None:
    free = score_plan(base_input())
    costly = score_plan(base_input(additional_cost_minor=45_000))
    assert costly.total < free.total


def test_broken_connection_weighs_heavily() -> None:
    safe = score_plan(base_input())
    broken = score_plan(base_input(connection_safety=ConnectionSafety.BROKEN))
    assert broken.components["connection"] == 0.0
    assert broken.total < safe.total


def test_more_changes_and_hotel_nights_reduce_the_score() -> None:
    clean = score_plan(base_input())
    messy = score_plan(base_input(changes_count=4, hotel_nights_added=2, hotel_nights_lost=1))
    assert messy.total < clean.total


def test_visa_friction_reduces_the_score() -> None:
    clear = score_plan(base_input())
    friction = score_plan(base_input(visa_friction=True))
    assert friction.total < clear.total


def test_factors_are_plain_language_with_no_confidence_numbers() -> None:
    result = score_plan(
        base_input(arrival_delay_minutes=80, additional_cost_minor=4_200, changes_count=1)
    )
    joined = " ".join(result.factors)
    assert "Arrives 1h 20m later than planned" in joined
    assert "Additional cost" in joined
    assert not re.search(r"\b\d+(\.\d+)?\s?%", joined), "no confidence percentages"
    assert "AI" not in joined and "recommend" not in joined.lower()


def test_score_is_deterministic() -> None:
    first = score_plan(base_input(arrival_delay_minutes=45))
    second = score_plan(base_input(arrival_delay_minutes=45))
    assert first.total == second.total
    assert first.components == second.components
