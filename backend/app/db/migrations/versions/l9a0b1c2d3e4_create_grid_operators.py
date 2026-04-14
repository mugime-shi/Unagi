"""create grid_operators table with SE3 seed data

Revision ID: l9a0b1c2d3e4
Revises: k8f9a0b1c2d3
Create Date: 2026-04-14
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "l9a0b1c2d3e4"
down_revision: Union[str, None] = "k8f9a0b1c2d3"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "grid_operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("city", sa.String(50), nullable=False),
        sa.Column("area", sa.String(4), nullable=False),
        sa.Column("dwelling_type", sa.String(20), nullable=False),
        sa.Column("fast_fee_sek_year", sa.Numeric(10, 2), nullable=False),
        sa.Column("transfer_fee_ore", sa.Numeric(10, 2), nullable=False),
        sa.Column("effect_fee_sek_kw", sa.Numeric(10, 2), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", "dwelling_type", "valid_from", name="uq_grid_operator_tariff"),
        sa.Index("idx_grid_operators_area", "area"),
    )

    # Enable RLS (Supabase requirement)
    op.execute("ALTER TABLE grid_operators ENABLE ROW LEVEL SECURITY")

    # ── SE3 seed data (2026, all exkl moms) ──
    # Sources:
    #   Göteborg Energi: https://api.goteborgenergi.cloud/gridtariff/v0/tariffs
    #   Ellevio: https://www.ellevio.se/abonnemang/elnatspriser/
    #   Vattenfall: https://www.vattenfalleldistribution.se/abonnemang-och-avgifter/
    #   Mälarenergi: https://www.malarenergi.se/el/elnat/priser-elnat/
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            -- Göteborg Energi Nät (GNM63, one tariff for all)
            ('goteborg-energi', 'Göteborg Energi Nät', 'Göteborg', 'SE3', 'apartment',
             1968.00, 18.40, NULL,
             '2026-01-01', '2026-12-31',
             'https://api.goteborgenergi.cloud/gridtariff/v0/tariffs'),
            ('goteborg-energi', 'Göteborg Energi Nät', 'Göteborg', 'SE3', 'house',
             1968.00, 18.40, 39.20,
             '2026-01-01', '2026-12-31',
             'https://api.goteborgenergi.cloud/gridtariff/v0/tariffs'),

            -- Ellevio (Stockholm)
            ('ellevio', 'Ellevio', 'Stockholm', 'SE3', 'apartment',
             1152.00, 20.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.ellevio.se/abonnemang/elnatspriser/lagenhet/'),
            ('ellevio', 'Ellevio', 'Stockholm', 'SE3', 'house',
             3792.00, 5.60, 65.00,
             '2026-01-01', '2026-12-31',
             'https://www.ellevio.se/abonnemang/elnatspriser/hus/'),

            -- Vattenfall Eldistribution
            ('vattenfall', 'Vattenfall Eldistribution', 'Bred SE3', 'SE3', 'apartment',
             1960.00, 35.60, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.vattenfalleldistribution.se/abonnemang-och-avgifter/'),
            ('vattenfall', 'Vattenfall Eldistribution', 'Bred SE3', 'SE3', 'house',
             4620.00, 35.60, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.vattenfalleldistribution.se/abonnemang-och-avgifter/'),

            -- Mälarenergi Elnät (Västerås)
            ('malarenergi', 'Mälarenergi Elnät', 'Västerås', 'SE3', 'apartment',
             1380.00, 17.20, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.malarenergi.se/el/elnat/priser-elnat/'),
            ('malarenergi', 'Mälarenergi Elnät', 'Västerås', 'SE3', 'house',
             3372.00, 17.20, 47.40,
             '2026-01-01', '2026-12-31',
             'https://www.malarenergi.se/el/elnat/priser-elnat/')
        """
    )


def downgrade() -> None:
    op.drop_table("grid_operators")
