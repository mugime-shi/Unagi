"""enable row level security on all public tables

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-03-26
"""

from typing import Union

from alembic import op

revision: str = "h5c6d7e8f9a0"
down_revision: Union[str, None] = "g4b5c6d7e8f9"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

TABLES = [
    "spot_prices",
    "weather_data",
    "weather_forecast",
    "push_subscriptions",
    "balancing_prices",
    "generation_mix",
    "load_forecast",
    "gas_price",
    "de_spot_price",
    "forecast_accuracy",
    "alembic_version",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
