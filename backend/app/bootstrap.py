"""Bootstrap the application's user accounts.

ReTryp ships no demonstration catalogue and seeds no trips. A trip is created
by a traveller through the Journey Builder, from real sources. This module only
creates the accounts needed to sign in.

Usage::

    python -m app.bootstrap

Accounts and password come from the environment when set:

* ``BOOTSTRAP_ADMIN_EMAIL`` (default ``ops@retryp.example``)
* ``BOOTSTRAP_MANAGER_EMAIL`` (default ``manager@retryp.example``)
* ``BOOTSTRAP_TRAVELLER_EMAIL`` (default ``traveller@retryp.example``)
* ``BOOTSTRAP_PASSWORD`` (default generated and printed once)
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .domain.enums import Role
from .models import User
from .security import hash_password

ACCOUNT_SPECS = (
    ("BOOTSTRAP_ADMIN_EMAIL", "ops@retryp.example", "Administrator", Role.ADMIN.value),
    ("BOOTSTRAP_MANAGER_EMAIL", "manager@retryp.example", "Travel Manager", Role.TRAVEL_MANAGER.value),
    ("BOOTSTRAP_TRAVELLER_EMAIL", "traveller@retryp.example", "Traveller", Role.TRAVELLER.value),
)


def _password() -> tuple[str, bool]:
    """The bootstrap password, or a generated one. Returns (value, generated)."""
    configured = os.environ.get("BOOTSTRAP_PASSWORD", "").strip()
    if configured:
        return configured, False
    return secrets.token_urlsafe(12), True


def create_accounts(db, password: str) -> list[User]:
    users: list[User] = []
    for env_key, default_email, full_name, role in ACCOUNT_SPECS:
        email = os.environ.get(env_key, default_email).strip() or default_email
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=role,
                settings={
                    "notifications": {"disruption": True, "plan_ready": True, "execution": True},
                    "currency": "INR",
                    "language": "en",
                    "timezone": "UTC",
                    "travel_preferences": {"avoid_overnight_connections": False},
                    "privacy": {"share_itinerary_with_manager": True},
                },
            )
            db.add(user)
            db.flush()
        users.append(user)
    return users


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap ReTryp user accounts")
    parser.parse_args(argv)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        password, generated = _password()
        users = create_accounts(db, password)
        db.commit()
        print("ReTryp accounts ready. No trips are seeded.")
        print(f"  sign-in  : {', '.join(u.email for u in users)}")
        if generated:
            print(f"  password : {password}")
            print("  Set BOOTSTRAP_PASSWORD to choose your own.")
        else:
            print("  password : (from BOOTSTRAP_PASSWORD)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
