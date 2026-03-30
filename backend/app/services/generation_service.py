"""
Generation mix service: orchestrates ENTSO-E A75 fetch → DB UPSERT → read.

Design mirrors balancing_service.py:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent)
- Returns empty list when DB has no rows for a date
- Caller decides whether to fall back to a live fetch
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.generation_mix import GenerationMix
from app.services.entsoe_client import (
    _AREA_TO_EIC,
    PSR_GROUP,
    RENEWABLE_PSR,
    GenerationPoint,
    fetch_generation_mix,
)
from app.utils.timezone import stockholm_midnight_utc

# Direct combustion emission factors (gCO₂/kWh).
# Source: IPCC AR5 WG3 Annex III (direct emissions only).
EMISSION_FACTOR: dict[str, int] = {
    "B04": 410,  # Fossil Gas (CCGT)
    "B05": 910,  # Fossil Hard Coal
    "B06": 740,  # Fossil Oil
    "B11": 0,  # Hydro Run-of-river
    "B12": 0,  # Hydro Water Reservoir
    "B14": 0,  # Nuclear
    "B16": 0,  # Solar PV
    "B17": 330,  # Waste (fossil fraction)
    "B18": 0,  # Wind Offshore
    "B19": 0,  # Wind Onshore
    "B20": 200,  # Other (conservative estimate)
}


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_generation(db: Session, points: list[GenerationPoint], area: str = "SE3") -> int:
    """
    Persist GenerationPoints using INSERT ON CONFLICT DO UPDATE.
    Returns the number of rows written.
    """
    if not points:
        return 0

    stmt = text("""
        INSERT INTO generation_mix
            (area, timestamp_utc, psr_type, value_mw, resolution)
        VALUES (:area, :ts, :psr, :mw, :res)
        ON CONFLICT (area, timestamp_utc, psr_type)
        DO UPDATE SET
            value_mw   = EXCLUDED.value_mw,
            resolution = EXCLUDED.resolution
    """)

    params = [
        {"area": area, "ts": p.timestamp_utc, "psr": p.psr_type, "mw": p.value_mw, "res": p.resolution} for p in points
    ]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_generation_for_date(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[GenerationMix]:
    """
    Fetch generation rows for target_date from DB.
    Window: Stockholm midnight → next Stockholm midnight (handles CET/CEST transitions).
    """
    day_start = stockholm_midnight_utc(target_date)
    day_end = stockholm_midnight_utc(target_date + timedelta(days=1))

    return (
        db.query(GenerationMix)
        .filter(
            GenerationMix.area == area,
            GenerationMix.timestamp_utc >= day_start,
            GenerationMix.timestamp_utc < day_end,
        )
        .order_by(GenerationMix.timestamp_utc, GenerationMix.psr_type)
        .all()
    )


# ---------------------------------------------------------------------------
# Aggregate: build summary from DB rows
# ---------------------------------------------------------------------------


def build_generation_summary(rows: list[GenerationMix]) -> dict:
    """
    From a list of GenerationMix rows, compute:
    - latest_slot: timestamp of the most recent data point
    - breakdown: {group: total_mw} for the latest slot
    - renewable_pct, carbon_free_pct (nuclear counted as carbon-free but not renewable)
    - time_series: list of {timestamp, breakdown} per slot
    """
    if not rows:
        return {}

    # Group rows by timestamp slot
    from collections import defaultdict

    by_slot: dict[datetime, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_slot[r.timestamp_utc][r.psr_type] = float(r.value_mw)

    # Latest slot
    latest_ts = max(by_slot.keys())
    latest = by_slot[latest_ts]

    # Aggregate into groups for latest slot
    group_mw: dict[str, float] = defaultdict(float)
    for psr_type, mw in latest.items():
        group = PSR_GROUP.get(psr_type, "other")
        group_mw[group] += mw

    total_mw = sum(group_mw.values())

    renewable_mw = sum(mw for psr, mw in latest.items() if psr in RENEWABLE_PSR)
    nuclear_mw = latest.get("B14", 0.0)
    carbon_free_mw = renewable_mw + nuclear_mw

    renewable_pct = round(renewable_mw / total_mw * 100, 1) if total_mw else None
    carbon_free_pct = round(carbon_free_mw / total_mw * 100, 1) if total_mw else None

    # Carbon intensity for latest slot (weighted average of PSR-level emission factors)
    latest_emissions = sum(mw * EMISSION_FACTOR.get(psr, 200) for psr, mw in latest.items())
    carbon_intensity = round(latest_emissions / total_mw, 1) if total_mw else None

    # Build time series (hourly buckets to keep response small)
    # One entry per UTC hour: average of the 4 quarterly slots within that hour
    hour_buckets: dict[datetime, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    hour_ci: dict[datetime, list[float]] = defaultdict(list)
    for ts, psr_dict in sorted(by_slot.items()):
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        for psr_type, mw in psr_dict.items():
            group = PSR_GROUP.get(psr_type, "other")
            hour_buckets[hour_ts][group].append(mw)
        # Per-slot carbon intensity → averaged into hourly buckets
        slot_total = sum(psr_dict.values())
        if slot_total > 0:
            slot_ci = sum(mw * EMISSION_FACTOR.get(psr, 200) for psr, mw in psr_dict.items()) / slot_total
            hour_ci[hour_ts].append(slot_ci)

    time_series = []
    for hour_ts in sorted(hour_buckets.keys()):
        bucket = hour_buckets[hour_ts]
        hour_totals = {g: round(sum(vals) / len(vals), 1) for g, vals in bucket.items()}
        hour_total = sum(hour_totals.values())
        hour_ren = sum(v for g, v in hour_totals.items() if g in ("hydro", "wind", "solar"))
        ci_vals = hour_ci.get(hour_ts)
        time_series.append(
            {
                "timestamp_utc": hour_ts.isoformat(),
                "total_mw": round(hour_total, 1),
                "renewable_pct": round(hour_ren / hour_total * 100, 1) if hour_total else None,
                "carbon_intensity": round(sum(ci_vals) / len(ci_vals), 1) if ci_vals else None,
                **hour_totals,
            }
        )

    # Ensure timezone-aware ISO string so JavaScript parses as UTC, not local time.
    # psycopg2 may return naive datetimes for TIMESTAMPTZ depending on driver config.
    def _utc_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    return {
        "latest_slot": _utc_iso(latest_ts),
        "total_mw": round(total_mw, 1),
        "renewable_pct": renewable_pct,
        "carbon_free_pct": carbon_free_pct,
        "carbon_intensity": carbon_intensity,
        "breakdown": {k: round(v, 1) for k, v in group_mw.items()},
        "time_series": time_series,
    }


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------


def fetch_and_store_generation(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[GenerationMix]:
    """
    Pull A75 generation mix from ENTSO-E and persist. Returns stored rows.
    Raises EntsoEError if the API call or parse fails.
    """
    eic_code = _AREA_TO_EIC.get(area, area)
    points = fetch_generation_mix(
        target_date=target_date,
        area=eic_code,
        api_key=settings.entsoe_api_key,
    )
    upsert_generation(db, points, area=area)
    return get_generation_for_date(db, target_date, area=area)
