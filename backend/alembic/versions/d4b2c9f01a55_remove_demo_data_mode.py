"""remove the demonstration data mode

ReTryp no longer ships a demonstration catalogue or a switchable data mode, so
``trips.is_demo`` and the ``platform_settings`` table are no longer used. Trips
are always built from real sources.

Revision ID: d4b2c9f01a55
Revises: c3f1a7d24b90
Create Date: 2026-09-28 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d4b2c9f01a55"
down_revision: str | None = "c3f1a7d24b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode (enabled for SQLite in alembic/env.py) rewrites the table.
    with op.batch_alter_table("trips") as batch:
        batch.drop_column("is_demo")
    op.drop_table("platform_settings")


def downgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
    )
    with op.batch_alter_table("trips") as batch:
        batch.add_column(
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false())
        )
