"""create_weather_forecast

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-03-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_forecast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        sa.Column("target_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Numeric(5, 1), nullable=True),
        sa.Column("wind_speed_10m", sa.Numeric(6, 1), nullable=True),
        sa.Column("wind_speed_100m", sa.Numeric(6, 1), nullable=True),
        sa.Column("global_radiation_wm2", sa.Numeric(8, 2), nullable=True),
        sa.Column("source", sa.String(20), server_default="open-meteo"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issued_date", "target_utc", "source", name="uq_weather_forecast"
        ),
    )
    op.create_index(
        "idx_weather_forecast_issued",
        "weather_forecast",
        ["issued_date", "target_utc"],
    )


def downgrade() -> None:
    op.drop_index("idx_weather_forecast_issued", table_name="weather_forecast")
    op.drop_table("weather_forecast")
