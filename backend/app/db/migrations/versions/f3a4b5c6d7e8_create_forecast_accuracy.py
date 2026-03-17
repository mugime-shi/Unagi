"""create forecast_accuracy table

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-03-17
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "forecast_accuracy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("area", sa.String(4), nullable=False, server_default="SE3"),
        sa.Column("model_name", sa.String(30), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("predicted_sek_kwh", sa.Numeric(10, 4), nullable=False),
        sa.Column("actual_sek_kwh", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_date", "area", "model_name", "hour",
            name="uq_forecast_accuracy",
        ),
    )
    op.create_index(
        "idx_forecast_accuracy_date_area",
        "forecast_accuracy",
        ["target_date", "area"],
    )


def downgrade() -> None:
    op.drop_index("idx_forecast_accuracy_date_area", table_name="forecast_accuracy")
    op.drop_table("forecast_accuracy")
