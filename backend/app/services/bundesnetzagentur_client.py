"""
Bundesnetzagentur / Trading Hub Europe (THE) gas price client.

Fetches daily THE reference prices (Referenzpreise) — the settlement
price for the German virtual trading point, used as a proxy for
European gas costs that drive electricity price spikes.

Data source: Trading Hub Europe "Referenzpreise" public download.
THE publishes CSV files with daily settlement prices.
"""

from dataclasses import dataclass
from datetime import date, datetime

import httpx

# THE reference prices are published at their data portal.
# The CSV download contains: Date, Price (EUR/MWh)
THE_BASE_URL = "https://www.tradinghub.eu/Portals/0/Referenzpreise/Referenzpreise_{year}.csv"


class GasPriceError(Exception):
    pass


@dataclass
class GasPricePoint:
    trade_date: date
    price_eur_mwh: float
    source: str = "the_reference"


def _parse_the_csv(csv_text: str) -> list[GasPricePoint]:
    """
    Parse THE reference price CSV into GasPricePoint list.

    Expected format (semicolon-delimited, German locale):
        Gashandelstag;Referenzpreis (EUR/MWh)
        02.01.2025;34,52
        03.01.2025;35,10
    """
    points: list[GasPricePoint] = []
    lines = csv_text.strip().split("\n")

    for line in lines[1:]:  # skip header
        line = line.strip()
        if not line:
            continue

        parts = line.split(";")
        if len(parts) < 2:
            continue

        try:
            # German date format: DD.MM.YYYY
            date_str = parts[0].strip()
            trade_date = datetime.strptime(date_str, "%d.%m.%Y").date()

            # German decimal: comma → dot
            price_str = parts[1].strip().replace(",", ".")
            price = float(price_str)

            points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=price))
        except (ValueError, IndexError):
            continue

    return sorted(points, key=lambda p: p.trade_date)


def fetch_gas_prices(
    start_date: date,
    end_date: date,
) -> list[GasPricePoint]:
    """
    Fetch THE reference prices for the given date range.

    Downloads annual CSV files and filters to the requested range.
    Weekend/holiday gaps are normal (no trading on those days).
    """
    years = set(range(start_date.year, end_date.year + 1))
    all_points: list[GasPricePoint] = []

    for year in sorted(years):
        url = THE_BASE_URL.format(year=year)
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url)

            if response.status_code != 200:
                raise GasPriceError(f"THE returned HTTP {response.status_code} for {year}: {response.text[:200]}")

            points = _parse_the_csv(response.text)
            all_points.extend(points)

        except httpx.RequestError as exc:
            raise GasPriceError(f"Network error fetching THE gas prices for {year}: {exc}") from exc

    filtered = [p for p in all_points if start_date <= p.trade_date <= end_date]

    if not filtered:
        raise GasPriceError(f"No THE gas price data found for {start_date} → {end_date}")

    return filtered
