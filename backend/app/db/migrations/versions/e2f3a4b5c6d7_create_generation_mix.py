"""create_generation_mix

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-16

Stores ENTSO-E A75 actual generation per production type (15-min resolution).
One row per (area, timestamp_utc, psr_type) — e.g. SE3/B12/Hydro at 10:00 UTC.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_mix",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("psr_type", sa.String(4), nullable=False),   # "B12", "B14", etc.
        sa.Column("value_mw", sa.Numeric(10, 2), nullable=False),
        sa.Column("resolution", sa.String(10), server_default="PT15M"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "area", "timestamp_utc", "psr_type",
            name="uq_generation_mix",
        ),
    )
    op.create_index(
        "idx_generation_mix_area_time",
        "generation_mix",
        ["area", sa.text("timestamp_utc DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_generation_mix_area_time", table_name="generation_mix")
    op.drop_table("generation_mix")
