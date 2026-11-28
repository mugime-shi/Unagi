"""create_weather_data_table

Revision ID: b8f2c9d1a3e5
Revises: 36b7e8f0261d
Create Date: 2026-03-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8f2c9d1a3e5"
down_revision: Union[str, Sequence[str], None] = "36b7e8f0261d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_data",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False, server_default="71420"),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Numeric(5, 1), nullable=True),
        sa.Column("global_radiation_wm2", sa.Numeric(8, 2), nullable=True),
        sa.Column("sunshine_hours", sa.Numeric(4, 1), nullable=True),
        sa.Column("source", sa.String(20), server_default="smhi"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("station_id", "timestamp_utc", "source", name="uq_weather_data"),
    )
    op.create_index(
        "idx_weather_data_station_time",
        "weather_data",
        ["station_id", sa.text("timestamp_utc DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_weather_data_station_time", table_name="weather_data")
    op.drop_table("weather_data")
