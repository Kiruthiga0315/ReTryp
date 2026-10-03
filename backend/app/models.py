"""SQLAlchemy ORM models.

Two families live here:

* ``User``/``AuthSession``/``AuditLog``/``Notification`` - platform state.
* ``Trip``/``Segment``/``HotelStay``/``GroundTransport``/``Disruption``/
  ``RecoveryPlan``/``PlanAction``/``TripEvent`` - journey state.

All timestamps are stored as timezone-aware UTC. SQLite has no native
timezone support, so ``UtcDateTime`` is used and the application
guarantees UTC on write.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UtcDateTime


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="traveller", index=True)
    manager_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # profile
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    home_airport: Mapped[str | None] = mapped_column(String(8), nullable=True)
    preferred_airlines: Mapped[list] = mapped_column(JSON, default=list)
    preferred_seat: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_cabin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hotel_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    ground_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_currency: Mapped[str] = mapped_column(String(3), default="INR")
    budget_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accessibility_needs: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Masked only. Full passport data is never stored or logged.
    passport_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    passport_nationality: Mapped[str | None] = mapped_column(String(2), nullable=True)
    passport_expiry: Mapped[str | None] = mapped_column(String(10), nullable=True)

    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    trips: Mapped[list["Trip"]] = relationship(back_populates="traveller")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    traveller_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    reference: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_code: Mapped[str] = mapped_column(String(8))
    destination_code: Mapped[str] = mapped_column(String(8))
    starts_at_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    ends_at_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Immutable snapshot of the itinerary as first loaded, taken before any
    # recovery rewrote it. Resetting to this restores the original booking.
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    traveller: Mapped[User] = relationship(back_populates="trips")
    segments: Mapped[list["Segment"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="Segment.sequence"
    )
    hotels: Mapped[list["HotelStay"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )
    ground: Mapped[list["GroundTransport"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )
    disruptions: Mapped[list["Disruption"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )


class Segment(Base):
    """A leg of the journey: flight, train, bus, transfer, taxi or rental car."""

    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    segment_type: Mapped[str] = mapped_column(String(16), default="flight")
    carrier_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    service_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    origin_code: Mapped[str] = mapped_column(String(8))
    origin_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    origin_tz: Mapped[str] = mapped_column(String(64))
    destination_code: Mapped[str] = mapped_column(String(8))
    destination_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    destination_tz: Mapped[str] = mapped_column(String(64))

    scheduled_departure_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    scheduled_arrival_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    estimated_departure_utc: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    estimated_arrival_utc: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    actual_departure_utc: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    actual_arrival_utc: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    status: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    booking_reference: Mapped[str | None] = mapped_column(String(24), nullable=True)
    terminal: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gate: Mapped[str | None] = mapped_column(String(8), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(12), nullable=True)
    cabin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fare_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    refundable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    provenance: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    is_recovery: Mapped[bool] = mapped_column(Boolean, default=False)
    replaces_segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="segments")

    @property
    def effective_departure_utc(self) -> datetime:
        return (
            self.actual_departure_utc
            or self.estimated_departure_utc
            or self.scheduled_departure_utc
        )

    @property
    def effective_arrival_utc(self) -> datetime:
        return (
            self.actual_arrival_utc
            or self.estimated_arrival_utc
            or self.scheduled_arrival_utc
        )


class HotelStay(Base):
    __tablename__ = "hotel_stays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    city_code: Mapped[str] = mapped_column(String(8))
    city_name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    check_out_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    rooms: Mapped[int] = mapped_column(Integer, default=1)
    guests: Mapped[int] = mapped_column(Integer, default=1)
    booking_reference: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="confirmed")
    late_arrival_notice: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    refundable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="hotels")


class GroundTransport(Base):
    __tablename__ = "ground_transport"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16), default="transfer")
    provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    from_label: Mapped[str] = mapped_column(String(200))
    to_label: Mapped[str] = mapped_column(String(200))
    city_code: Mapped[str] = mapped_column(String(8))
    timezone: Mapped[str] = mapped_column(String(64))
    pickup_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    dropoff_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    booking_reference: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="confirmed")
    cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="ground")


class Disruption(Base):
    __tablename__ = "disruptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hotel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ground_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), default="detected", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="high")
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_at_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    resolved_at_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="SIMULATED")
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    parent_disruption_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    trip: Mapped[Trip] = relationship(back_populates="disruptions")
    plans: Mapped[list["RecoveryPlan"]] = relationship(
        back_populates="disruption", cascade="all, delete-orphan"
    )


class RecoveryPlan(Base):
    __tablename__ = "recovery_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    disruption_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("disruptions.id", ondelete="CASCADE")
    )
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_factors: Mapped[list] = mapped_column(JSON, default=list)
    arrival_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    original_arrival_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    total_duration_minutes: Mapped[int] = mapped_column(Integer)
    additional_cost_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    refund_estimate_minor: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")
    connection_safety: Mapped[str] = mapped_column(String(16), default="safe")
    segments: Mapped[list] = mapped_column(JSON, default=list)
    hotel_changes: Mapped[list] = mapped_column(JSON, default=list)
    ground_transport: Mapped[list] = mapped_column(JSON, default=list)
    restrictions: Mapped[list] = mapped_column(JSON, default=list)
    compensation: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(16), default="SIMULATED")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    explanation_version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    disruption: Mapped[Disruption] = relationship(back_populates="plans")
    actions: Mapped[list["PlanAction"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanAction(Base):
    """One executable step of a plan, with an honest execution state."""

    __tablename__ = "plan_actions"
    __table_args__ = (UniqueConstraint("plan_id", "idempotency_key", name="uq_action_idem"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recovery_plans.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str] = mapped_column(String(40))
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="change_requested")
    idempotency_key: Mapped[str] = mapped_column(String(120))
    cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    executed_at_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)

    plan: Mapped[RecoveryPlan] = relationship(back_populates="actions")


class TripEvent(Base):
    """Append-only journey event log, feeds the timeline and audit views."""

    __tablename__ = "trip_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"))
    occurred_at_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(16), default="SIMULATED")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    read_at_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    provenance: Mapped[str] = mapped_column(String(16), default="SIMULATED")
    wording_source: Mapped[str | None] = mapped_column(String(24), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    occurred_at_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(String(255))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class MonitoringState(Base):
    """Per-trip monitoring loop state, so re-disruption can be replayed."""

    __tablename__ = "monitoring_state"

    trip_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    active_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cycle: Mapped[int] = mapped_column(Integer, default=0)
    watching: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
