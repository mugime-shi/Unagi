"""create elhandlare table with SE3 seed data

Revision ID: o2d3e4f5g6h7
Revises: n1c2d3e4f5g6
Create Date: 2026-04-19
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "o2d3e4f5g6h7"
down_revision: Union[str, None] = "n1c2d3e4f5g6"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "elhandlare",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("area", sa.String(4), nullable=False),
        sa.Column("contract_type", sa.String(20), nullable=False),
        sa.Column("paslag_ore_kwh", sa.Numeric(6, 2), nullable=False),
        sa.Column("monthly_fee_sek", sa.Numeric(8, 2), nullable=False),
        sa.Column("elcert_included", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("binding_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_estimate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", "area", "contract_type", "valid_from", name="uq_elhandlare_tariff"),
        sa.Index("idx_elhandlare_area", "area"),
    )

    # Enable RLS (Supabase requirement)
    op.execute("ALTER TABLE elhandlare ENABLE ROW LEVEL SECURITY")

    # ── SE3 seed data (2026, markup and monthly fee exkl VAT unless noted) ──
    # All figures sourced from work/elhandlare-pricing-data-v2.md (2026-04-08 survey).
    # paslag_ore_kwh: advertised markup per company — NOT a unified "real cost" metric
    # (definitions differ across companies; that gap is the point of the transparency section).
    # contract_type values ('rorligt', 'kvartspris', 'fast') stay as DB enums;
    # frontend maps them to 'variable' / 'spot' / 'fixed' for display.
    op.execute(
        """
        INSERT INTO elhandlare
            (slug, name, area, contract_type,
             paslag_ore_kwh, monthly_fee_sek,
             elcert_included, binding_months, is_estimate,
             notes, valid_from, valid_to, source_url)
        VALUES
            ('tibber', 'Tibber', 'SE3', 'kvartspris',
             6.00, 49.00,
             false, 0, false,
             'Advertised profit markup is 0 öre; the 6 öre figure is the fixed markup per official terms. Purchase costs (green certificates, origin guarantees, Nord Pool/SvK/eSett fees) are NOT included — totalling ~8.6 öre/kWh incl VAT per 2025 Elpriskollen data.',
             '2026-01-01', '2026-12-31',
             'https://tibber.com/se/villkor/elavtalsvillkor'),

            ('greenely', 'Greenely', 'SE3', 'kvartspris',
             8.00, 69.00,
             false, 0, true,
             'Estimated figure. Advertised profit markup is 0 öre; full purchase costs not officially disclosed. Comparison sites estimate 8-9 öre incl VAT, comparable to Tibber. Monthly fee drops to 49 kr with a 12-month binding choice.',
             '2026-01-01', '2026-12-31',
             'https://greenely.se'),

            ('fortum', 'Fortum', 'SE3', 'rorligt',
             3.90, 69.00,
             true, 0, false,
             'Advertised as 2 öre markup + 1.9 öre green certificate = 3.9 öre combined. Balancing cost, origin guarantees and other fees are NOT included.',
             '2026-01-01', '2026-12-31',
             'https://www.fortum.se'),

            ('skelleftea-kraft', 'Skellefteå Kraft', 'SE3', 'rorligt',
             6.00, 49.00,
             false, 0, false,
             'Includes origin labeling (100% renewable). Other purchase costs excluded. Schysst Elhandel certified.',
             '2026-01-01', '2026-12-31',
             'https://www.skekraft.se'),

            ('vattenfall', 'Vattenfall', 'SE3', 'rorligt',
             7.00, 45.00,
             true, 0, false,
             'Includes green certificate (integrated since 2021). Profile cost (customer consumption pattern weighting) is NOT included.',
             '2026-01-01', '2026-12-31',
             'https://www.vattenfall.se')
        """
    )


def downgrade() -> None:
    op.drop_table("elhandlare")
