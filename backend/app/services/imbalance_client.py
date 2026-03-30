"""
ENTSO-E Transparency Platform client for Balancing (Imbalance) prices.

Document type A85 — Balancing_MarketDocument.
SE3 area uses EIC code 10Y1001A1001A46L (same as DA).

Key differences from Day-ahead (A44):
- Response is a ZIP archive containing one XML file
- Different XML namespace: urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:4
- Price field tag: <imbalance_Price.amount>  (not <price.amount>)
- Category field:  <imbalance_Price.category>
    A04 = Long  (excess supply — price is typically at or below DA)
    A05 = Short (supply deficit — price spikes, can be 2–3× DA)
- Resolution: always PT15M for SE3

Market context:
  Day-ahead prices are set the previous afternoon for the whole next day.
  Imbalance prices are settled every 15 minutes by Svenska kraftnät (SVK)
  after each interval closes. They reflect the real cost of balancing the grid
  within that slot — much higher when the grid was short (A05), much lower or
  even negative when long (A04).
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.config import settings
from app.utils.timezone import stockholm_midnight_utc

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
SE3_EIC = "10Y1001A1001A46L"

# XML namespace in Balancing_MarketDocument (different from Publication_MarketDocument)
NS_B = "urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:4"

CATEGORY_LONG = "A04"  # Excess supply (oversupply → price ≤ DA)
CATEGORY_SHORT = "A05"  # Supply deficit (shortage → price ≥ DA, can spike)


@dataclass
class BalancingPoint:
    timestamp_utc: datetime  # start of the 15-min slot
    price_eur_mwh: float
    price_sek_kwh: float
    category: str  # "A04" (Long) or "A05" (Short)
    resolution: str = field(default="PT15M")


class BalancingError(Exception):
    pass


def _period_param(dt: date) -> str:
    """Format a date as YYYYMMDDHHMM (midnight UTC) for ENTSO-E."""
    return dt.strftime("%Y%m%d") + "0000"


def _parse_zip_response(content: bytes, eur_to_sek: float) -> list[BalancingPoint]:
    """
    Parse ENTSO-E A85 ZIP response into a list of BalancingPoints.

    The ZIP contains one XML file with root element Balancing_MarketDocument.
    Each TimeSeries covers one imbalance category (A04 or A05).
    Period resolution is PT15M; positions are 1-based.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise BalancingError(f"ENTSO-E A85 response is not a valid ZIP: {exc}") from exc

    points: list[BalancingPoint] = []

    for fname in zf.namelist():
        xml_text = zf.read(fname).decode("utf-8")
        root = ET.fromstring(xml_text)

        for ts in root.findall(f"{{{NS_B}}}TimeSeries"):
            period = ts.find(f"{{{NS_B}}}Period")
            if period is None:
                continue

            ti = period.find(f"{{{NS_B}}}timeInterval")
            if ti is None:
                continue

            start_el = ti.find(f"{{{NS_B}}}start")
            if start_el is None:
                continue
            period_start = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))

            res_el = period.find(f"{{{NS_B}}}resolution")
            res_str = res_el.text if res_el is not None else "PT15M"
            slot_td = timedelta(minutes=15) if res_str == "PT15M" else timedelta(hours=1)

            for pt in period.findall(f"{{{NS_B}}}Point"):
                pos_el = pt.find(f"{{{NS_B}}}position")
                price_el = pt.find(f"{{{NS_B}}}imbalance_Price.amount")
                cat_el = pt.find(f"{{{NS_B}}}imbalance_Price.category")

                if pos_el is None or price_el is None or cat_el is None:
                    continue

                position = int(pos_el.text) - 1  # 1-based → 0-based offset
                price_eur_mwh = float(price_el.text)
                category = cat_el.text
                timestamp = period_start + slot_td * position
                price_sek_kwh = round(price_eur_mwh * eur_to_sek / 1000, 6)

                points.append(
                    BalancingPoint(
                        timestamp_utc=timestamp,
                        price_eur_mwh=price_eur_mwh,
                        price_sek_kwh=price_sek_kwh,
                        category=category,
                        resolution=res_str,
                    )
                )

    return sorted(points, key=lambda p: (p.timestamp_utc, p.category))


def fetch_imbalance_prices(
    target_date: date,
    area: str = SE3_EIC,
    api_key: Optional[str] = None,
    eur_to_sek: Optional[float] = None,
) -> list[BalancingPoint]:
    """
    Fetch SE3 imbalance prices for `target_date` from ENTSO-E (document type A85).

    Imbalance prices are settled 15 minutes after each interval closes.
    Yesterday's data is always complete. Today's data is available up to
    approximately 1–2 hours behind the current wall clock.

    Returns a list of BalancingPoint sorted by (timestamp_utc, category).
    Raises BalancingError on any API or parse failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise BalancingError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    rate = eur_to_sek if eur_to_sek is not None else settings.eur_to_sek_rate

    # Wide query window: day-1 00:00 UTC → day+1 00:00 UTC covers the full CET day
    period_start = target_date - timedelta(days=1)
    period_end = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType": "A85",
        "controlArea_Domain": area,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise BalancingError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise BalancingError(f"ENTSO-E returned HTTP {response.status_code}: {response.content[:200]}")

    all_points = _parse_zip_response(response.content, rate)

    # Filter to slots that fall within the requested Stockholm time (CET/CEST) calendar day
    day_start_utc = stockholm_midnight_utc(target_date)
    day_end_utc = day_start_utc + timedelta(hours=24)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise BalancingError(
            f"No imbalance price data found for {target_date} in SE3. "
            "Yesterday is always fully settled; today's data lags ~1–2 hours."
        )

    return filtered
