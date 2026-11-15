"""create response_cache table

Precomputed JSON responses for slow global endpoints (story/today, generation/national-24h),
shared across Lambda instances. See app/models/response_cache.py.

Revision ID: u8j9k0l1m2n3
Revises: t7i8j9k0l1m2
Create Date: 2026-11-15
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "u8j9k0l1m2n3"
down_revision: Union[str, None] = "t7i8j9k0l1m2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "response_cache",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Enable RLS (Supabase requirement)
    op.execute("ALTER TABLE response_cache ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("response_cache")
