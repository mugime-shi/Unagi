"""add area column to weather_data / weather_forecast

Weather was a single Göteborg point shared by all four bidding areas.
Local (per-area) wind is the dominant driver of northern price shape
(work/SE12_LOCAL_WEATHER_2026-07-16.md), so both tables gain an `area`
column. Existing rows are Göteborg data → tagged 'SE3'. Feature loading
falls back to SE3 rows for areas without local data, so behaviour is
unchanged until an area is backfilled.

Revision ID: r5g6h7i8j9k0
Revises: q4f5g6h7i8j9
Create Date: 2026-07-16
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "r5g6h7i8j9k0"
down_revision: Union[str, None] = "q4f5g6h7i8j9"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "weather_data",
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
    )
    op.drop_constraint("uq_weather_data", "weather_data", type_="unique")
    op.create_unique_constraint(
        "uq_weather_data",
        "weather_data",
        ["station_id", "timestamp_utc", "source", "area"],
    )
    op.create_index("idx_weather_data_area_time", "weather_data", ["area", "timestamp_utc"])

    op.add_column(
        "weather_forecast",
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
    )
    op.drop_constraint("uq_weather_forecast", "weather_forecast", type_="unique")
    op.create_unique_constraint(
        "uq_weather_forecast",
        "weather_forecast",
        ["issued_date", "target_utc", "source", "area"],
    )
    op.create_index(
        "idx_weather_forecast_area_issued",
        "weather_forecast",
        ["area", "issued_date", "target_utc"],
    )


def downgrade() -> None:
    op.drop_index("idx_weather_forecast_area_issued", table_name="weather_forecast")
    op.drop_constraint("uq_weather_forecast", "weather_forecast", type_="unique")
    op.execute("DELETE FROM weather_forecast WHERE area != 'SE3'")
    op.drop_column("weather_forecast", "area")
    op.create_unique_constraint(
        "uq_weather_forecast",
        "weather_forecast",
        ["issued_date", "target_utc", "source"],
    )

    op.drop_index("idx_weather_data_area_time", table_name="weather_data")
    op.drop_constraint("uq_weather_data", "weather_data", type_="unique")
    op.execute("DELETE FROM weather_data WHERE area != 'SE3'")
    op.drop_column("weather_data", "area")
    op.create_unique_constraint(
        "uq_weather_data",
        "weather_data",
        ["station_id", "timestamp_utc", "source"],
    )
