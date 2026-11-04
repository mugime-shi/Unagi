"""create usage_events table

ID-less first-party usage tracking (visits with day offsets, tab/area views).
See app/models/usage_event.py for why Vercel Analytics is not enough.

Revision ID: s6h7i8j9k0l1
Revises: r5g6h7i8j9k0
Create Date: 2026-11-01
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "s6h7i8j9k0l1"
down_revision: Union[str, None] = "r5g6h7i8j9k0"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("days_since_first", sa.Integer(), nullable=True),
        sa.Column("days_since_last", sa.Integer(), nullable=True),
        sa.Index("idx_usage_events_event_time", "event", "occurred_at"),
    )

    # Enable RLS (Supabase requirement)
    op.execute("ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("usage_events")
