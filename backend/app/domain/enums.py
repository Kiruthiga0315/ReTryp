"""Enumerations shared by models, agents and the API."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class SegmentType(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    TAXI = "taxi"
    TRANSFER = "transfer"
    RENTAL_CAR = "rental_car"


class SegmentStatus(StrEnum):
    SCHEDULED = "scheduled"
    ON_TIME = "on_time"
    AT_RISK = "at_risk"
    DELAYED = "delayed"
    DISRUPTED = "disrupted"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    COMPLETED = "completed"
    MISSED = "missed"


class TripStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    DISRUPTED = "disrupted"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CHANGE_REQUESTED = "change_requested"
    PENDING_PROVIDER = "pending_provider_confirmation"
    RECORDED_OFFLINE = "recorded_offline"
    CANCELLED = "cancelled"
    UNCHANGED = "unchanged"


class DisruptionKind(StrEnum):
    FLIGHT_DELAY = "flight_delay"
    FLIGHT_CANCELLATION = "flight_cancellation"
    MISSED_CONNECTION = "missed_connection"
    WEATHER = "weather"
    AIRPORT_DISRUPTION = "airport_disruption"
    DENIED_BOARDING = "denied_boarding"
    GROUND_TRANSPORT = "ground_transport_disruption"
    HOTEL_CANCELLATION = "hotel_cancellation"
    VISA_TRANSIT = "visa_transit_restriction"


class DisruptionStatus(StrEnum):
    DETECTED = "detected"
    VALIDATED = "validated"
    ASSESSED = "assessed"
    RECOVERING = "recovering"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    # Closed because a newer disruption opened a fresh cycle. Kept for history
    # so the trip shows one active incident rather than a stack of them.
    SUPERSEDED = "superseded"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ConnectionSafety(StrEnum):
    SAFE = "safe"
    TIGHT = "tight"
    AT_RISK = "at_risk"
    BROKEN = "broken"


class Role(StrEnum):
    TRAVELLER = "traveller"
    TRAVEL_MANAGER = "travel_manager"
    ADMIN = "admin"


class NotificationKind(StrEnum):
    DISRUPTION = "disruption"
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    EXECUTION = "execution"
    MONITORING = "monitoring"
    RECOVERY = "recovery"
    COMPENSATION = "compensation"
    SYSTEM = "system"


class RefundStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    ESTIMATED = "estimated"
    REQUESTED = "requested"
    PROCESSED = "processed"


class CompensationBasis(StrEnum):
    EU261 = "eu261"
    DGCA_INDIA = "dgca_india"
    NONE = "none"


class CompensationOutcome(StrEnum):
    ELIGIBLE = "potential_eligibility"
    POSSIBLY_ELIGIBLE = "possible_eligibility"
    NOT_ELIGIBLE = "not_eligible"
    CARE_ONLY = "care_only"


class AuditAction(StrEnum):
    DISRUPTION_DETECTED = "disruption_detected"
    IMPACT_ASSESSED = "impact_assessed"
    PLAN_GENERATED = "plan_generated"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    NOTIFICATION_SENT = "notification_sent"
    MONITORING_ALERT = "monitoring_alert"
    ESCALATION_TRIGGERED = "escalation_triggered"
    LOGIN = "login"
    LOGOUT = "logout"
    USER_CREATED = "user_created"
    TRIP_CREATED = "trip_created"
    RECOVERY_RESET = "recovery_reset"
