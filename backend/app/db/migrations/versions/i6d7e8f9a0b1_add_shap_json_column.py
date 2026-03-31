"""add shap_json column to forecast_accuracy

Revision ID: i6d7e8f9a0b1
Revises: h5c6d7e8f9a0
Create Date: 2026-03-31
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "i6d7e8f9a0b1"
down_revision: Union[str, None] = "h5c6d7e8f9a0"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "forecast_accuracy",
        sa.Column("shap_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forecast_accuracy", "shap_json")
