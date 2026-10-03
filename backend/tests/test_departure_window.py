"""The AeroDataBox departure window must cover the origin's whole local day.

The endpoint caps one request at 12 hours and reads its window as the airport's
local wall clock. Requesting only the first 12 hours of a UTC-anchored day made
every pair whose flights leave in the evening of the local day look unserved:
Singapore to Frankfurt and Singapore to Chennai both returned nothing. These
tests drive the window walk with a fake transport, so they never call the API.
"""

from datetime import datetime, timezone

import pytest

from app.providers import flights


class _Recorder(flights.AeroDataBoxProvider):
    """An AeroDataBox provider that records windows instead of fetching them."""

    def __init__(self):
        self.windows = []

    async def _departures_window(self, origin_iata, start, end):  # type: ignore[override]
        self.windows.append((origin_iata, start, end))
        return []


@pytest.mark.asyncio
async def test_windows_cover_the_full_local_day():
    provider = _Recorder()
    # 2026-09-29 00:00 UTC is 08:00 in Singapore.
    await provider._departures_day("SIN", datetime(2026, 9, 29, 0, tzinfo=timezone.utc))

    assert len(provider.windows) == 2
    _, first_start, first_end = provider.windows[0]
    _, second_start, second_end = provider.windows[1]

    # Times are naive local wall clock: 08:00-20:00 and 20:00-08:00 next day.
    assert (first_start, first_end) == (
        datetime(2026, 9, 29, 8, 0),
        datetime(2026, 9, 29, 20, 0),
    )
    assert (second_start, second_end) == (
        datetime(2026, 9, 29, 20, 0),
        datetime(2026, 9, 30, 8, 0),
    )


@pytest.mark.asyncio
async def test_each_window_is_within_the_api_limit():
    provider = _Recorder()
    await provider._departures_day("SIN", datetime(2026, 9, 29, 0, tzinfo=timezone.utc))

    for _, start, end in provider.windows:
        assert (end - start).total_seconds() / 3600 <= flights.WINDOW_HOURS


@pytest.mark.asyncio
async def test_window_walk_is_contiguous():
    provider = _Recorder()
    await provider._departures_day("MAA", datetime(2026, 9, 29, 0, tzinfo=timezone.utc))

    for (_, _, previous_end), (_, next_start, _) in zip(provider.windows, provider.windows[1:]):
        assert previous_end == next_start


@pytest.mark.asyncio
async def test_a_failed_chunk_keeps_the_rest(monkeypatch):
    """One window erroring must not discard the windows that succeeded."""
    provider = _Recorder()
    real = provider._departures_window
    calls = {"n": 0}

    async def flaky(origin_iata, start, end):
        calls["n"] += 1
        if calls["n"] == 1:
            raise flights.ProviderError("window failed", retryable=True)
        return await real(origin_iata, start, end)

    monkeypatch.setattr(provider, "_departures_window", flaky)

    rows = await provider._departures_day("SIN", datetime(2026, 9, 29, 0, tzinfo=timezone.utc))

    assert rows == []
    assert calls["n"] == 2
