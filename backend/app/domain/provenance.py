"""Provenance: every outward-facing data point says where it came from.

The product must never present stale or simulated data as live, and must never
fabricate data. Provenance travels with the value.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Provenance(str, Enum):
    LIVE = "LIVE"              # answered by a provider during this request
    CACHED = "CACHED"          # a stored reading, with a fetched-at timestamp
    REFERENCE = "REFERENCE"    # a downloaded static dataset
    SIMULATED = "SIMULATED"    # injected by the Scenario Simulator
    UNAVAILABLE = "UNAVAILABLE"  # no source could answer


class Sourced(BaseModel):
    """Mixin for any value that came from somewhere."""

    model_config = ConfigDict(use_enum_values=False)

    provenance: Provenance = Provenance.UNAVAILABLE
    source: str = Field(default="Unknown source")
    fetched_at: datetime | None = None

    def badge(self) -> str:
        if self.provenance == Provenance.CACHED and self.fetched_at:
            return f"CACHED · fetched {self.fetched_at:%Y-%m-%d %H:%M}Z"
        return self.provenance.value
