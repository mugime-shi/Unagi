"""create load_forecast, gas_price, de_spot_price tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- load_forecast ---
    op.create_table(
        "load_forecast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(4), server_default="SE3", nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_mw", sa.Numeric(10, 1), nullable=False),
        sa.Column("resolution", sa.String(10), server_default="PT60M"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("area", "timestamp_utc", "resolution", name="uq_load_forecast"),
    )
    op.create_index("idx_load_forecast_area_time", "load_forecast", ["area", "timestamp_utc"])

    # --- gas_price ---
    op.create_table(
        "gas_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("price_eur_mwh", sa.Numeric(10, 2), nullable=False),
        sa.Column("source", sa.String(30), server_default="bundesnetzagentur"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "source", name="uq_gas_price"),
    )
    op.create_index("idx_gas_price_date", "gas_price", ["trade_date"])

    # --- de_spot_price ---
    op.create_table(
        "de_spot_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_eur_mwh", sa.Numeric(10, 2), nullable=False),
        sa.Column("resolution", sa.String(10), server_default="PT60M"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("timestamp_utc", "resolution", name="uq_de_spot_price"),
    )
    op.create_index("idx_de_spot_price_time", "de_spot_price", ["timestamp_utc"])


def downgrade() -> None:
    op.drop_index("idx_de_spot_price_time", table_name="de_spot_price")
    op.drop_table("de_spot_price")

    op.drop_index("idx_gas_price_date", table_name="gas_price")
    op.drop_table("gas_price")

    op.drop_index("idx_load_forecast_area_time", table_name="load_forecast")
    op.drop_table("load_forecast")
