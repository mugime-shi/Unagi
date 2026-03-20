r"""
Trading Hub Europe (THE) gas price client.

Fetches daily THE settlement prices — used as a proxy for European gas
costs that drive electricity price spikes (especially night-time hours
when wind/solar are unavailable and gas-fired plants set the marginal price).

Data sources (in priority order):
1. THE Ausgleichsenergie Final API — historical date-range queries (primary)
2. THE Preismonitor API — current gas-day only (fallback for today)

The negative balancing energy price (preisAusgleichsenergieNegativ)
serves as the settlement price for shipper imbalances, equivalent
to the retired "Referenzpreis" CSV download.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

log = logging.getLogger(__name__)

# THE Ausgleichsenergie Final API — returns historical settlement prices with date range.
# Response: [{"gastag": "2025-03-05T05:00:00", "preisAusgleichsenergieNegativ": 39.5, ...}]
THE_FINAL_API_URL = "https://datenservice-api.tradinghub.eu/api/evoq/GetAusgleichsenergieFinalTabelle"

# THE Preismonitor API — returns current gas-day only (today's preliminary prices).
THE_PREISMONITOR_URL = "https://datenservice-api.tradinghub.eu/api/evoq/GetPreismonitorTabelle"


class GasPriceError(Exception):
    pass


@dataclass
class GasPricePoint:
    trade_date: date
    price_eur_mwh: float
    source: str = "the_reference"


def _parse_the_csv(csv_text: str) -> list[GasPricePoint]:
    """
    Parse THE reference price CSV into GasPricePoint list (legacy format).

    Expected format (semicolon-delimited, German locale):
        Gashandelstag;Referenzpreis (EUR/MWh)
        02.01.2025;34,52
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
            date_str = parts[0].strip()
            trade_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            price_str = parts[1].strip().replace(",", ".")
            price = float(price_str)
            points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=price))
        except (ValueError, IndexError):
            continue

    return sorted(points, key=lambda p: p.trade_date)


def fetch_gas_prices_from_final_api(
    start_date: date,
    end_date: date,
) -> list[GasPricePoint]:
    """
    Fetch historical THE settlement prices from the Final Ausgleichsenergie API.

    This API supports date-range queries and returns finalized daily settlement
    prices. Data is available from ~2020 onwards with a ~2 day publication lag.

    Uses preisAusgleichsenergieNegativ as the reference price (settlement
    price for negative imbalance = the core gas market price signal).
    """
    params = {
        "DatumStart": start_date.isoformat(),
        "DatumEnde": end_date.isoformat(),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(THE_FINAL_API_URL, params=params)

        if response.status_code != 200:
            raise GasPriceError(f"THE Final API returned HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        if not isinstance(data, list):
            raise GasPriceError("THE Final API returned invalid JSON")

        points: list[GasPricePoint] = []
        for entry in data:
            gastag = entry.get("gastag")
            price = entry.get("preisAusgleichsenergieNegativ")

            if gastag is None or price is None:
                continue

            trade_date = datetime.fromisoformat(gastag).date()
            points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=float(price)))

        return sorted(points, key=lambda p: p.trade_date)

    except httpx.RequestError as exc:
        raise GasPriceError(f"Network error fetching THE Final API: {exc}") from exc


def fetch_gas_prices_from_api() -> list[GasPricePoint]:
    """
    Fetch today's THE settlement price from the Preismonitor JSON API.

    Returns a list with 0 or 1 GasPricePoint (current gas-day only).
    Used as a fallback for today's price which may not yet appear in
    the Final API (publication lag).
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(THE_PREISMONITOR_URL)

        if response.status_code != 200:
            raise GasPriceError(f"THE API returned HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        if not data or not isinstance(data, list):
            raise GasPriceError("THE API returned empty or invalid JSON")

        points: list[GasPricePoint] = []
        for entry in data:
            gas_tag = entry.get("gasTag")
            price = entry.get("negativer_Ausgleichsenergiepreis")

            if gas_tag is None or price is None:
                continue

            trade_date = datetime.fromisoformat(gas_tag).date()
            points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=float(price)))

        return points

    except httpx.RequestError as exc:
        raise GasPriceError(f"Network error fetching THE gas prices: {exc}") from exc


def fetch_gas_prices(
    start_date: date,
    end_date: date,
) -> list[GasPricePoint]:
    """
    Fetch THE gas prices for the given date range.

    Strategy:
    1. Use the Final Ausgleichsenergie API for historical data (date-range)
    2. Supplement with the Preismonitor API for today's price (may not be in Final yet)

    Both APIs are public, no authentication required.
    """
    # Primary: Final API with date range
    all_points: list[GasPricePoint] = []
    try:
        final_points = fetch_gas_prices_from_final_api(start_date, end_date)
        log.info("THE Final API returned %d gas price point(s) for %s → %s", len(final_points), start_date, end_date)
        all_points.extend(final_points)
    except GasPriceError as exc:
        log.warning("THE Final API failed: %s", exc)

    # Supplement: Preismonitor for today (Final API has ~2 day lag)
    today = date.today()
    if start_date <= today <= end_date:
        try:
            today_points = fetch_gas_prices_from_api()
            all_points.extend(today_points)
        except GasPriceError as exc:
            log.debug("Preismonitor fallback failed: %s", exc)

    # Deduplicate by trade_date (Final API takes precedence over Preismonitor)
    seen: dict[date, GasPricePoint] = {}
    for p in all_points:
        if start_date <= p.trade_date <= end_date:
            if p.trade_date not in seen:
                seen[p.trade_date] = p
    filtered = sorted(seen.values(), key=lambda p: p.trade_date)

    if not filtered:
        raise GasPriceError(f"No THE gas price data found for {start_date} → {end_date}")

    return filtered
