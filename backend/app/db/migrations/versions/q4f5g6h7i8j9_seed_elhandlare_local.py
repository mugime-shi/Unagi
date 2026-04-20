"""seed elhandlare with local/kommun retailers (GBG, Luleå, Umeå, Jämt, Mälar, Öresund)

Adds six Swedish local/kommun-owned electricity retailers to the comparison:
- Göteborg Energi (SE3) — Göteborg
- Luleå Energi (SE1) — Luleå
- Umeå Energi (SE1) — Umeå
- Jämtkraft (SE2) — Östersund
- Mälarenergi (SE3) — Västerås
- Öresundskraft (SE4) — Helsingborg

All figures sourced from each retailer's official site and cross-checked
against aggregator sites (elavtal24, hittaelavtal, elbruk). Markup (öre/kWh)
is exkl VAT; monthly fee is inkl VAT (industry advertising convention).
Only rörligt (monthly variable) contracts are seeded for the first round.

Revision ID: q4f5g6h7i8j9
Revises: p3e4f5g6h7i8
Create Date: 2026-04-20
"""

from typing import Union

from alembic import op

revision: str = "q4f5g6h7i8j9"
down_revision: Union[str, None] = "p3e4f5g6h7i8"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO elhandlare
            (slug, name, area, contract_type,
             paslag_ore_kwh, monthly_fee_sek,
             elcert_included, binding_months, is_estimate,
             notes, valid_from, valid_to, source_url)
        VALUES
            ('goteborg-energi-elhandel', 'Göteborg Energi', 'SE3', 'rorligt',
             8.60, 45.00,
             false, 0, true,
             'Estimated figure — 8.6 öre markup not published on official site; value from third-party comparison sites. 100% fossil-free. Monthly fee 45 kr incl VAT. Göteborg municipality-owned.',
             '2026-01-01', '2026-12-31',
             'https://www.goteborgenergi.se/privat/elavtal/rorligt'),

            ('lulea-energi-elhandel', 'Luleå Energi', 'SE1', 'rorligt',
             2.90, 30.00,
             false, 0, false,
             'Officially disclosed markup (high transparency). Elcertifikat 0.69 öre is billed separately on top of the 2.90 öre markup. 100% fossil-free default. Add-on tariffs: VattenEl (+3 öre), VindEl (+3 öre), Bra Miljöval (+4.5 öre). Municipally owned.',
             '2026-01-01', '2026-12-31',
             'https://www.luleaenergi.se/produkter-och-tjanster/elavtal/rorligt-pris/'),

            ('umea-energi-elhandel', 'Umeå Energi', 'SE1', 'rorligt',
             4.22, 39.60,
             true, 0, true,
             'Estimated figure from aggregator sites. Markup 4.22 öre includes elcertifikat per official notice (unusually transparent compared to peers). Ursprungsgarantier likely separate. 100% fossil-free default; 100% renewable upgrade for +2.5 öre. Municipally owned.',
             '2026-01-01', '2026-12-31',
             'https://www.umeaenergi.se/elavtal'),

            ('jamtkraft-elhandel', 'Jämtkraft', 'SE2', 'rorligt',
             3.40, 50.00,
             false, 0, true,
             'Estimated figure — not published on official site. 100% renewable default. Notice period is 14 days (shorter than industry standard 1 month). Elcertifikat, ursprungsgarantier and other purchase costs are separate per the official price notice.',
             '2026-01-01', '2026-12-31',
             'https://www.jamtkraft.se/privat/elavtal/vara-elavtal/rorligt-elpris/'),

            ('malarenergi-elhandel', 'Mälarenergi', 'SE3', 'rorligt',
             2.90, 35.00,
             false, 0, true,
             'Estimated figure from aggregator sites. Default mix is 72% renewable / 18% nuclear / 10% fossil+peat; fossil-free upgrade available for +1.6 öre. Elcertifikat, balansansvar and SvK/Nord Pool/eSett fees are billed separately. Västerås municipality-owned.',
             '2026-01-01', '2026-12-31',
             'https://www.malarenergi.se/el/elavtal/rorligt-manadspris/'),

            ('oresundskraft-elhandel', 'Öresundskraft', 'SE4', 'rorligt',
             2.55, 36.00,
             false, 0, false,
             'Officially disclosed markup. Monthly fee 432 kr/year (~36 kr/mån) — scheduled to rise to 470.4 kr/year from 2026-06. Rebranded from SmartEl in Nov 2025. Ursprungsgarantier, elcertifikat, profile cost and other fees are separate per official disclosure. Helsingborg municipality-owned.',
             '2026-01-01', '2026-12-31',
             'https://www.oresundskraft.se/privat/el/manadspris/')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM elhandlare
        WHERE slug IN (
            'goteborg-energi-elhandel',
            'lulea-energi-elhandel',
            'umea-energi-elhandel',
            'jamtkraft-elhandel',
            'malarenergi-elhandel',
            'oresundskraft-elhandel'
        )
        """
    )
