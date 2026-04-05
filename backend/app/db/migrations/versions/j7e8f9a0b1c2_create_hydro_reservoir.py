"""create hydro_reservoir table

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
Create Date: 2026-04-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "j7e8f9a0b1c2"
down_revision: Union[str, None] = "i6d7e8f9a0b1"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "hydro_reservoir",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("stored_energy_mwh", sa.Numeric(12, 0), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_hydro_reservoir", "hydro_reservoir", ["area", "week_start"])
    op.create_index("idx_hydro_reservoir_area_week", "hydro_reservoir", ["area", "week_start"])
    # Enable RLS (consistent with existing tables)
    op.execute("ALTER TABLE hydro_reservoir ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("hydro_reservoir")
