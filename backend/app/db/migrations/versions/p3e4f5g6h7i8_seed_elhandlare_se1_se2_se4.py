"""seed elhandlare SE1/SE2/SE4 for the five nationwide retailers

All five retailers (Tibber, Fortum, Skellefteå Kraft, Vattenfall, Greenely)
advertise the same markup and monthly fee nationwide; what changes between
SE1–SE4 is only the spot price, which comes from the spot_prices table.
Copying the SE3 rows into SE1/SE2/SE4 lets the ranking render for every
bidding area without a separate survey.

Revision ID: p3e4f5g6h7i8
Revises: o2d3e4f5g6h7
Create Date: 2026-04-20
"""

from typing import Union

from alembic import op

revision: str = "p3e4f5g6h7i8"
down_revision: Union[str, None] = "o2d3e4f5g6h7"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


_INSERT_SQL = """
INSERT INTO elhandlare
    (slug, name, area, contract_type,
     paslag_ore_kwh, monthly_fee_sek,
     elcert_included, binding_months, is_estimate,
     notes, valid_from, valid_to, source_url)
VALUES
    ('tibber', 'Tibber', :area, 'kvartspris',
     6.00, 49.00,
     false, 0, false,
     'Advertised profit markup is 0 öre; the 6 öre figure is the fixed markup per official terms. Purchase costs (green certificates, origin guarantees, Nord Pool/SvK/eSett fees) are NOT included — totalling ~8.6 öre/kWh incl VAT per 2025 Elpriskollen data.',
     '2026-01-01', '2026-12-31',
     'https://tibber.com/se/villkor/elavtalsvillkor'),

    ('greenely', 'Greenely', :area, 'kvartspris',
     8.00, 69.00,
     false, 0, true,
     'Estimated figure. Advertised profit markup is 0 öre; full purchase costs not officially disclosed. Comparison sites estimate 8-9 öre incl VAT, comparable to Tibber. Monthly fee drops to 49 kr with a 12-month binding choice.',
     '2026-01-01', '2026-12-31',
     'https://greenely.se'),

    ('fortum', 'Fortum', :area, 'rorligt',
     3.90, 69.00,
     true, 0, false,
     'Advertised as 2 öre markup + 1.9 öre green certificate = 3.9 öre combined. Balancing cost, origin guarantees and other fees are NOT included.',
     '2026-01-01', '2026-12-31',
     'https://www.fortum.se'),

    ('skelleftea-kraft', 'Skellefteå Kraft', :area, 'rorligt',
     6.00, 49.00,
     false, 0, false,
     'Includes origin labeling (100% renewable). Other purchase costs excluded. Schysst Elhandel certified.',
     '2026-01-01', '2026-12-31',
     'https://www.skekraft.se'),

    ('vattenfall', 'Vattenfall', :area, 'rorligt',
     7.00, 45.00,
     true, 0, false,
     'Includes green certificate (integrated since 2021). Profile cost (customer consumption pattern weighting) is NOT included.',
     '2026-01-01', '2026-12-31',
     'https://www.vattenfall.se')
"""


def upgrade() -> None:
    for area in ("SE1", "SE2", "SE4"):
        op.execute(_INSERT_SQL.replace(":area", f"'{area}'"))


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM elhandlare
        WHERE area IN ('SE1', 'SE2', 'SE4')
          AND slug IN (
            'tibber', 'greenely', 'fortum', 'skelleftea-kraft', 'vattenfall'
          )
        """
    )
