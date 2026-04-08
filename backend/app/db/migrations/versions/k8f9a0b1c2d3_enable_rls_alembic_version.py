"""enable row level security on alembic_version

Supabase Security Advisor flagged public.alembic_version as still missing
RLS. The earlier fix (commit f1f1fa1) tried to patch this by editing the
already-applied h5c6d7e8f9a0 migration in place, but Alembic does not
re-run migrations that are marked as applied, so production was never
updated. Ship the fix as a fresh migration instead.

Revision ID: k8f9a0b1c2d3
Revises: j7e8f9a0b1c2
Create Date: 2026-04-08
"""

from typing import Union

from alembic import op

revision: str = "k8f9a0b1c2d3"
down_revision: Union[str, None] = "j7e8f9a0b1c2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY")
