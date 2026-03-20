"""add predicted_low/high columns to forecast_accuracy

Revision ID: g4b5c6d7e8f9
Revises: b2c3d4e5f6a7
Create Date: 2026-03-20
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "g4b5c6d7e8f9"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "forecast_accuracy",
        sa.Column("predicted_low_sek_kwh", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "forecast_accuracy",
        sa.Column("predicted_high_sek_kwh", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forecast_accuracy", "predicted_high_sek_kwh")
    op.drop_column("forecast_accuracy", "predicted_low_sek_kwh")
