"""
ENTSO-E Transparency Platform client.

Fetches SE3 day-ahead spot prices (document type A44) and
actual generation per production type (document type A75).
API docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import httpx

from app.config import settings
from app.utils.timezone import stockholm_day_range_utc

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
SE3_AREA = "10Y1001A1001A46L"
DE_LU_AREA = "10Y1001A1001A82H"

# Friendly name → EIC code (bidding zone domain)
_AREA_TO_EIC: dict[str, str] = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "DE-LU": "10Y1001A1001A82H",
}

# XML namespace for A44 price documents
NS = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}

# XML namespace for A75 generation documents
NS_GEN = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}

# PSR type → human-readable group (ENTSO-E codes)
PSR_GROUP: dict[str, str] = {
    "B04": "fossil",  # Fossil Gas
    "B05": "fossil",  # Fossil Hard coal
    "B06": "fossil",  # Fossil Oil
    "B11": "hydro",  # Hydro Run-of-river
    "B12": "hydro",  # Hydro Water Reservoir
    "B14": "nuclear",  # Nuclear
    "B16": "solar",  # Solar
    "B17": "other",  # Waste
    "B18": "wind",  # Wind Offshore
    "B19": "wind",  # Wind Onshore
    "B20": "other",  # Other
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
    The query window must cover the full day in UTC (Stockholm time, CET/CEST).

    Returns a list of PricePoint sorted by timestamp_utc.
    Raises EntsoEError on API or parse failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    if eur_to_sek is not None:
        rate = eur_to_sek
    else:
        from app.services.riksbank_client import get_eur_sek_rate

        rate = get_eur_sek_rate()

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
        raise EntsoEError(f"ENTSO-E returned HTTP {response.status_code}: {response.text[:200]}")

    all_points = _parse_xml(response.text, rate)

    # Filter to only slots that fall within the requested Stockholm calendar day.
    # stockholm_day_range_utc handles CET (UTC+1) and CEST (UTC+2) automatically.
    day_start_utc, day_end_utc = stockholm_day_range_utc(target_date)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise EntsoEError(
            f"No price data found for {target_date} in SE3. Tomorrow's prices are published after ~13:00 CET."
        )

    return filtered


# ---------------------------------------------------------------------------
# A75: Actual Generation Per Production Type
# ---------------------------------------------------------------------------


@dataclass
class GenerationPoint:
    timestamp_utc: datetime
    psr_type: str  # e.g. "B12" (Hydro), "B14" (Nuclear), "B16" (Solar)
    value_mw: float
    resolution: str  # "PT15M"


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
        raise EntsoEError(f"ENTSO-E A75 error {reason.text}: {text_el.text if text_el is not None else ''}")

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
        end_el = period.find("ns:timeInterval/ns:end", NS_GEN)
        res_el = period.find("ns:resolution", NS_GEN)
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
            qty_el = point_el.find("ns:quantity", NS_GEN)
            if pos_el is None or qty_el is None:
                continue
            raw.append((int(pos_el.text), float(qty_el.text)))

        # Expand step function: each listed position applies until the next
        for i, (pos, qty) in enumerate(raw):
            next_pos = raw[i + 1][0] if i + 1 < len(raw) else total_slots + 1
            for slot in range(pos, next_pos):
                timestamp = period_start + slot_duration * (slot - 1)  # 1-based → offset
                points.append(
                    GenerationPoint(
                        timestamp_utc=timestamp,
                        psr_type=psr_type,
                        value_mw=qty,
                        resolution=resolution_str,
                    )
                )

    return sorted(points, key=lambda p: (p.timestamp_utc, p.psr_type))


# ---------------------------------------------------------------------------
# A65: Day-Ahead Total Load Forecast
# ---------------------------------------------------------------------------


@dataclass
class LoadForecastPoint:
    timestamp_utc: datetime
    load_mw: float
    resolution: str  # "PT60M"


def _parse_load_forecast_xml(xml_text: str) -> list[LoadForecastPoint]:
    """
    Parse ENTSO-E A65 GL_MarketDocument XML into LoadForecastPoint list.

    A65 documents contain a single TimeSeries per period with quantity values
    (MW) at each position. Uses the same step-function encoding as A75.
    """
    root = ET.fromstring(xml_text)

    reason = root.find(".//ns:Reason/ns:code", NS_GEN)
    if reason is not None and reason.text != "999":
        text_el = root.find(".//ns:Reason/ns:text", NS_GEN)
        raise EntsoEError(f"ENTSO-E A65 error {reason.text}: {text_el.text if text_el is not None else ''}")

    points: list[LoadForecastPoint] = []

    for ts in root.findall(".//ns:TimeSeries", NS_GEN):
        period = ts.find("ns:Period", NS_GEN)
        if period is None:
            continue

        start_el = period.find("ns:timeInterval/ns:start", NS_GEN)
        res_el = period.find("ns:resolution", NS_GEN)
        if start_el is None or res_el is None:
            continue

        period_start = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
        slot_duration = _parse_resolution(res_el.text)
        resolution_str = res_el.text

        for point_el in period.findall("ns:Point", NS_GEN):
            pos_el = point_el.find("ns:position", NS_GEN)
            qty_el = point_el.find("ns:quantity", NS_GEN)
            if pos_el is None or qty_el is None:
                continue

            position = int(pos_el.text) - 1
            timestamp = period_start + slot_duration * position

            points.append(
                LoadForecastPoint(
                    timestamp_utc=timestamp,
                    load_mw=float(qty_el.text),
                    resolution=resolution_str,
                )
            )

    return sorted(points, key=lambda p: p.timestamp_utc)


def fetch_load_forecast(
    target_date: date,
    area: str = SE3_AREA,
    api_key: Optional[str] = None,
) -> list[LoadForecastPoint]:
    """
    Fetch day-ahead total load forecast (A65/A01) for target_date.

    Returns LoadForecastPoint list (one row per hour) filtered to the Stockholm time (CET/CEST)
    calendar day, sorted by timestamp_utc. Raises EntsoEError on failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    period_start = target_date - timedelta(days=1)
    period_end = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType": "A65",
        "processType": "A01",
        "outBiddingZone_Domain": area,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(f"ENTSO-E A65 returned HTTP {response.status_code}: {response.text[:200]}")

    all_points = _parse_load_forecast_xml(response.text)

    # Filter to Stockholm calendar day (handles CET/CEST automatically)
    day_start_utc, day_end_utc = stockholm_day_range_utc(target_date)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise EntsoEError(
            f"No load forecast data found for {target_date} in {area}. A65 data may not yet be available."
        )

    return filtered


@dataclass
class DePricePoint:
    timestamp_utc: datetime
    price_eur_mwh: float
    resolution: str


def fetch_de_day_ahead_prices(
    target_date: date,
    api_key: Optional[str] = None,
) -> list[DePricePoint]:
    """
    Fetch DE-LU day-ahead spot prices (A44) for target_date from ENTSO-E.
    Returns EUR/MWh only (no SEK conversion).
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    period_start = target_date - timedelta(days=1)
    period_end = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType": "A44",
        "in_Domain": DE_LU_AREA,
        "out_Domain": DE_LU_AREA,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(f"ENTSO-E A44 DE-LU returned HTTP {response.status_code}: {response.text[:200]}")

    # Reuse existing XML parser with dummy rate — we only use price_eur_mwh
    all_points = _parse_xml(response.text, eur_to_sek=1.0)

    # Filter to Stockholm calendar day (handles CET/CEST automatically)
    day_start_utc, day_end_utc = stockholm_day_range_utc(target_date)

    filtered = [
        DePricePoint(
            timestamp_utc=p.timestamp_utc,
            price_eur_mwh=p.price_eur_mwh,
            resolution=p.resolution,
        )
        for p in all_points
        if day_start_utc <= p.timestamp_utc < day_end_utc
    ]

    if not filtered:
        raise EntsoEError(f"No DE-LU price data found for {target_date}.")

    return filtered


def fetch_generation_mix(
    target_date: date,
    area: str = SE3_AREA,
    api_key: Optional[str] = None,
    timeout: float = 30.0,
) -> list[GenerationPoint]:
    """
    Fetch actual generation per production type (A75/A16) for target_date.

    Returns GenerationPoint list (one row per psr_type per 15-min slot)
    filtered to the Stockholm time (CET/CEST) calendar day, sorted by (timestamp_utc, psr_type).
    Raises EntsoEError on failure.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")

    period_start = target_date - timedelta(days=1)
    period_end = target_date + timedelta(days=1)

    params = {
        "securityToken": key,
        "documentType": "A75",
        "processType": "A16",
        "in_Domain": area,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(f"ENTSO-E A75 returned HTTP {response.status_code}: {response.text[:200]}")

    all_points = _parse_generation_xml(response.text)

    # Filter to Stockholm calendar day (handles CET/CEST automatically)
    day_start_utc, day_end_utc = stockholm_day_range_utc(target_date)

    filtered = [p for p in all_points if day_start_utc <= p.timestamp_utc < day_end_utc]

    if not filtered:
        raise EntsoEError(
            f"No generation data found for {target_date} in {area}. A75 data lags ~15-30 min behind real time."
        )

    return filtered


# ---------------------------------------------------------------------------
# A72: Hydro reservoir stored energy (weekly)
# ---------------------------------------------------------------------------

# XML namespace for A72 generation/load documents
NS_HYDRO = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}


@dataclass
class HydroReservoirPoint:
    week_start: date  # Monday of the reporting week (CET)
    stored_energy_mwh: float  # total stored energy in MWh


def fetch_hydro_reservoir(
    period_start: date,
    period_end: date,
    area: str = SE3_AREA,
    api_key: str | None = None,
) -> list[HydroReservoirPoint]:
    """
    Fetch weekly hydro reservoir stored energy from ENTSO-E A72.

    Returns one HydroReservoirPoint per week in the requested range.
    Data is published weekly (P7D resolution) in MWh.
    """
    api_key = api_key or settings.entsoe_api_key
    params = {
        "securityToken": api_key,
        "documentType": "A72",
        "processType": "A16",
        "in_Domain": area,
        "periodStart": _period_param(period_start),
        "periodEnd": _period_param(period_end),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.HTTPError as exc:
        raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc

    if response.status_code != 200:
        raise EntsoEError(f"ENTSO-E A72 returned HTTP {response.status_code}: {response.text[:200]}")

    # Check for "no data" acknowledgement
    if "Acknowledgement_MarketDocument" in response.text:
        raise EntsoEError(f"No hydro reservoir data for {area} in {period_start}–{period_end}")

    return _parse_hydro_xml(response.text)


def _parse_hydro_xml(xml_text: str) -> list[HydroReservoirPoint]:
    """Parse ENTSO-E A72 GL_MarketDocument XML into HydroReservoirPoint list."""
    root = ET.fromstring(xml_text)
    points: list[HydroReservoirPoint] = []

    for ts in root.findall(".//ns:TimeSeries", NS_HYDRO):
        period = ts.find("ns:Period", NS_HYDRO)
        if period is None:
            continue

        interval = period.find("ns:timeInterval", NS_HYDRO)
        if interval is None:
            continue

        start_text = interval.findtext("ns:start", default="", namespaces=NS_HYDRO)
        if not start_text:
            continue

        # Parse period start (UTC) — e.g. "2024-12-29T23:00Z" = Monday 00:00 CET
        period_start_utc = datetime.fromisoformat(start_text.replace("Z", "+00:00"))

        resolution = period.findtext("ns:resolution", default="P7D", namespaces=NS_HYDRO)
        if resolution != "P7D":
            continue  # only handle weekly data

        for point in period.findall("ns:Point", NS_HYDRO):
            position = int(point.findtext("ns:position", default="0", namespaces=NS_HYDRO))
            quantity = float(point.findtext("ns:quantity", default="0", namespaces=NS_HYDRO))

            # Each position is one week from the period start
            week_offset = timedelta(weeks=position - 1)
            week_start_utc = period_start_utc + week_offset
            # Convert to CET date (the Monday)
            week_start_date = (week_start_utc + timedelta(hours=1)).date()  # UTC+1 (CET base)

            points.append(
                HydroReservoirPoint(
                    week_start=week_start_date,
                    stored_energy_mwh=quantity,
                )
            )

    return sorted(points, key=lambda p: p.week_start)


# ---------------------------------------------------------------------------
# A77 / A80: Unavailability of generation / production units (outages)
# ---------------------------------------------------------------------------

NS_OUTAGE = {"ns": "urn:iec62325.351:tc57wg16:451-6:outagedocument:3:0"}
_EIC_TO_AREA = {eic: name for name, eic in _AREA_TO_EIC.items()}
_OUTAGE_PAGE_SIZE = 200  # ENTSO-E returns at most 200 documents per request
_OUTAGE_TIMEOUT = 60.0  # cold requests take up to ~13 s


def _parse_outage_dt(text: str) -> datetime:
    """Parse '2026-10-06T08:00Z' / '...:00Z' into an aware UTC datetime."""
    return datetime.fromisoformat(text.strip().replace("Z", "+00:00")).astimezone(timezone.utc)


def _outage_dt_pair(ts: ET.Element, prefix: str) -> Optional[datetime]:
    d = ts.findtext(f"ns:{prefix}_DateAndOrTime.date", namespaces=NS_OUTAGE)
    t = ts.findtext(f"ns:{prefix}_DateAndOrTime.time", namespaces=NS_OUTAGE)
    if not d:
        return None
    return _parse_outage_dt(f"{d.strip()}T{(t or '00:00:00Z').strip()}")


def _available_periods(ts: ET.Element) -> list[dict]:
    """
    Convert Available_Period/Point step functions into absolute periods.

    A point holds its quantity until the next point's position (curveType A03),
    the last one until the period end. Consecutive equal quantities are merged.
    """
    out: list[dict] = []
    for ap in ts.findall("ns:Available_Period", NS_OUTAGE):
        start_el = ap.find("ns:timeInterval/ns:start", NS_OUTAGE)
        end_el = ap.find("ns:timeInterval/ns:end", NS_OUTAGE)
        res_el = ap.find("ns:resolution", NS_OUTAGE)
        if start_el is None or end_el is None or res_el is None:
            continue
        p_start, p_end = _parse_outage_dt(start_el.text), _parse_outage_dt(end_el.text)
        step = _parse_outage_resolution(res_el.text)
        pts = sorted(
            (
                int(p.findtext("ns:position", namespaces=NS_OUTAGE)),
                float(p.findtext("ns:quantity", namespaces=NS_OUTAGE)),
            )
            for p in ap.findall("ns:Point", NS_OUTAGE)
        )
        for i, (pos, qty) in enumerate(pts):
            seg_start = p_start + step * (pos - 1)
            seg_end = p_start + step * (pts[i + 1][0] - 1) if i + 1 < len(pts) else p_end
            seg_end = min(seg_end, p_end)
            if seg_end <= seg_start:
                continue
            if out and out[-1]["mw"] == qty and out[-1]["end"] == seg_start.isoformat():
                out[-1]["end"] = seg_end.isoformat()
            else:
                out.append({"start": seg_start.isoformat(), "end": seg_end.isoformat(), "mw": qty})
    return out


def _parse_outage_resolution(text: str) -> timedelta:
    """Generic ISO-8601 'PT<n>M' / 'PT<n>H' resolution (PT1M, PT15M, PT60M, PT1H ...)."""
    t = text.strip()
    if t.startswith("PT") and t[-1] in "MH" and t[2:-1].isdigit():
        n = int(t[2:-1])
        return timedelta(minutes=n) if t[-1] == "M" else timedelta(hours=n)
    raise EntsoEError(f"Unknown resolution: {text}")


def _parse_unavailability_xml(xml_text: str | bytes, area: str = "") -> list[dict]:
    """
    Parse one Unavailability_MarketDocument into outage dicts (one per TimeSeries,
    in practice one per document). Raises EntsoEError on an unexpected acknowledgement.
    """
    root = ET.fromstring(xml_text)
    if root.tag.split("}")[-1] != "Unavailability_MarketDocument":
        code = root.findtext(".//{*}Reason/{*}code")
        text = root.findtext(".//{*}Reason/{*}text") or ""
        if code == "999":
            return []
        raise EntsoEError(f"ENTSO-E API error {code}: {text}")

    mrid = root.findtext("ns:mRID", namespaces=NS_OUTAGE)
    revision = int(root.findtext("ns:revisionNumber", default="1", namespaces=NS_OUTAGE) or 1)
    doc_type = root.findtext("ns:type", namespaces=NS_OUTAGE)
    doc_status = root.findtext("ns:docStatus/ns:value", namespaces=NS_OUTAGE)
    created = root.findtext("ns:createdDateTime", namespaces=NS_OUTAGE)
    doc_reason_code = root.findtext("ns:Reason/ns:code", namespaces=NS_OUTAGE)
    doc_start = root.findtext("ns:unavailability_Time_Period.timeInterval/ns:start", namespaces=NS_OUTAGE)
    doc_end = root.findtext("ns:unavailability_Time_Period.timeInterval/ns:end", namespaces=NS_OUTAGE)

    series = root.findall("ns:TimeSeries", NS_OUTAGE)
    out: list[dict] = []
    for idx, ts in enumerate(series):
        r = "production_RegisteredResource"
        eic_zone = ts.findtext("ns:biddingZone_Domain.mRID", namespaces=NS_OUTAGE)
        start = _outage_dt_pair(ts, "start") or (_parse_outage_dt(doc_start) if doc_start else None)
        end = _outage_dt_pair(ts, "end") or (_parse_outage_dt(doc_end) if doc_end else None)
        if start is None or end is None:
            continue
        nominal = ts.findtext(f"ns:{r}.pSRType.powerSystemResources.nominalP", namespaces=NS_OUTAGE)
        # TimeSeries-level reason (A95 + free text) is more specific than the doc-level B18/B19
        ts_code = ts.findtext("ns:Reason/ns:code", namespaces=NS_OUTAGE)
        ts_text = ts.findtext("ns:Reason/ns:text", namespaces=NS_OUTAGE)
        ts_mrid = ts.findtext("ns:mRID", namespaces=NS_OUTAGE)
        out.append(
            {
                "mrid": mrid if len(series) == 1 else f"{mrid}:{ts_mrid or idx + 1}",
                "revision": revision,
                "document_type": doc_type,
                "business_type": ts.findtext("ns:businessType", namespaces=NS_OUTAGE),
                "status": "cancelled" if doc_status == "A09" else "active",
                "area": _EIC_TO_AREA.get((eic_zone or "").strip(), area),
                "resource_eic": (ts.findtext(f"ns:{r}.mRID", namespaces=NS_OUTAGE) or "").strip() or None,
                "resource_name": (ts.findtext(f"ns:{r}.name", namespaces=NS_OUTAGE) or "").strip() or None,
                "psr_type": ts.findtext(f"ns:{r}.pSRType.psrType", namespaces=NS_OUTAGE),
                "nominal_mw": float(nominal) if nominal else None,
                "start_utc": start,
                "end_utc": end,
                "available_periods": _available_periods(ts),
                "reason_code": (ts_code or doc_reason_code),
                "reason_text": (ts_text.strip() if ts_text else None),
                "created_utc": _parse_outage_dt(created) if created else None,
            }
        )
    return out


def _parse_unavailability_response(content: bytes, area: str) -> tuple[list[dict], int]:
    """Return (outages, number_of_documents) for one HTTP response body."""
    if content[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise EntsoEError(f"Corrupt zip from ENTSO-E: {exc}") from exc
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        outages: list[dict] = []
        for n in names:
            outages.extend(_parse_unavailability_xml(zf.read(n), area))
        return outages, len(names)
    # No zip: single document or an Acknowledgement (999 = no data)
    return _parse_unavailability_xml(content, area), 0


def fetch_unavailability(
    area: str,
    doc_type: Literal["A77", "A80"],
    start_utc: datetime,
    end_utc: datetime,
    api_key: Optional[str] = None,
) -> list[dict]:
    """
    Fetch unavailability of generation (A77) or production (A80) units for an
    area over [start_utc, end_utc). Pages through `offset` (200 docs/request).

    Returns outage dicts (see _parse_unavailability_xml). Empty list when
    ENTSO-E reports no data (acknowledgement 999). Raises EntsoEError otherwise.
    """
    key = api_key or settings.entsoe_api_key
    if not key:
        raise EntsoEError("ENTSOE_API_KEY is not set. Add it to backend/.env")
    eic = _AREA_TO_EIC.get(area)
    if eic is None:
        raise EntsoEError(f"Unknown area: {area}")

    def fmt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M")

    results: list[dict] = []
    offset = 0
    while True:
        params: dict[str, str | int] = {
            "securityToken": key,
            "documentType": doc_type,
            "biddingZone_Domain": eic,
            "periodStart": fmt(start_utc),
            "periodEnd": fmt(end_utc),
        }
        if offset:
            params["offset"] = offset
        try:
            with httpx.Client(timeout=_OUTAGE_TIMEOUT) as client:
                response = client.get(ENTSOE_BASE, params=params)
        except httpx.RequestError as exc:
            raise EntsoEError(f"Network error contacting ENTSO-E: {exc}") from exc
        if response.status_code != 200:
            raise EntsoEError(f"ENTSO-E {doc_type} returned HTTP {response.status_code}: {response.text[:200]}")
        page, n_docs = _parse_unavailability_response(response.content, area)
        results.extend(page)
        if n_docs < _OUTAGE_PAGE_SIZE:
            return results
        offset += _OUTAGE_PAGE_SIZE
