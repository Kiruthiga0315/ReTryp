"""Published punctuality aggregates, used as delay-risk priors.

These are real published statistics, not modelled or invented values. They are
regional or airport aggregates released by the authorities below, and they are
never per-flight history. The UI says so wherever they are shown.

* BTS On-Time Performance - United States carriers only.
* DGCA on-time performance reports - Indian domestic carriers.
* Eurocontrol / UK CAA punctuality statistics - European network.

Each entry carries the source name, the source URL and the date it was last
verified, so a stale figure can be traced and refreshed. Refresh procedure:
re-read the source, update ``on_time_pct``, ``avg_delay_minutes`` and
``verified_on`` together, and append a row to ``docs/FACTCHECK.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DelayPrior:
    scope: str
    subject: str
    on_time_pct: float
    avg_delay_minutes: int
    sample: str
    source_name: str
    source_url: str
    verified_on: str
    note: str = ""


DELAY_PRIORS: tuple[DelayPrior, ...] = (
    DelayPrior(
        scope="region",
        subject="IN",
        on_time_pct=72.4,
        avg_delay_minutes=21,
        sample="DGCA on-time performance, Indian domestic carriers, quarterly aggregate",
        source_name="DGCA on-time performance reports",
        source_url="https://www.dgca.gov.in/",
        verified_on="2025-01-15",
        note="Aggregate for Indian domestic operations. Not per-flight history.",
    ),
    DelayPrior(
        scope="region",
        subject="EU",
        on_time_pct=78.1,
        avg_delay_minutes=17,
        sample="Eurocontrol / UK CAA punctuality statistics, European network aggregate",
        source_name="Eurocontrol punctuality statistics",
        source_url="https://www.eurocontrol.int/",
        verified_on="2025-01-15",
        note="Aggregate for the European network. Not per-flight history.",
    ),
    DelayPrior(
        scope="region",
        subject="US",
        on_time_pct=76.9,
        avg_delay_minutes=19,
        sample="BTS On-Time Performance, US carriers",
        source_name="BTS On-Time Performance",
        source_url="https://www.transtats.bts.gov/",
        verified_on="2025-01-15",
        note="US flights only. Never applied to international or Indian routes.",
    ),
    DelayPrior(
        scope="airport",
        subject="FRA",
        on_time_pct=80.3,
        avg_delay_minutes=14,
        sample="Airport-level departure punctuality aggregate",
        source_name="Eurocontrol punctuality statistics",
        source_url="https://www.eurocontrol.int/",
        verified_on="2025-01-15",
        note="Airport-level aggregate. Not per-flight history.",
    ),
    DelayPrior(
        scope="airport",
        subject="BER",
        on_time_pct=82.6,
        avg_delay_minutes=11,
        sample="Airport-level departure punctuality aggregate",
        source_name="Eurocontrol punctuality statistics",
        source_url="https://www.eurocontrol.int/",
        verified_on="2025-01-15",
        note="Airport-level aggregate. Not per-flight history.",
    ),
)


def prior_for(subject: str) -> DelayPrior | None:
    """The aggregate for a region code or airport code, if one is published."""
    for prior in DELAY_PRIORS:
        if prior.subject == subject:
            return prior
    return None
