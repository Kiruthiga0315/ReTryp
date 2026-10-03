"""Connectivity graph and live-search contract tests.

The graph must answer for any pair the loaded datasets know about, offer a
concrete connecting route when no direct service exists, and never invent an
edge. These tests use the reference data only, so they need no network.
"""

from __future__ import annotations

from app.domain import graph


def test_graph_covers_the_reference_network() -> None:
    coverage = graph.served_coverage()
    assert coverage["nodes"] > 2000
    assert coverage["edges"] > 5000
    assert "OpenFlights route pairs" in coverage["sources"]


def test_direct_service_is_detected() -> None:
    assert graph.is_served("MAA", "FRA") is True
    assert graph.is_served("BER", "MAA") is False


def test_same_market_is_not_a_service() -> None:
    # Two codes in the same city are not a leg a traveller needs.
    assert graph.is_served("BER", "BER_AIR") is False


def test_path_bridges_through_a_hub() -> None:
    path = graph.find_path("MAA", "BER")
    assert path is not None
    assert path[0] == "MAA"
    assert path[-1] in {"BER", "BER_AIR", "BER_HBF"}
    assert len(path) >= 3, "MAA to Berlin needs a change"


def test_path_respects_the_hop_limit() -> None:
    # A one-hop limit cannot bridge two continents.
    assert graph.find_path("MAA", "BER", max_hops=1) is None


def test_unconnected_place_has_no_path() -> None:
    assert graph.find_path("MAA", "ZZZ") is None


def test_bridges_offer_a_concrete_hub() -> None:
    bridges = graph.suggest_bridges("MAA", "BER")
    assert bridges, "a pair with no direct service must suggest a connection"
    assert all(b["via"] and b["via_name"] for b in bridges)
    # The bridge must genuinely reach the destination market.
    assert any(b["via"] == "FRA" for b in bridges)


def test_no_service_pair_suggests_nothing_invented() -> None:
    # A place with no edges cannot have a bridge invented for it.
    assert graph.suggest_bridges("ZZZ", "MAA") == []


def test_hub_rank_is_ordered() -> None:
    hubs = graph.hub_rank(limit=5)
    degrees = [d for _, d in hubs]
    assert degrees == sorted(degrees, reverse=True)


def test_nearest_nodes_are_ordered_by_distance() -> None:
    # Central Berlin.
    places = graph.nearest_nodes(52.52, 13.40, limit=5)
    assert places
    distances = [p["distance_km"] for p in places]
    assert distances == sorted(distances)
    assert places[0]["country"] == "DE"


def test_recording_a_live_pair_adds_an_edge() -> None:
    # A provider-confirmed pair becomes served for the rest of the process.
    # ANR is a single-route airport, so MAA-ANR is genuinely absent upstream.
    assert graph.is_served("MAA", "ANR") is False
    graph.record_live_pair("MAA", "ANR")
    assert graph.is_served("MAA", "ANR") is True
