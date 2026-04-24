"""
90-day correlation: ENTSO-E physical flows (A11) vs daily LightGBM MAE.

For each day D with a production LightGBM forecast:
  - Fetch actual hourly physical flow on D-1 for each link (A11)
  - Compute daily stats: max, mean, 90th percentile, saturation hours
  - Correlate against D's daily MAE

Two research questions:
  Q1: do the worst-MAE days have high flow (congestion) on the preceding day?
  Q2: is the signal strong enough to justify feature-engineering + backfill
      of flow data for the ML pipeline?

Output: Pearson / Spearman correlations for each link stat, plus an
optional per-day dump to CSV.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from sqlalchemy import text

from app.config import settings
from app.db.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("flow_vs_mae")

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
API_KEY = settings.entsoe_api_key or os.getenv("ENTSOE_API_KEY")

AREAS = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "NO1": "10YNO-1--------2",
    "FI": "10YFI-1--------U",
    "SE1_SE2": None,  # placeholder
}

# Import-side and export-side links for SE3.
LINKS = [
    ("SE2", "SE3"),
    ("NO1", "SE3"),
    ("FI", "SE3"),
    ("SE3", "SE4"),
    ("SE1", "SE2"),  # upstream signal (affects what SE2 can push)
]


@dataclass
class FlowPoint:
    timestamp_utc: datetime
    mw: float


def _period_param(dt: date) -> str:
    return dt.strftime("%Y%m%d") + "2200"


def _strip_namespaces(xml_text: str) -> str:
    return re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)


def _parse_resolution(r: str) -> timedelta:
    return {
        "PT60M": timedelta(hours=1),
        "PT30M": timedelta(minutes=30),
        "PT15M": timedelta(minutes=15),
    }[r]


def _parse_flow_xml(xml_text: str) -> list[FlowPoint]:
    if "<Acknowledgement_MarketDocument" in xml_text[:500]:
        return []
    root = ET.fromstring(_strip_namespaces(xml_text))
    pts: list[FlowPoint] = []
    for period in root.findall(".//Period"):
        start = datetime.fromisoformat(
            period.find("timeInterval/start").text.replace("Z", "+00:00")
        )
        res = _parse_resolution(period.find("resolution").text)
        for p in period.findall("Point"):
            pos = int(p.find("position").text)
            qty = float(p.find("quantity").text)
            pts.append(FlowPoint(timestamp_utc=start + res * (pos - 1), mw=qty))
    pts.sort(key=lambda x: x.timestamp_utc)
    return pts


def fetch_flow(
    client: httpx.Client, from_area: str, to_area: str, target_date: date
) -> list[FlowPoint]:
    params = {
        "securityToken": API_KEY,
        "documentType": "A11",
        "in_Domain": AREAS[to_area],
        "out_Domain": AREAS[from_area],
        "periodStart": _period_param(target_date - timedelta(days=1)),
        "periodEnd": _period_param(target_date + timedelta(days=1)),
    }
    r = client.get(ENTSOE_BASE, params=params, timeout=30.0)
    if r.status_code != 200:
        return []
    return _parse_flow_xml(r.text)


def filter_to_day(points: list[FlowPoint], target_date: date) -> list[FlowPoint]:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Stockholm")
    day_start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    ds = day_start_local.astimezone(timezone.utc)
    de = day_end_local.astimezone(timezone.utc)
    return [p for p in points if ds <= p.timestamp_utc < de]


def daily_stats(points: list[FlowPoint]) -> Optional[dict]:
    if not points:
        return None
    vals = np.array([p.mw for p in points])
    return {
        "n": len(vals),
        "max": float(vals.max()),
        "mean": float(vals.mean()),
        "p90": float(np.percentile(vals, 90)),
        "saturation_share": float((vals >= vals.max() * 0.95).mean()) if vals.max() > 0 else 0.0,
    }


def production_mae(db, days: int, area: str) -> dict[date, float]:
    end = date.today()
    start = end - timedelta(days=days)
    rows = db.execute(
        text(
            """
            SELECT target_date, hour, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"area": area, "start": start, "end": end},
    ).fetchall()
    by_day = defaultdict(list)
    for d, _, p, a in rows:
        by_day[d].append(abs(float(p) - float(a)))
    return {d: float(np.mean(errs)) for d, errs in by_day.items()}


def correlation(x, y):
    if len(x) < 3:
        return 0.0, 0.0
    xa, ya = np.array(x), np.array(y)
    pearson = float(np.corrcoef(xa, ya)[0, 1])
    xr = np.argsort(np.argsort(xa))
    yr = np.argsort(np.argsort(ya))
    spearman = float(np.corrcoef(xr, yr)[0, 1])
    return pearson, spearman


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--csv-out", default=None)
    args = parser.parse_args()

    if not API_KEY:
        raise SystemExit("ENTSOE_API_KEY not set")

    db = SessionLocal()
    try:
        mae = production_mae(db, args.days, args.area)
    finally:
        db.close()
    if not mae:
        log.error("no MAE data")
        return 1
    target_days = sorted(mae.keys())
    log.info("loaded %d MAE days, %s .. %s", len(target_days), target_days[0], target_days[-1])

    # Flow features use D-1 flow data (available at D-1 morning for D prediction).
    # For each target day D, we fetch flow on D-1.
    per_day: dict[date, dict[str, dict]] = {}

    with httpx.Client() as client:
        for i, d in enumerate(target_days, 1):
            flow_date = d - timedelta(days=1)
            day_features = {}
            for frm, to in LINKS:
                pts = fetch_flow(client, frm, to, flow_date)
                pts = filter_to_day(pts, flow_date)
                s = daily_stats(pts)
                if s:
                    day_features[f"{frm}_{to}"] = s
            per_day[d] = day_features
            if i % 10 == 0:
                log.info("... %d/%d", i, len(target_days))

    # Aggregate correlations
    print()
    print("=" * 84)
    print(f"  FLOW (A11 at D-1) vs DAILY MAE at D — area={args.area}, {len(target_days)} days")
    print("=" * 84)
    print(f"  {'Link':<12} {'Stat':<10} {'N':>4} {'Pearson':>10} {'Spearman':>10}")
    print("-" * 84)
    for frm, to in LINKS:
        key = f"{frm}_{to}"
        for stat in ("max", "mean", "p90", "saturation_share"):
            xs, ys = [], []
            for d in target_days:
                if key in per_day[d]:
                    xs.append(per_day[d][key][stat])
                    ys.append(mae[d])
            pearson, spearman = correlation(xs, ys)
            print(f"  {key:<12} {stat:<10} {len(xs):>4} {pearson:>10.3f} {spearman:>10.3f}")
        print()

    # Optional CSV dump
    if args.csv_out:
        path = Path(args.csv_out)
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            header = ["date", "mae"]
            for frm, to in LINKS:
                for stat in ("max", "mean", "p90", "saturation_share"):
                    header.append(f"{frm}_{to}_{stat}")
            writer.writerow(header)
            for d in target_days:
                row = [d.isoformat(), mae[d]]
                for frm, to in LINKS:
                    key = f"{frm}_{to}"
                    for stat in ("max", "mean", "p90", "saturation_share"):
                        row.append(per_day[d].get(key, {}).get(stat, ""))
                writer.writerow(row)
        log.info("wrote %s", path)

    # Top-10 MAE days — show their flow features
    top = sorted(target_days, key=lambda d: mae[d], reverse=True)[:10]
    print("  Top 10 MAE days (with SE2->SE3 and SE3->SE4 stats for D-1):")
    print(f"  {'Date':<12} {'MAE':>7}  {'SE2→SE3 max':>14}  {'SE2→SE3 mean':>14}  {'SE3→SE4 max':>14}")
    for d in top:
        feats = per_day[d]
        se2_3 = feats.get("SE2_SE3", {})
        se3_4 = feats.get("SE3_SE4", {})
        print(
            f"  {d!s:<12} {mae[d]:>7.4f}  "
            f"{se2_3.get('max', '—'):>14}  "
            f"{se2_3.get('mean', '—'):>14}  "
            f"{se3_4.get('max', '—'):>14}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
