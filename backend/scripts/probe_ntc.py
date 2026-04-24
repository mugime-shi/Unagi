"""
Minimal probe for ENTSO-E Day-Ahead Forecasted Net Transfer Capacity (NTC).

Goal: fetch NTC between SE3 and its main neighbours for a small set of
known-worst and known-calm days, to see whether "SE3 isolated" (low NTC in
from north) correlates with high-MAE days.

If the signal looks real, we proceed to a full implementation (migration +
backfill + feature wiring). If not, we pivot to another data source
(nuclear outage calendar, hydro inflow).

Usage:
    python -m scripts.probe_ntc
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import re
import xml.etree.ElementTree as ET

import httpx

# Load env (running outside Docker requires explicit load)
try:
    from app.config import settings

    API_KEY = settings.entsoe_api_key
except Exception:  # pragma: no cover - fallback when run standalone
    API_KEY = os.getenv("ENTSOE_API_KEY")

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("probe_ntc")

# Bidding-zone EIC codes
AREAS = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "DE-LU": "10Y1001A1001A82H",
    "NO1": "10YNO-1--------2",
    "FI": "10YFI-1--------U",
    "DK1": "10YDK-1--------W",
}

# The flows we believe matter most for SE3 price formation
# (in_Domain = receiving, out_Domain = sending)
LINKS = [
    ("SE2", "SE3"),   # main internal north→south flow (hydro surplus → industrial)
    ("NO1", "SE3"),   # Norway hydro import
    ("FI", "SE3"),    # Finland import
    ("SE3", "SE4"),   # export south (drain direction)
    ("SE3", "DE-LU"), # export south to Germany via SE4 corridor
    ("DE-LU", "SE3"), # import from Germany (reverse)
    ("SE1", "SE2"),   # upstream: lets us see whether north trouble propagates
]


@dataclass
class NtcPoint:
    timestamp_utc: datetime
    mw: float


def _period_param(dt: date) -> str:
    return dt.strftime("%Y%m%d") + "2200"


def _parse_resolution(resolution_text: str) -> timedelta:
    # PT15M / PT30M / PT60M
    if resolution_text == "PT60M":
        return timedelta(hours=1)
    if resolution_text == "PT15M":
        return timedelta(minutes=15)
    if resolution_text == "PT30M":
        return timedelta(minutes=30)
    raise ValueError(f"Unknown resolution: {resolution_text}")


def _strip_namespaces(xml_text: str) -> str:
    """Drop default XML namespace so ET.find() works without prefixes."""
    return re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)


def _parse_ntc_xml(xml_text: str) -> list[NtcPoint]:
    """Parse a Publication_MarketDocument response for transfer capacity."""
    root = ET.fromstring(_strip_namespaces(xml_text))

    points: list[NtcPoint] = []
    for ts_node in root.findall(".//TimeSeries"):
        for period in ts_node.findall(".//Period"):
            start_text = period.find("timeInterval/start").text
            resolution_text = period.find("resolution").text
            start_utc = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            resolution = _parse_resolution(resolution_text)
            for pt in period.findall("Point"):
                position = int(pt.find("position").text)
                qty = float(pt.find("quantity").text)
                ts = start_utc + resolution * (position - 1)
                points.append(NtcPoint(timestamp_utc=ts, mw=qty))

    points.sort(key=lambda p: p.timestamp_utc)
    return points


def fetch_ntc(from_area: str, to_area: str, target_date: date) -> list[NtcPoint]:
    """Fetch actual physical flow (A11) from `from_area` to `to_area`.

    Nord Pool zones don't have explicit forecasted NTC (A61 returns
    Acknowledgement with Reason 999), so we use retrospective actual-flow
    as a proxy for grid congestion.
    """
    if API_KEY is None:
        raise SystemExit("ENTSOE_API_KEY not set")

    params = {
        "securityToken": API_KEY,
        "documentType": "A11",
        "in_Domain": AREAS[to_area],
        "out_Domain": AREAS[from_area],
        "periodStart": _period_param(target_date - timedelta(days=1)),
        "periodEnd": _period_param(target_date + timedelta(days=1)),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ENTSOE_BASE, params=params)
    except httpx.RequestError as exc:
        raise RuntimeError(f"network error: {exc}") from exc

    if response.status_code != 200:
        snippet = response.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"HTTP {response.status_code} for {from_area}->{to_area} {target_date}: {snippet}"
        )

    # Acknowledgement / no-data documents are still HTTP 200 but small
    if "<Acknowledgement_MarketDocument" in response.text[:500]:
        return []  # no data returned
    return _parse_ntc_xml(response.text)


def daily_stats(points: list[NtcPoint], target_date: date) -> dict | None:
    """Filter to target_date's 24h window in UTC and compute min/mean/max."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Stockholm")
    day_start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    vals = [p.mw for p in points if day_start_utc <= p.timestamp_utc < day_end_utc]
    if not vals:
        return None
    return {
        "n": len(vals),
        "min": min(vals),
        "mean": sum(vals) / len(vals),
        "max": max(vals),
    }


PROBE_DAYS = {
    "worst": [
        date(2026, 3, 31),  # #1 worst, production MAE 0.6233
        date(2026, 2, 6),   # mysterious high-MAE / low-vol
        date(2026, 2, 10),
        date(2026, 2, 19),
        date(2026, 3, 20),
        date(2026, 4, 15),
    ],
    "calm": [
        date(2026, 2, 26),  # best day
        date(2026, 1, 22),
        date(2026, 3, 4),
        date(2026, 4, 18),
        date(2026, 2, 2),
    ],
}


def main() -> int:
    if not API_KEY:
        print("ENTSOE_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    print("Probing ENTSO-E Day-Ahead Forecasted NTC (documentType=A61, contract=A01)")
    print("=" * 92)
    header = f"{'regime':<6} {'date':<12} {'flow':<14} {'n':>3} {'min MW':>10} {'mean MW':>10} {'max MW':>10}"
    print(header)
    print("-" * 92)

    for regime, days in PROBE_DAYS.items():
        for d in days:
            for frm, to in LINKS:
                try:
                    pts = fetch_ntc(frm, to, d)
                except Exception as e:
                    print(f"{regime:<6} {d!s:<12} {frm}->{to:<8}  ERROR  {e}")
                    continue
                stats = daily_stats(pts, d)
                flow = f"{frm}->{to}"
                if stats is None:
                    print(f"{regime:<6} {d!s:<12} {flow:<14} {'—':>3} {'—':>10} {'—':>10} {'—':>10}")
                else:
                    print(
                        f"{regime:<6} {d!s:<12} {flow:<14} {stats['n']:>3} "
                        f"{stats['min']:>10.0f} {stats['mean']:>10.0f} {stats['max']:>10.0f}"
                    )
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
