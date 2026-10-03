"""Request and response schemas for the REST API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .domain.enums import DisruptionKind, Role


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    full_name: str = Field(min_length=1, max_length=160)
    role: Role = Role.TRAVELLER


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    home_airport: str | None = Field(default=None, max_length=8)
    preferred_airlines: list[str] | None = None
    preferred_seat: str | None = Field(default=None, max_length=32)
    preferred_cabin: str | None = Field(default=None, max_length=32)
    hotel_preferences: dict | None = None
    ground_preferences: dict | None = None
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3)
    budget_minor: int | None = Field(default=None, ge=0)
    accessibility_needs: str | None = Field(default=None, max_length=2000)
    passport_masked: str | None = Field(default=None, max_length=32)
    passport_nationality: str | None = Field(default=None, min_length=2, max_length=2)
    passport_expiry: str | None = Field(default=None, max_length=10)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notifications: dict | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    language: str | None = Field(default=None, max_length=8)
    timezone: str | None = Field(default=None, max_length=64)
    travel_preferences: dict | None = None
    privacy: dict | None = None


class SimulateDisruptionRequest(BaseModel):
    """Input for the Scenario Simulator (admin only)."""

    model_config = ConfigDict(extra="forbid")

    trip_id: str
    kind: DisruptionKind
    segment_id: str | None = None
    hotel_id: str | None = None
    ground_id: str | None = None
    delay_minutes: int = Field(default=0, ge=0, le=2880)
    detail: str | None = Field(default=None, max_length=2000)
    baggage_recheck: bool = False
    auto_generate_plans: bool = True


class ApprovePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    confirmation: bool = Field(
        description="Must be true. The UI sets this after the confirmation dialog."
    )


class HelpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str | None = None
    trip_id: str | None = None
    topic: str
    question: str | None = Field(default=None, max_length=500)


class JourneySegmentSelection(BaseModel):
    """One leg the traveller chose on the journey builder screen."""

    model_config = ConfigDict(extra="forbid")

    service_key: str = Field(max_length=120)
    origin: str = Field(min_length=2, max_length=8)
    destination: str = Field(min_length=2, max_length=8)
    date: str = Field(description="Local departure day, YYYY-MM-DD")
    mode: str = Field(description="flight | train | bus | transfer")


class BuildJourneyRequest(BaseModel):
    """Compose and persist a trip, then check it and open a recovery cycle."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    reason: str = Field(default="business", max_length=64)
    origin: str = Field(min_length=2, max_length=8)
    destination: str = Field(min_length=2, max_length=8)
    date: str = Field(description="Local departure day, YYYY-MM-DD")
    segments: list[JourneySegmentSelection] = Field(min_length=1, max_length=12)
    # An optional disruption to check against immediately, so the traveller
    # sees the recovery cycle as soon as the trip exists.
    disrupted_service_key: str | None = Field(default=None, max_length=120)
    disruption_kind: str | None = Field(default=None, max_length=48)
    delay_minutes: int = Field(default=0, ge=0, le=2880)

    @field_validator("date")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("date must be YYYY-MM-DD") from exc
        return value

    @field_validator("segments")
    @classmethod
    def _valid_dates(cls, value: list[JourneySegmentSelection]) -> list[JourneySegmentSelection]:
        for item in value:
            try:
                date.fromisoformat(item.date)
            except ValueError as exc:  # pragma: no cover - defensive
                raise ValueError("segment date must be YYYY-MM-DD") from exc
        return value


class RecoverJourneyRequest(BaseModel):
    """Re-check a built trip and open a new recovery cycle when needed."""

    model_config = ConfigDict(extra="forbid")

    disruption_kind: str = Field(default="missed_connection", max_length=48)
    service_key: str | None = Field(default=None, max_length=120)
    delay_minutes: int = Field(default=0, ge=0, le=2880)


class HelpResponse(BaseModel):
    topic: str
    answer: str
    source: str
    related: dict = Field(default_factory=dict)


class NotificationReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_ids: list[str] = Field(default_factory=list)
    all: bool = False


class TimestampedModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    created_at: datetime | None = None
