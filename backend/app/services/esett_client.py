"""
eSett Open Data API client for Single Balance Prices (Nordic imbalance prices).

Endpoint: GET https://api.opendata.esett.com/EXP14/Prices
  - mba: Market Balance Area EIC code (SE3 = 10Y1001A1001A46L)
  - start / end: UTC ISO-8601 with milliseconds, e.g. 2026-03-15T00:00:00.000Z

Response fields (prices in EUR/MWh):
  upRegPrice    — marginal up-regulation price; eSett equivalent of ENTSO-E A05 (Short)
  downRegPrice  — marginal down-regulation price; eSett equivalent of ENTSO-E A04 (Long)
  imblSalesPrice    — what a short BRP pays (= upRegPrice since Nordic SIB Apr 2022)
  imblPurchasePrice — what a long BRP receives (= imblSalesPrice in SIB mode)
  imblSpotDifferencePrice — difference between imbalance price and day-ahead spot

Data lag: ~5–6 hours behind real time (vs ENTSO-E A85 which lags ~12 hours).
No API key required — fully public.

Mapping to BalancingPoint.category (keeps DB/frontend interface unchanged):
  upRegPrice   → category "A05"  (Short / up-regulation)
  downRegPrice → category "A04"  (Long  / down-regulation)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

ESETT_BASE = "https://api.opendata.esett.com"

# EIC codes for Swedish bidding areas (same as ENTSO-E)
_AREA_TO_MBA = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
}

CATEGORY_LONG  = "A04"   # down-regulation (excess supply)
CATEGORY_SHORT = "A05"   # up-regulation   (supply deficit)


@dataclass
class BalancingPoint:
    timestamp_utc: datetime
    price_eur_mwh: float
    price_sek_kwh: float
    category: str            # "A04" (Long / downReg) or "A05" (Short / upReg)
    resolution: str = field(default="PT15M")


class BalancingError(Exception):
    pass


def _fmt(dt: datetime) -> str:
    """Format datetime as ISO-8601 with milliseconds for eSett API."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_imbalance_prices(
    target_date: date,
    area: str = "10Y1001A1001A46L",
    eur_to_sek: Optional[float] = None,
    **_kwargs,
) -> list[BalancingPoint]:
    """
    Fetch SE3 imbalance prices from eSett EXP14 for `target_date`.

    Returns a list of BalancingPoint (one A04 + one A05 per 15-min slot)
    sorted by (timestamp_utc, category). Raises BalancingError on failure.

    `area` accepts either a friendly name ("SE3") or an EIC code.
    """
    mba = _AREA_TO_MBA.get(area, area)
    rate = eur_to_sek if eur_to_sek is not None else settings.eur_to_sek_rate

    # Query the full UTC day — eSett returns CET-labelled timestamps so we
    # widen the window by one day on each side to capture the CET calendar day.
    start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc) - timedelta(hours=1)
    end_utc   = start_utc + timedelta(hours=25)

    params = {
        "mba":   mba,
        "start": _fmt(start_utc),
        "end":   _fmt(end_utc),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{ESETT_BASE}/EXP14/Prices", params=params)
    except httpx.RequestError as exc:
        raise BalancingError(f"Network error contacting eSett: {exc}") from exc

    if resp.status_code != 200:
        raise BalancingError(
            f"eSett returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        raw = resp.json()
    except Exception as exc:
        raise BalancingError(f"eSett response is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise BalancingError(f"Unexpected eSett response shape: {type(raw)}")

    points: list[BalancingPoint] = []

    for row in raw:
        ts_str = row.get("timestampUTC")
        if not ts_str:
            continue

        # Parse UTC timestamp
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        up   = row.get("upRegPrice")
        down = row.get("downRegPrice")

        # Skip slots where both prices are absent (future / not yet settled)
        if up is None and down is None:
            continue

        if up is not None:
            points.append(BalancingPoint(
                timestamp_utc=ts,
                price_eur_mwh=float(up),
                price_sek_kwh=round(float(up) * rate / 1000, 6),
                category=CATEGORY_SHORT,   # A05
            ))

        if down is not None:
            points.append(BalancingPoint(
                timestamp_utc=ts,
                price_eur_mwh=float(down),
                price_sek_kwh=round(float(down) * rate / 1000, 6),
                category=CATEGORY_LONG,    # A04
            ))

    if not points:
        raise BalancingError(
            f"No imbalance price data found for {target_date} from eSett. "
            "Data typically lags ~5–6 hours behind real time."
        )

    return sorted(points, key=lambda p: (p.timestamp_utc, p.category))
