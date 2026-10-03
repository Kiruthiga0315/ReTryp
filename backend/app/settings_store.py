"""Platform data status.

ReTryp has one mode: real sources. It ships a downloaded reference database
and, when configured, queries live providers. There is no demonstration
catalogue to switch to.

What lives here is *reporting*: the header badge and the Settings screen both
need to know which real sources are answering right now. That is derived from
the configured providers, not stored as a user preference.
"""

from __future__ import annotations

from .config import get_settings
from .domain.provenance import Provenance

# The fixed badge for this instance. Kept as a name so callers read clearly.
DATA_MODE = "real"


def current_data_status() -> dict:
    """A compact description of where the running data comes from."""
    from .providers.flights import build_flight_provider

    settings = get_settings()
    provider = build_flight_provider(settings)
    live = provider.name != "unconfigured"
    return {
        "mode": DATA_MODE,
        "flight_provider": provider.name,
        "live_providers": [provider.name] if live else [],
        "live_schedules": live,
        "provenance": Provenance.LIVE.value if live else Provenance.UNAVAILABLE.value,
    }
