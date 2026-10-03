"""The recovery cycle as a LangGraph state machine.

    detect -> assess -> search -> constrain -> generate -> score
      -> present -> [human approval interrupt] -> execute -> monitor
                                                  ^                |
                                                  |                v
                                                  +--- escalate ---+

The service functions in ``pipeline.py`` hold the real logic. This module
sequences them and provides the interrupt point where the traveller's
approval is required, and the escalation edge that re-enters the cycle when
monitoring finds the active plan no longer valid.

The graph is internal. No node name is ever shown to a user.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .schemas import AgentName

NodeName = Literal[
    "detect",
    "assess",
    "search",
    "constrain",
    "generate",
    "score",
    "present",
    "execute",
    "monitor",
    "escalate",
]


class CycleState(TypedDict, total=False):
    """The graph's state. Plain data only, so it can be checkpointed."""

    trip_id: str
    cycle: int
    disruption_id: str
    approved_plan_id: str | None
    stage: str
    assessment: dict
    constraints: dict
    plan_labels: list[str]
    recommended_label: str | None
    monitoring: dict
    notes: list[str]
    escalated: bool


NODE_ORDER: list[NodeName] = [
    "detect",
    "assess",
    "search",
    "constrain",
    "generate",
    "score",
    "present",
    "execute",
    "monitor",
]


def node_agents() -> dict[str, list[AgentName]]:
    """Which internal agents participate in each node.

    Kept as data so the mapping is inspectable in tests and in the docs
    without reading the graph body.
    """
    return {
        "detect": [AgentName.FLIGHT_DISRUPTION, AgentName.WEATHER_DISRUPTION,
                   AgentName.AIRPORT_DISRUPTION, AgentName.GROUND_DISRUPTION],
        "assess": [AgentName.TRIP_INTELLIGENCE, AgentName.RISK_ASSESSMENT],
        "search": [AgentName.FLIGHT_RECOVERY, AgentName.TRAIN_RECOVERY,
                   AgentName.BUS_RECOVERY, AgentName.TRANSFER_RECOVERY],
        "constrain": [AgentName.PASSENGER_PROFILE, AgentName.VISA_COMPLIANCE,
                      AgentName.POLICY_ELIGIBILITY, AgentName.BAGGAGE_CONSTRAINT],
        "generate": [AgentName.FLIGHT_RECOVERY, AgentName.TRAIN_RECOVERY,
                     AgentName.HOTEL_SEARCH, AgentName.HOTEL_REBOOKING,
                     AgentName.HOTEL_CANCELLATION, AgentName.ITINERARY_GENERATION],
        "score": [AgentName.ROUTE_OPTIMISATION, AgentName.COST_OPTIMISATION,
                  AgentName.TIME_OPTIMISATION, AgentName.RISK_ASSESSMENT],
        "present": [AgentName.NOTIFICATION, AgentName.ITINERARY_GENERATION],
        "execute": [AgentName.BOOKING_EXECUTION, AgentName.CANCELLATION_REFUND,
                    AgentName.COMPENSATION],
        "monitor": [AgentName.JOURNEY_MONITORING, AgentName.REDISRUPTION_DETECTION],
        "escalate": [AgentName.RECOVERY_ESCALATION, AgentName.ORCHESTRATOR],
    }


def build_graph(handlers: dict[str, Any]):
    """Wire the cycle.

    ``handlers`` maps each node name to a callable taking the state and
    returning a partial state update. Passing them in keeps this module free
    of database imports, which makes the graph testable on its own.
    """
    graph = StateGraph(CycleState)

    for name in NODE_ORDER:
        if name in handlers:
            graph.add_node(name, handlers[name])

    graph.set_entry_point("detect")

    def after_present(state: CycleState) -> str:
        # Human approval is required before anything is executed.
        return "execute"

    def after_monitor(state: CycleState) -> str:
        if state.get("monitoring", {}).get("healthy", True):
            return END
        return "escalate"

    graph.add_edge("detect", "assess")
    graph.add_edge("assess", "search")
    graph.add_edge("search", "constrain")
    graph.add_edge("constrain", "generate")
    graph.add_edge("generate", "score")
    graph.add_edge("score", "present")
    graph.add_conditional_edges("present", after_present, {"execute": "execute"})
    graph.add_edge("execute", "monitor")

    if "escalate" in handlers:
        graph.add_conditional_edges(
            "monitor", after_monitor, {"escalate": "escalate", END: END}
        )
        graph.add_edge("escalate", "detect")
    else:
        graph.add_edge("monitor", END)

    return graph.compile(checkpointer=MemorySaver())


def approval_interrupt(plan_summary: dict) -> str:
    """The pause point where a traveller decision is required.

    LangGraph's ``interrupt`` suspends the graph; resuming with a decision
    continues into execution. The summary passed here is what a human would
    need to decide, nothing more.
    """
    decision = interrupt({"awaiting": "plan_approval", "plans": plan_summary})
    return str(decision)
