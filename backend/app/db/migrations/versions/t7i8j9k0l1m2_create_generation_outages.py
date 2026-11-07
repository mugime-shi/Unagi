"""create generation_outages table

ENTSO-E A77 (generation units) / A80 (production units) unavailability
documents, mainly for nuclear reactor status. See app/models/generation_outage.py.

Revision ID: t7i8j9k0l1m2
Revises: s6h7i8j9k0l1
Create Date: 2026-11-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "t7i8j9k0l1m2"
down_revision: Union[str, None] = "s6h7i8j9k0l1"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "generation_outages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mrid", sa.String(64), nullable=False, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("document_type", sa.String(3), nullable=False),
        sa.Column("business_type", sa.String(3), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("area", sa.String(4), nullable=False),
        sa.Column("resource_eic", sa.String(32), nullable=True),
        sa.Column("resource_name", sa.String(128), nullable=True),
        sa.Column("psr_type", sa.String(4), nullable=True),
        sa.Column("nominal_mw", sa.Numeric(8, 1), nullable=True),
        sa.Column("start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_periods", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reason_code", sa.String(8), nullable=True),
        sa.Column("reason_text", sa.String(512), nullable=True),
        sa.Column("created_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_utc", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Index("idx_generation_outages_area_window", "area", "start_utc", "end_utc"),
    )

    # Enable RLS (Supabase requirement)
    op.execute("ALTER TABLE generation_outages ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("generation_outages")
