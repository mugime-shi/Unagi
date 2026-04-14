"""seed grid_operators with SE1, SE2, SE4 data

Revision ID: m0b1c2d3e4f5
Revises: l9a0b1c2d3e4
Create Date: 2026-04-14
"""

from typing import Union

from alembic import op

revision: str = "m0b1c2d3e4f5"
down_revision: Union[str, None] = "l9a0b1c2d3e4"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── SE1 seed data (2026, exkl moms) ──
    # Skellefteå Kraft: https://www.skekraft.se/privat/elnat/elnatspriser/
    # Prices on site are inkl moms; divided by 1.25 below.
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            ('skelleftea-kraft', 'Skellefteå Kraft Elnät', 'Skellefteå', 'SE1', 'apartment',
             1780.00, 8.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.skekraft.se/privat/elnat/elnatspriser/'),
            ('skelleftea-kraft', 'Skellefteå Kraft Elnät', 'Skellefteå', 'SE1', 'house',
             4528.00, 8.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.skekraft.se/privat/elnat/elnatspriser/')
        """
    )

    # ── SE2 seed data (2026, exkl moms) ──
    # Jämtkraft: https://www.jamtkraft.se/privat/elnat/elnatsavgifter/
    # Gävle Energi: https://www.gavleenergi.se/elnat/elnatspriser/
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            ('jamtkraft', 'Jämtkraft Elnät', 'Östersund', 'SE2', 'apartment',
             1992.00, 6.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.jamtkraft.se/privat/elnat/elnatsavgifter/'),
            ('jamtkraft', 'Jämtkraft Elnät', 'Östersund', 'SE2', 'house',
             4560.00, 6.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.jamtkraft.se/privat/elnat/elnatsavgifter/'),

            ('gavle-energi', 'Gävle Energi Elnät', 'Gävle', 'SE2', 'apartment',
             1596.00, 12.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.gavleenergi.se/elnat/elnatspriser/'),
            ('gavle-energi', 'Gävle Energi Elnät', 'Gävle', 'SE2', 'house',
             3472.00, 12.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.gavleenergi.se/elnat/elnatspriser/')
        """
    )

    # ── SE4 seed data (2026, exkl moms) ──
    # Öresundskraft: https://www.oresundskraft.se/privat/elnat/elnatsavgifter/
    #   Transfer fee is variable: "17 + 5.57% × MMU" öre inkl moms.
    #   Estimated at typical SE4 spot ~50 öre → 19.8 inkl → 15.8 exkl.
    # Kraftringen: https://www.kraftringen.se/privat/elnat/elnatsavgifter/komplett-elnatsprislista/
    #   Transfer fee is variable: "20 + 0.05 × spot" öre inkl moms.
    #   Estimated at typical SE4 spot ~50 öre → 22.5 inkl → 18.0 exkl.
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            ('oresundskraft', 'Öresundskraft', 'Helsingborg', 'SE4', 'apartment',
             1932.00, 15.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.oresundskraft.se/privat/elnat/elnatsavgifter/'),
            ('oresundskraft', 'Öresundskraft', 'Helsingborg', 'SE4', 'house',
             4128.00, 15.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.oresundskraft.se/privat/elnat/elnatsavgifter/'),

            ('kraftringen', 'Kraftringen Elnät', 'Lund', 'SE4', 'apartment',
             3312.00, 18.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.kraftringen.se/privat/elnat/elnatsavgifter/komplett-elnatsprislista/'),
            ('kraftringen', 'Kraftringen Elnät', 'Lund', 'SE4', 'house',
             6576.00, 18.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.kraftringen.se/privat/elnat/elnatsavgifter/komplett-elnatsprislista/')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM grid_operators WHERE area IN ('SE1', 'SE2', 'SE4')")
