"""Covering-cache fallback for the OpenStreetMap transit harvest.

Overpass is donated infrastructure and occasionally unreachable. When it is,
a previously stored harvest that covers the point still answers, filtered to
the radius the caller asked for.
"""

import json
import time

from app.providers import transit


def _payload(nodes):
    return {
        "stored_at": time.time(),
        "fetched_at": "2026-09-28T00:00:00Z",
        "source": "OpenStreetMap contributors (ODbL)",
        "nodes": nodes,
    }


def _node(osm_id, name, lat, lon):
    return {
        "osm_id": osm_id,
        "name": name,
        "kind": "rail",
        "lat": lat,
        "lon": lon,
        "operator": None,
        "network": None,
        "country": None,
    }


def test_cached_near_filters_to_requested_radius(tmp_path, monkeypatch):
    monkeypatch.setattr(transit, "CACHE_DIR", tmp_path)
    (tmp_path / "osm_transit_52.520_13.400_25.json").write_text(
        json.dumps(
            _payload(
                [
                    _node("node/1", "Berlin Hbf", 52.525, 13.369),
                    _node("node/2", "Far Away", 52.9, 13.9),
                ]
            )
        )
    )

    got = transit._cached_near(52.52, 13.405, 15.0)

    assert got is not None
    names = [n["name"] for n in got["nodes"]]
    assert "Berlin Hbf" in names
    assert "Far Away" not in names


def test_cached_near_is_none_when_nothing_covers(tmp_path, monkeypatch):
    monkeypatch.setattr(transit, "CACHE_DIR", tmp_path)
    (tmp_path / "osm_transit_52.520_13.400_15.json").write_text(json.dumps(_payload([])))

    assert transit._cached_near(48.85, 2.35, 15.0) is None


def test_cached_near_ignores_expired_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(transit, "CACHE_DIR", tmp_path)
    payload = _payload([_node("node/1", "Berlin Hbf", 52.525, 13.369)])
    payload["stored_at"] = time.time() - transit.CACHE_TTL_SECONDS - 10
    (tmp_path / "osm_transit_52.520_13.400_25.json").write_text(json.dumps(payload))

    assert transit._cached_near(52.52, 13.405, 15.0) is None
