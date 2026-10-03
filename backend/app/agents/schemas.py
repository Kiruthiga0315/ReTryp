"""Typed objects exchanged between the recovery agents.

These are the contract between modules. Each agent declares what it consumes
and what it produces, and nothing is passed as a loose dict across a
boundary.

The agents are internal: none of these names ever reach the user interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import (
    ConnectionSafety,
    DisruptionKind,
    RiskLevel,
    Severity,
)
from ..domain.impact import ImpactAssessment
from ..domain.recovery import ScoredPlan


class AgentName(str, Enum):
    """Internal identifiers. Never rendered in the UI."""

    ORCHESTRATOR = "orchestrator"
    TRIP_INTELLIGENCE = "trip_intelligence"
    FLIGHT_DISRUPTION = "flight_disruption"
    WEATHER_DISRUPTION = "weather_disruption"
    AIRPORT_DISRUPTION = "airport_disruption"
    GROUND_DISRUPTION = "ground_disruption"
    PASSENGER_PROFILE = "passenger_profile"
    VISA_COMPLIANCE = "visa_compliance"
    POLICY_ELIGIBILITY = "policy_eligibility"
    BAGGAGE_CONSTRAINT = "baggage_constraint"
    FLIGHT_RECOVERY = "flight_recovery"
    TRAIN_RECOVERY = "train_recovery"
    BUS_RECOVERY = "bus_recovery"
    TRANSFER_RECOVERY = "transfer_recovery"
    HOTEL_SEARCH = "hotel_search"
    HOTEL_REBOOKING = "hotel_rebooking"
    HOTEL_CANCELLATION = "hotel_cancellation"
    ROUTE_OPTIMISATION = "route_optimisation"
    COST_OPTIMISATION = "cost_optimisation"
    TIME_OPTIMISATION = "time_optimisation"
    RISK_ASSESSMENT = "risk_assessment"
    BOOKING_EXECUTION = "booking_execution"
    CANCELLATION_REFUND = "cancellation_refund"
    COMPENSATION = "compensation"
    NOTIFICATION = "notification"
    ITINERARY_GENERATION = "itinerary_generation"
    JOURNEY_MONITORING = "journey_monitoring"
    REDISRUPTION_DETECTION = "redisruption_detection"
    RECOVERY_ESCALATION = "recovery_escalation"


class DisruptionEvent(BaseModel):
    """A validated disruption, whatever produced it."""

    model_config = ConfigDict(extra="ignore")

    kind: DisruptionKind
    trip_id: str
    segment_id: str | None = None
    hotel_id: str | None = None
    ground_id: str | None = None
    delay_minutes: int = 0
    title: str
    detail: str | None = None
    severity: Severity = Severity.HIGH
    provenance: str = "SIMULATED"
    source: str = "Scenario Simulator"
    detected_at_utc: datetime
    payload: dict = Field(default_factory=dict)
    is_extraordinary: bool = False


class ConstraintSet(BaseModel):
    """Everything a plan must satisfy for this traveller."""

    model_config = ConfigDict(extra="ignore")

    traveller_id: str
    nationality: str | None = None
    passport_expiring_soon: bool = False
    visa_notes: list[str] = Field(default_factory=list)
    transit_restrictions: list[str] = Field(default_factory=list)
    requires_baggage_recheck: bool = False
    preferred_airlines: list[str] = Field(default_factory=list)
    preferred_cabin: str | None = None
    budget_minor: int | None = None
    budget_currency: str = "INR"
    accessibility_needs: str | None = None
    policy_notes: list[str] = Field(default_factory=list)
    hard_blockers: list[str] = Field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.hard_blockers)


class Alternative(BaseModel):
    """One candidate replacement, before it is assembled into a plan."""

    model_config = ConfigDict(extra="ignore")

    key: str
    mode: str
    carrier_code: str
    carrier_name: str
    service_number: str
    origin_code: str
    destination_code: str
    departure_utc: datetime
    arrival_utc: datetime
    cost_minor: int
    currency: str
    refundable: bool
    connection_safety: ConnectionSafety = ConnectionSafety.SAFE
    buffer_minutes: int = 0
    required_minutes: int = 0
    provenance: str = "UNAVAILABLE"
    source: str = "ReTryp option catalogue"
    note: str = ""


class PlanSegmentPayload(BaseModel):
    """A replacement leg as the UI needs it, with local times precomputed."""

    model_config = ConfigDict(extra="ignore")

    key: str
    mode: str
    carrier_code: str
    carrier_name: str
    service_number: str
    origin_code: str
    origin_name: str
    origin_tz: str
    destination_code: str
    destination_name: str
    destination_tz: str
    departure_utc: datetime
    arrival_utc: datetime
    departure_local: str
    arrival_local: str
    duration_minutes: int
    cost_minor: int
    currency: str
    refundable: bool
    cabin: str | None = None
    fare_class: str | None = None
    platform: str | None = None
    terminal: str | None = None
    gate: str | None = None
    connection_safety: str = "safe"
    buffer_minutes: int = 0
    required_minutes: int = 0
    provenance: str = "UNAVAILABLE"
    note: str = ""


class RecoveryPlanPayload(BaseModel):
    """The full plan object the API and the UI consume."""

    model_config = ConfigDict(extra="ignore")

    plan_id: str
    disruption_id: str
    trip_id: str
    cycle: int = 1
    label: str
    title: str
    summary: str
    status: str = "proposed"
    recommended: bool = False
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    decision_factors: list[str] = Field(default_factory=list)
    segments: list[PlanSegmentPayload] = Field(default_factory=list)
    hotel_changes: list[dict] = Field(default_factory=list)
    ground_transport: list[dict] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    compensation: dict = Field(default_factory=dict)
    arrival_utc: datetime
    arrival_local: str
    original_arrival_utc: datetime
    original_arrival_local: str
    arrival_delta_minutes: int
    arrival_delta_display: str
    total_duration_minutes: int
    total_duration_display: str
    additional_cost_minor: int
    additional_cost_display: str
    refund_estimate_minor: int
    refund_estimate_display: str
    currency: str
    risk_level: RiskLevel
    connection_safety: ConnectionSafety
    changes_count: int
    hotel_nights_added: int = 0
    hotel_nights_lost: int = 0
    ground_transport_ok: bool = True
    provenance: str = "SIMULATED"
    explanation: str | None = None
    explanation_source: str | None = None
    explanation_version: int = 1


@dataclass
class RecoveryCycleState:
    """Working state carried through one recovery cycle.

    This is the object the LangGraph nodes read and write. It is a dataclass
    rather than a Pydantic model because it holds ORM-bound snapshots and
    partial results, and it never crosses the API boundary.
    """

    trip_id: str
    cycle: int
    disruption: DisruptionEvent
    constraints: ConstraintSet | None = None
    impact: ImpactAssessment | None = None
    alternatives: list[Alternative] = field(default_factory=list)
    plans: list[ScoredPlan] = field(default_factory=list)
    recommended_label: str | None = None
    approved_plan_id: str | None = None
    executed_action_ids: list[str] = field(default_factory=list)
    monitoring_notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stage: str = "detect"

    def note(self, message: str) -> None:
        self.monitoring_notes.append(message)
