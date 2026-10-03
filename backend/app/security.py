"""Authentication and authorisation.

Email and password with server-side sessions. Passwords are hashed with
PBKDF2-HMAC-SHA256 and a per-user salt. Session tokens are stored hashed, so
a database leak does not hand over live sessions.

Passport data is stored masked. Nothing in this module logs a credential, a
token, or a passport number.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .domain.enums import Role
from .models import AuditLog, AuthSession, User, utcnow

PBKDF2_ROUNDS = 260_000
SESSION_COOKIE = "retryp_session"


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(rounds)
    ).hex()
    return hmac.compare_digest(candidate, digest)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, *, user: User, user_agent: str | None = None) -> tuple[str, AuthSession]:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=hash_token(token),
        user_id=user.id,
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    db.flush()
    return token, session


def revoke_session(db: Session, *, token: str) -> None:
    session = db.scalars(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).first()
    if session is not None:
        session.revoked_at = utcnow()
        db.flush()


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.scalars(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).first()
    if session is None or session.revoked_at is not None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        return None
    return db.get(User, session.user_id)


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def token_from_request(request: Request) -> str | None:
    """Public alias so non-router callers (middleware) can resolve a session."""
    return _token_from_request(request)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the caller, or reject the request."""
    user = user_from_token(db, _token_from_request(request))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: Role):
    """Dependency factory enforcing role-based access on an endpoint."""

    allowed = {r.value for r in roles}

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action",
            )
        return user

    return dependency


def can_view_user(actor: User, target: User) -> bool:
    """A traveller sees only themselves; a manager sees their travellers."""
    if actor.id == target.id:
        return True
    if actor.role == Role.ADMIN.value:
        return True
    if actor.role == Role.TRAVEL_MANAGER.value:
        return target.manager_id == actor.id or target.id == actor.id
    return False


def visible_traveller_ids(db: Session, actor: User) -> list[str]:
    """Which travellers' trips the actor may read."""
    if actor.role == Role.ADMIN.value:
        return [u.id for u in db.scalars(select(User)).all()]
    if actor.role == Role.TRAVEL_MANAGER.value:
        managed = db.scalars(select(User.id).where(User.manager_id == actor.id)).all()
        return [actor.id, *managed]
    return [actor.id]


def mask_passport(value: str | None) -> str | None:
    """Keep only the last two characters. Used everywhere a passport is shown."""
    if not value:
        return None
    cleaned = value.strip()
    if len(cleaned) <= 2:
        return "*" * len(cleaned)
    return "*" * (len(cleaned) - 2) + cleaned[-2:]


def log_audit(
    db: Session,
    *,
    action: str,
    summary: str,
    actor: User | None = None,
    trip_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        trip_id=trip_id,
        action=action,
        summary=summary,
        detail=detail or {},
    )
    db.add(entry)
    db.flush()
    return entry
