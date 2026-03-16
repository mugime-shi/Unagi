"""
ENTSO-E Transparency Platform client.

Fetches SE3 day-ahead spot prices (document type A44) and
actual generation per production type (document type A75).
API docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
SE3_AREA = "10Y1001A1001A46L"

# XML namespace for A44 price documents
NS = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}

# XML namespace for A75 generation documents
NS_GEN = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}

# PSR type → human-readable group (ENTSO-E codes)
PSR_GROUP: dict[str, str] = {
    "B04": "fossil",   # Fossil Gas
    "B05": "fossil",   # Fossil Hard coal
    "B06": "fossil",   # Fossil Oil
    "B11": "hydro",    # Hydro Run-of-river
    "B12": "hydro",    # Hydro Water Reservoir
    "B14": "nuclear",  # Nuclear
    "B16": "solar",    # Solar
    "B17": "other",    # Waste
    "B18": "wind",     # Wind Offshore
    "B19": "wind",     # Wind Onshore
    "B20": "other",    # Other
}
RENEWABLE_PSR = {"B11", "B12", "B16", "B18", "B19"}


@dataclass
class PricePoint:
    timestamp_utc: datetime  # start of the 15-min (or 60-min) slot
    price_eur_mwh: float
    price_sek_kwh: float
    resolution: str  # "PT15M" or "PT60M"


class EntsoEError(Exception):
    pass


def _period_param(dt: date) -> str:
    """Format a date as YYYYMMDDHHMM (midnight UTC) for ENTSO-E."""
    return dt.strftime("%Y%m%d") + "0000"


def _parse_resolution(resolution_text: str) -> timedelta:
    """Convert 'PT15M' or 'PT60M' to a timedelta."""
    if resolution_text == "PT15M":
        return timedelta(minutes=15)
    if resolution_text in ("PT60M", "PT1H"):
        return timedelta(hours=1)
    raise EntsoEError(f"Unknown resolution: {resolution_text}")


def _parse_xml(xml_text: str, eur_to_sek: float) -> list[PricePoint]:
    """
    Parse ENTSO-E Publication_MarketDocument XML into PricePoint list.

    Each TimeSeries contains a Period with:
      - timeInterval/start  (UTC, e.g. "2026-03-08T23:00Z")
      - resolution           (e.g. "PT60M")
      - Point/position       (1-based index)
      - Point/price.amount   (EUR/MWh)
    """
    root = ET.fromstring(xml_text)

    # Check for error acknowledgement document
    doc_type = root.find("ns:type", NS)
    if doc_type is not None and doc_type.text == "A44":
        pass  # normal day-ahead prices document

    reason = root.find(".//ns:Reason/ns:code", NS)
    if reason is not None and reason.text != "999":
        text = root.find(".//ns:Reason/ns:text", NS)
        raise EntsoEError(f"ENTSO-E API error {reason.text}: {text.text if text is not None else ''}")

    points: list[PricePoint] = []

    for ts in root.findall(".//ns:TimeSeries", NS):
        period = ts.find("ns:Period", NS)
        if period is None:
            continue

        start_el = period.find("ns:timeInterval/ns:start", NS)
        if start_el is None:
            continue
        period_start = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))

        resolution_el = period.find("ns:resolution", NS)
        if resolution_el is None:
            continue
        slot_duration = _parse_resolution(resolution_el.text)
        resolution_str = resolution_el.text

        for point_el in period.findall("ns:Point", NS):
            pos_el = point_el.find("ns:position", NS)
            price_el = point_el.find("ns:price.amount", NS)
            if pos_el is None or price_el is None:
                continue

            position = int(pos_el.text) - 1  # 1-based → 0-based offset
            price_eur_mwh = float(price_el.text)

            timestamp = period_start + slot_duration * position
            price_sek_kwh = round(price_eur_mwh * eur_to_sek / 1000, 6)  # EUR/MWh → SEK/kWh

            points.append(
                PricePoint(
                    timestamp_utc=timestamp,
                    price_eur_mwh=price_eur_mwh,
                    price_sek_kwh=price_sek_kwh,
                    resolution=resolution_str,
                )
            )

    return sorted(points, key=lambda p: p.timestamp_utc)


def fetch_day_ahead_prices(
    target_date: date,
    area: str = SE3_AREA,
    api_key: Optional[str] = None,
    eur_to_sek: Optional[float] = None,
) -> list[PricePoint]:
    """
    Fetch SE3 day-ahead prices for `target_date` from ENTSO-E.

    ENTSO-E publishes the next day's prices at ~13:00 CET.
    The query window must cover the full day in UTC (previous day 23:00 → current day 23:00 CET).

    Returns a list of PricePoint sorted by timestamp_utc.
    Raises EntsoEError on API or parse failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    rate = eur_to_sek if eur_to_sek is not None else settings.eur_to_sek_rate

    # ENTSO-E day-ahead prices are published for CET day (UTC-1 in winter, UTC-2 in summer).
    # A safe query window: day-1 22:00 UTC → day+1 02:00 UTC captures the full CET day.
    period_start = target_date - timedelta(days=1)
    period_end = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType": "A44",
        "in_Domain": area,
        "out_Domain": area,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(
            f"ENTSO-E returned HTTP {response.status_code}: {response.text[:200]}"
        )

    all_points = _parse_xml(response.text, rate)

    # Filter to only slots that fall within the requested calendar date (UTC+1 CET proxy)
    # We keep slots where the CET date matches target_date.
    # Simple approach: filter by UTC hour 23:00 previous day to 23:00 same day.
    day_start_utc = datetime(target_date.year, target_date.month, target_date.day,
                             0, 0, tzinfo=timezone.utc) - timedelta(hours=1)  # 23:00 UTC prev day = 00:00 CET
    day_end_utc = day_start_utc + timedelta(hours=24)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise EntsoEError(
            f"No price data found for {target_date} in SE3. "
            "Tomorrow's prices are published after ~13:00 CET."
        )

    return filtered


# ---------------------------------------------------------------------------
# A75: Actual Generation Per Production Type
# ---------------------------------------------------------------------------

@dataclass
class GenerationPoint:
    timestamp_utc: datetime
    psr_type: str       # e.g. "B12" (Hydro), "B14" (Nuclear), "B16" (Solar)
    value_mw: float
    resolution: str     # "PT15M"


def _parse_generation_xml(xml_text: str) -> list[GenerationPoint]:
    """
    Parse ENTSO-E A75 GL_MarketDocument XML into GenerationPoint list.

    ENTSO-E uses step-function encoding: only positions where the value
    changes are listed. Intermediate slots carry the previous value forward.
    This function expands the step function into one row per 15-min slot.
    """
    root = ET.fromstring(xml_text)

    reason = root.find(".//ns:Reason/ns:code", NS_GEN)
    if reason is not None and reason.text != "999":
        text_el = root.find(".//ns:Reason/ns:text", NS_GEN)
        raise EntsoEError(
            f"ENTSO-E A75 error {reason.text}: {text_el.text if text_el is not None else ''}"
        )

    points: list[GenerationPoint] = []

    for ts in root.findall(".//ns:TimeSeries", NS_GEN):
        psr_el = ts.find("ns:MktPSRType/ns:psrType", NS_GEN)
        if psr_el is None:
            continue
        psr_type = psr_el.text

        period = ts.find("ns:Period", NS_GEN)
        if period is None:
            continue

        start_el = period.find("ns:timeInterval/ns:start", NS_GEN)
        end_el   = period.find("ns:timeInterval/ns:end",   NS_GEN)
        res_el   = period.find("ns:resolution", NS_GEN)
        if start_el is None or res_el is None:
            continue

        period_start = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
        slot_duration = _parse_resolution(res_el.text)
        resolution_str = res_el.text

        # Compute total slots in this period (needed for last step-function block)
        if end_el is not None:
            period_end_ts = datetime.fromisoformat(end_el.text.replace("Z", "+00:00"))
            total_slots = int((period_end_ts - period_start) / slot_duration)
        else:
            total_slots = 0

        # Collect explicitly listed (position, quantity) pairs
        raw: list[tuple[int, float]] = []
        for point_el in period.findall("ns:Point", NS_GEN):
            pos_el = point_el.find("ns:position", NS_GEN)
            qty_el = point_el.find("ns:quantity",  NS_GEN)
            if pos_el is None or qty_el is None:
                continue
            raw.append((int(pos_el.text), float(qty_el.text)))

        # Expand step function: each listed position applies until the next
        for i, (pos, qty) in enumerate(raw):
            next_pos = raw[i + 1][0] if i + 1 < len(raw) else total_slots + 1
            for slot in range(pos, next_pos):
                timestamp = period_start + slot_duration * (slot - 1)  # 1-based → offset
                points.append(GenerationPoint(
                    timestamp_utc=timestamp,
                    psr_type=psr_type,
                    value_mw=qty,
                    resolution=resolution_str,
                ))

    return sorted(points, key=lambda p: (p.timestamp_utc, p.psr_type))


def fetch_generation_mix(
    target_date: date,
    area: str = SE3_AREA,
    api_key: Optional[str] = None,
) -> list[GenerationPoint]:
    """
    Fetch actual generation per production type (A75/A16) for target_date.

    Returns GenerationPoint list (one row per psr_type per 15-min slot)
    filtered to the CET calendar day, sorted by (timestamp_utc, psr_type).
    Raises EntsoEError on failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    period_start = target_date - timedelta(days=1)
    period_end   = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType":  "A75",
        "processType":   "A16",
        "in_Domain":     area,
        "periodStart":   _period_param(period_start),
        "periodEnd":     _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(
            f"ENTSO-E A75 returned HTTP {response.status_code}: {response.text[:200]}"
        )

    all_points = _parse_generation_xml(response.text)

    # Filter to CET calendar day (same window as day-ahead prices)
    day_start_utc = (
        datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
        - timedelta(hours=1)
    )
    day_end_utc = day_start_utc + timedelta(hours=24)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise EntsoEError(
            f"No generation data found for {target_date} in {area}. "
            "A75 data lags ~15-30 min behind real time."
        )

    return filtered
