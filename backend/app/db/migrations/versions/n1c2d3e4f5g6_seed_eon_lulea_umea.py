"""seed grid_operators with E.ON (3 areas), Luleå Energi, Umeå Energi

Revision ID: n1c2d3e4f5g6
Revises: m0b1c2d3e4f5
Create Date: 2026-04-14
"""

from typing import Union

from alembic import op

revision: str = "n1c2d3e4f5g6"
down_revision: Union[str, None] = "m0b1c2d3e4f5"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── E.ON Energidistribution (2026, exkl moms) ──
    # Source: https://www.eon.se/el/elnat/elnaetsabonnemang-priser
    # Prices on site are inkl moms; divided by 1.25 below.
    # "Electricity transmission fee" on site EXCLUDES energiskatt.
    #
    # Apartment = "16A, Apartment" subscription
    # House = "16A, over 8,000 kWh/year" subscription
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            -- E.ON Norr (SE2: Kramfors, Hammarstrand, Medelpad, Ådalen)
            ('eon-norr', 'E.ON Energidistribution (Norr)', 'Sundsvall', 'SE2', 'apartment',
             1056.00, 87.36, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser'),
            ('eon-norr', 'E.ON Energidistribution (Norr)', 'Sundsvall', 'SE2', 'house',
             6696.00, 21.04, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser'),

            -- E.ON Syd & Mellersta (SE4: Skåne, Blekinge, Halland, Småland, Ö. Götaland, Örebro)
            ('eon-syd', 'E.ON Energidistribution (Syd)', 'Malmö', 'SE4', 'apartment',
             1056.00, 87.36, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser'),
            ('eon-syd', 'E.ON Energidistribution (Syd)', 'Malmö', 'SE4', 'house',
             5976.00, 25.84, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser'),

            -- E.ON Stockholm (SE3: Danderyd, Enköping, Åkersberga, southern Uppland)
            ('eon-stockholm', 'E.ON Energidistribution (Stockholm)', 'Stockholm', 'SE3', 'apartment',
             1296.00, 64.68, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser'),
            ('eon-stockholm', 'E.ON Energidistribution (Stockholm)', 'Stockholm', 'SE3', 'house',
             4788.00, 21.04, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.eon.se/el/elnat/elnaetsabonnemang-priser')
        """
    )

    # ── Luleå Energi Elnät (SE1, 2026) ──
    # Source: elnät-prislista_2026.pdf from luleaenergi.se
    # Prices on PDF are inkl moms; divided by 1.25 below.
    # Apartment (NL16): pure fixed model, 0 öre/kWh transfer
    # House (NR16): 16A with max 24,850 kWh, has transfer fee
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            ('lulea-energi', 'Luleå Energi Elnät', 'Luleå', 'SE1', 'apartment',
             1416.00, 0.00, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.luleaenergi.se/produktion-och-infrastruktur/elnat/natpriser-och-avtalsvillkor/'),
            ('lulea-energi', 'Luleå Energi Elnät', 'Luleå', 'SE1', 'house',
             2808.00, 14.48, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.luleaenergi.se/produktion-och-infrastruktur/elnat/natpriser-och-avtalsvillkor/')
        """
    )

    # ── Umeå Energi Elnät (SE1, 2026) ──
    # Source: https://www.umeaenergi.se/elnat/priser/priser-elnat (screenshot 2026-04-14)
    # Fixed fees from screenshot: exkl moms column confirmed.
    # Transfer fee: 16.8 öre/kWh exkl moms (from Ei 2025 data, unchanged in 2026).
    op.execute(
        """
        INSERT INTO grid_operators
            (slug, name, city, area, dwelling_type,
             fast_fee_sek_year, transfer_fee_ore, effect_fee_sek_kw,
             valid_from, valid_to, source_url)
        VALUES
            ('umea-energi', 'Umeå Energi Elnät', 'Umeå', 'SE1', 'apartment',
             871.00, 16.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.umeaenergi.se/elnat/priser/priser-elnat'),
            ('umea-energi', 'Umeå Energi Elnät', 'Umeå', 'SE1', 'house',
             2189.00, 16.80, NULL,
             '2026-01-01', '2026-12-31',
             'https://www.umeaenergi.se/elnat/priser/priser-elnat')
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM grid_operators WHERE slug IN "
        "('eon-norr', 'eon-syd', 'eon-stockholm', 'lulea-energi', 'umea-energi')"
    )
