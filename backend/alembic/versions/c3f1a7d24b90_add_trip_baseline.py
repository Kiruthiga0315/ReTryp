"""add trip baseline

Stores the itinerary as first loaded so a recovery cycle can be undone and the
demonstration replayed from the original booking.

Revision ID: c3f1a7d24b90
Revises: 8f61b8b601d9
Create Date: 2026-09-28 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c3f1a7d24b90"
down_revision: str | None = "8f61b8b601d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("baseline", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("trips", "baseline")
