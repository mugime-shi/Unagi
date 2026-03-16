"""create_balancing_prices

Revision ID: d1e2f3a4b5c6
Revises: c9d1e2f3a4b5
Create Date: 2026-03-16

Stores ENTSO-E A85 imbalance (balancing) prices for SE3.
Separate table from spot_prices: different market, different document type,
different namespace, and the category dimension (Long/Short) would
require a schema change to the existing spot_prices table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "balancing_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_eur_mwh", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_sek_kwh", sa.Numeric(10, 4), nullable=True),
        sa.Column("category", sa.String(4), nullable=False),   # A04=Long, A05=Short
        sa.Column("resolution", sa.String(10), server_default="PT15M"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "area", "timestamp_utc", "category", "resolution",
            name="uq_balancing_price",
        ),
    )
    op.create_index(
        "idx_balancing_prices_area_time",
        "balancing_prices",
        ["area", sa.text("timestamp_utc DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_balancing_prices_area_time", table_name="balancing_prices")
    op.drop_table("balancing_prices")
