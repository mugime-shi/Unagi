r"""
Trading Hub Europe (THE) gas price client.

Fetches daily THE settlement prices — used as a proxy for European gas
costs that drive electricity price spikes (especially night-time hours
when wind/solar are unavailable and gas-fired plants set the marginal price).

Data sources (in priority order):
1. THE Ausgleichsenergie Final API — historical date-range queries (primary)
2. THE Ausgleichsenergie Vorlaeufig API — current gas-day only (supplement for today)

THE moved both endpoints from datenservice-api.tradinghub.eu to api.tradinghub.eu
(~2026-09-15). The old host kept answering HTTP 200 with empty lists, so it is kept
as a fallback only: it is tried when the new host errors or returns no usable rows.

The negative balancing energy price (preisAusgleichsenergieNegativ)
serves as the settlement price for shipper imbalances, equivalent
to the retired "Referenzpreis" CSV download.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.utils.timezone import stockholm_today

log = logging.getLogger(__name__)

# Final API — historical settlement prices with date range.
# Response: [{"gastag": "2026-10-25T00:00:00", "preisAusgleichsenergieNegativ": 39.5, ...}]
# (the old host used "T05:00:00" gastag timestamps)
THE_FINAL_API_URL = "https://api.tradinghub.eu/api/website/evoq/GetAusgleichsenergieFinalTabelle"
THE_FINAL_API_URL_LEGACY = "https://datenservice-api.tradinghub.eu/api/evoq/GetAusgleichsenergieFinalTabelle"

# Vorlaeufig API — preliminary prices for the current gas-day. Can include the next gas-day
# as a placeholder row with all prices 0. Replaces the retired Preismonitor endpoint.
THE_PRELIMINARY_API_URL = "https://api.tradinghub.eu/api/website/evoq/GetAusgleichsenergieVorlaeufigTabelle"
THE_PREISMONITOR_URL_LEGACY = "https://datenservice-api.tradinghub.eu/api/evoq/GetPreismonitorTabelle"


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


def _get_json_list(url: str, params: dict | None, label: str) -> list:
    """GET url and return the JSON list, raising GasPriceError on HTTP/network/shape errors."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
    except httpx.RequestError as exc:
        raise GasPriceError(f"Network error fetching {label}: {exc}") from exc

    if response.status_code != 200:
        raise GasPriceError(f"{label} returned HTTP {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise GasPriceError(f"{label} returned invalid JSON") from exc
    if not isinstance(data, list):
        raise GasPriceError(f"{label} returned invalid JSON")
    return data


def _first_of(entry: dict, *keys: str):
    for key in keys:
        if entry.get(key) is not None:
            return entry[key]
    return None


def _try_sources(sources: list[tuple[str, str]], fetch_one, what: str) -> list[GasPricePoint]:
    """
    Return the first non-empty result of fetch_one(url, label) over sources.

    A source that errors or yields no rows falls through to the next (WARNING).
    Returns [] if every source was reachable but empty; raises GasPriceError if
    every source errored.
    """
    errors: list[str] = []
    for i, (label, url) in enumerate(sources):
        try:
            points = fetch_one(url, label)
        except GasPriceError as exc:
            errors.append(str(exc))
            points = []
            reason = f"failed: {exc}"
        else:
            reason = "returned no rows"
        if points:
            log.info("THE %s served by %s (%d row(s))", what, label, len(points))
            return points
        if i + 1 < len(sources):
            log.warning("THE %s %s %s — falling back to %s", what, label, reason, sources[i + 1][0])
    if len(errors) == len(sources):
        raise GasPriceError("; ".join(errors))
    return []


def fetch_gas_prices_from_final_api(
    start_date: date,
    end_date: date,
) -> list[GasPricePoint]:
    """
    Fetch historical THE settlement prices from the Final Ausgleichsenergie API.

    This API supports date-range queries and returns finalized daily settlement
    prices with a ~1 day publication lag. Falls back to the legacy host when the
    new one errors or has no rows in range.

    Uses preisAusgleichsenergieNegativ as the reference price (settlement
    price for negative imbalance = the core gas market price signal).
    """
    params = {
        "DatumStart": start_date.isoformat(),
        "DatumEnde": end_date.isoformat(),
    }

    def fetch_one(url: str, label: str) -> list[GasPricePoint]:
        points: list[GasPricePoint] = []
        for entry in _get_json_list(url, params, label):
            gastag = entry.get("gastag")
            price = entry.get("preisAusgleichsenergieNegativ")
            if gastag is None or price is None:
                continue
            trade_date = datetime.fromisoformat(gastag).date()
            if start_date <= trade_date <= end_date:
                points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=float(price)))
        return sorted(points, key=lambda p: p.trade_date)

    return _try_sources(
        [("THE Final API", THE_FINAL_API_URL), ("legacy THE Final API", THE_FINAL_API_URL_LEGACY)],
        fetch_one,
        "Final prices",
    )


def fetch_gas_prices_from_api() -> list[GasPricePoint]:
    """
    Fetch the current gas-day's preliminary THE settlement price.

    Used as a supplement for today's price, which may not yet appear in the
    Final API (publication lag). Placeholder rows (price 0/missing, as THE
    publishes for the next gas-day) and future dates are dropped. The legacy
    Preismonitor field names are still accepted for the fallback host.
    """
    today = stockholm_today()

    def fetch_one(url: str, label: str) -> list[GasPricePoint]:
        points: list[GasPricePoint] = []
        for entry in _get_json_list(url, None, label):
            gas_tag = _first_of(entry, "gastag", "gasTag")
            price = _first_of(entry, "preisAusgleichsenergieNegativ", "negativer_Ausgleichsenergiepreis")
            if gas_tag is None or not price:
                continue
            trade_date = datetime.fromisoformat(gas_tag).date()
            if trade_date <= today:
                points.append(GasPricePoint(trade_date=trade_date, price_eur_mwh=float(price)))
        return points

    points = _try_sources(
        [("THE preliminary API", THE_PRELIMINARY_API_URL), ("legacy THE Preismonitor", THE_PREISMONITOR_URL_LEGACY)],
        fetch_one,
        "preliminary price",
    )
    if not points:
        raise GasPriceError("THE preliminary API returned no usable rows")
    return points


def fetch_gas_prices(
    start_date: date,
    end_date: date,
) -> list[GasPricePoint]:
    """
    Fetch THE gas prices for the given date range.

    Strategy:
    1. Use the Final Ausgleichsenergie API for historical data (date-range)
    2. Supplement with the Vorlaeufig API for today's price (may not be in Final yet)

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

    # Supplement: preliminary price for today (Final API lags ~1 day)
    today = stockholm_today()
    if start_date <= today <= end_date:
        try:
            today_points = fetch_gas_prices_from_api()
            all_points.extend(today_points)
        except GasPriceError as exc:
            log.debug("Preliminary price fetch failed: %s", exc)

    # Deduplicate by trade_date (Final API takes precedence over preliminary)
    seen: dict[date, GasPricePoint] = {}
    for p in all_points:
        if start_date <= p.trade_date <= end_date:
            if p.trade_date not in seen:
                seen[p.trade_date] = p
    filtered = sorted(seen.values(), key=lambda p: p.trade_date)

    if not filtered:
        raise GasPriceError(f"No THE gas price data found for {start_date} → {end_date}")

    return filtered
