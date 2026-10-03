"""Authentication, profile and settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..domain.enums import AuditAction, Role
from ..models import User
from ..schemas import (
    ProfileUpdate,
    SettingsUpdate,
    SignInRequest,
    SignUpRequest,
)
from ..security import (
    SESSION_COOKIE,
    create_session,
    current_user,
    hash_password,
    log_audit,
    mask_passport,
    revoke_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "phone": user.phone,
        "home_airport": user.home_airport,
        "preferred_airlines": user.preferred_airlines or [],
        "preferred_seat": user.preferred_seat,
        "preferred_cabin": user.preferred_cabin,
        "hotel_preferences": user.hotel_preferences or {},
        "ground_preferences": user.ground_preferences or {},
        "budget_currency": user.budget_currency,
        "budget_minor": user.budget_minor,
        "accessibility_needs": user.accessibility_needs,
        # Always masked, even to the owner, unless they explicitly reveal it.
        "passport_masked": user.passport_masked,
        "passport_nationality": user.passport_nationality,
        "passport_expiry": user.passport_expiry,
        "settings": user.settings or {},
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def sign_up(
    payload: SignUpRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalars(select(User).where(User.email == payload.email.lower())).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    # Self-service signup cannot mint an admin account.
    role = payload.role.value if payload.role != Role.ADMIN else Role.TRAVELLER.value
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=role,
        settings={
            "notifications": {"disruption": True, "plan_ready": True, "execution": True},
            "currency": "INR",
            "language": "en",
            "timezone": "UTC",
            "travel_preferences": {},
            "privacy": {"share_itinerary_with_manager": True},
        },
    )
    db.add(user)
    db.flush()

    token, _ = create_session(db, user=user, user_agent=request.headers.get("user-agent"))
    log_audit(db, action=AuditAction.USER_CREATED.value, summary=f"Account created for {user.email}", actor=user)
    db.commit()

    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
    )
    return {"user": user_payload(user), "token": token}


@router.post("/signin")
def sign_in(
    payload: SignInRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalars(select(User).where(User.email == payload.email.lower())).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        # One message for both cases: never reveal whether an email exists.
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    token, _ = create_session(db, user=user, user_agent=request.headers.get("user-agent"))
    log_audit(db, action=AuditAction.LOGIN.value, summary=f"{user.full_name} signed in", actor=user)
    db.commit()

    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
    )
    return {"user": user_payload(user), "token": token}


@router.post("/signout")
def sign_out(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    header = request.headers.get("authorization")
    token = header[7:].strip() if header and header.lower().startswith("bearer ") else request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token=token)
    log_audit(db, action=AuditAction.LOGOUT.value, summary=f"{user.full_name} signed out", actor=user)
    db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_payload(user)}


@router.patch("/profile")
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if "passport_masked" in data:
        # Store only the masked form. The full number never reaches the database.
        data["passport_masked"] = mask_passport(data["passport_masked"])
    for field, value in data.items():
        setattr(user, field, value)
    log_audit(db, action="profile_updated", summary=f"{user.full_name} updated their profile", actor=user)
    db.commit()
    return {"user": user_payload(user)}


@router.patch("/settings")
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    current = dict(user.settings or {})
    for field, value in data.items():
        if isinstance(value, dict) and isinstance(current.get(field), dict):
            current[field] = {**current[field], **value}
        else:
            current[field] = value
    user.settings = current
    log_audit(db, action="settings_updated", summary=f"{user.full_name} updated settings", actor=user)
    db.commit()
    return {"settings": current}
