"""
Generation mix router — ENTSO-E A75 actual generation per production type.

Endpoints:
  GET /api/v1/generation/today   — today's generation mix with renewable % badge
  GET /api/v1/generation/date    — generation mix for an arbitrary date (DB only)
"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.hydro_reservoir import HydroReservoir
from app.services.entsoe_client import EntsoEError
from app.services.generation_service import (
    build_generation_summary,
    fetch_and_store_generation,
    get_generation_for_date,
)

# Shared SQL fragment: ENTSO-E psr_type -> Unagi semantic group.
# Kept as raw SQL so /national-24h and /history can do the national aggregation
# in Postgres (summing zones per slot, averaging slots per bucket) without
# pulling hundreds of thousands of rows into Python.
_PSR_TO_GROUP_SQL = """
    CASE psr_type
        WHEN 'B04' THEN 'fossil'
        WHEN 'B05' THEN 'fossil'
        WHEN 'B10' THEN 'hydro'
        WHEN 'B11' THEN 'hydro'
        WHEN 'B12' THEN 'hydro'
        WHEN 'B14' THEN 'nuclear'
        WHEN 'B16' THEN 'solar'
        WHEN 'B18' THEN 'wind'
        WHEN 'B19' THEN 'wind'
        ELSE 'other'
    END
"""

router = APIRouter(prefix="/generation", tags=["generation"])

DbDep = Annotated[Session, Depends(get_db)]

VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}
AreaDep = Annotated[
    str,
    Query(description="Bidding area (SE1–SE4)"),
]

# ---------------------------------------------------------------------------
# In-memory cache (survives between Lambda warm invocations)
# ---------------------------------------------------------------------------
_CACHE_TTL = 45 * 60  # seconds — matches the staleness threshold
_generation_cache: dict[tuple[str, str], tuple[dict, float]] = {}


def _get_cached(area: str, date_str: str) -> dict | None:
    key = (area, date_str)
    if key in _generation_cache:
        resp, cached_at = _generation_cache[key]
        if time.time() - cached_at <= _CACHE_TTL:
            return resp
        del _generation_cache[key]
    return None


@router.get("/today")
def get_today_generation(db: DbDep, area: AreaDep = "SE3"):
    """
    Actual generation mix for today (Stockholm calendar day).

    Returns the renewable energy percentage badge (hydro + wind + solar),
    carbon-free percentage (renewable + nuclear), a breakdown by group,
    and an hourly time series.

    Source: ENTSO-E A75 processType=A16 (Realised). Data lags ~15-30 min.
    If today's data is not yet in DB, attempts a live fetch.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    today = datetime.now(tz=timezone.utc).date()
    today_str = today.isoformat()

    # Fast path: return cached response if still fresh
    cached = _get_cached(area, today_str)
    if cached is not None:
        return cached

    rows = get_generation_for_date(db, today, area)

    # Re-fetch if no data or the latest slot is older than 45 min.
    # A75 data updates every 15 min with ~15-30 min ENTSO-E lag.
    # The scheduler Lambda pre-populates data at 12:30 UTC, so most
    # requests hit the DB cache.  45 min balances freshness vs latency.
    needs_fetch = not rows
    if rows:
        latest_ts = max(r.timestamp_utc for r in rows)
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        stale_seconds = (datetime.now(timezone.utc) - latest_ts).total_seconds()
        needs_fetch = stale_seconds > 45 * 60

    if needs_fetch:
        try:
            rows = fetch_and_store_generation(db, today, area)
        except EntsoEError as exc:
            if rows:
                pass  # stale data is better than nothing
            else:
                # Fallback: try yesterday (data may not be available yet for today)
                yesterday = today - timedelta(days=1)
                try:
                    rows = get_generation_for_date(db, yesterday, area)
                    if not rows:
                        rows = fetch_and_store_generation(db, yesterday, area)
                    today = yesterday  # report the date we actually got data for
                except EntsoEError:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No generation data available: {exc}",
                    )

    summary = build_generation_summary(rows)
    if not summary:
        raise HTTPException(status_code=404, detail="No generation data available")

    response = {
        "area": area,
        "date": today.isoformat(),
        "source": "ENTSO-E A75",
        "note": "renewable = hydro + wind + solar. carbon_free adds nuclear.",
        **summary,
    }

    # Cache the computed response for subsequent requests
    _generation_cache[(area, today.isoformat())] = (response, time.time())

    return response


@router.get("/national-24h")
def get_national_24h(db: DbDep):
    """
    National aggregate generation mix for the last 24 hours, hourly resolution.
    Sums across all SE zones. Returns up to 24 hourly entries sorted chronologically.
    """
    from collections import defaultdict
    from zoneinfo import ZoneInfo

    _STHLM = ZoneInfo("Europe/Stockholm")

    # Query last 48h of data (wide buffer for ENTSO-E lag + overnight gaps).
    # All aggregation happens in Postgres so we only pull one row per
    # (hour, group) back into Python.
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=48)
    sql = text(
        f"""
        WITH slot_zone AS (
            SELECT timestamp_utc, area, {_PSR_TO_GROUP_SQL} AS grp,
                   SUM(value_mw) AS mw
            FROM generation_mix
            WHERE timestamp_utc >= :cutoff
            GROUP BY timestamp_utc, area, grp
        ),
        slot AS (
            SELECT timestamp_utc, grp, SUM(mw) AS national_mw
            FROM slot_zone
            GROUP BY timestamp_utc, grp
        )
        SELECT date_trunc('hour', timestamp_utc) AS hour_ts,
               grp,
               AVG(national_mw) AS avg_mw
        FROM slot
        GROUP BY hour_ts, grp
        ORDER BY hour_ts, grp
        """
    )
    db_rows = db.execute(sql, {"cutoff": cutoff.replace(tzinfo=None)}).mappings().all()

    # Pivot rows -> {hour_ts: {group: mw}}
    per_hour: dict[datetime, dict[str, float]] = defaultdict(dict)
    for r in db_rows:
        ts = r["hour_ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        per_hour[ts][r["grp"]] = float(r["avg_mw"])

    entries = []
    for hour_ts in sorted(per_hour.keys()):
        groups = per_hour[hour_ts]
        entry: dict = {"timestamp_utc": hour_ts.isoformat()}
        local = hour_ts.astimezone(_STHLM)
        entry["hour_label"] = f"{local.hour:02d}:00"
        total = 0.0
        for g in ("hydro", "nuclear", "wind", "solar", "fossil", "other"):
            mw = groups.get(g, 0.0)
            entry[g] = round(mw)
            total += mw
        renewable = entry.get("hydro", 0) + entry.get("wind", 0) + entry.get("solar", 0)
        entry["total_mw"] = round(total)
        entry["renewable_pct"] = round(renewable / total * 100, 1) if total > 0 else None
        entries.append(entry)

    # Take the last 24 data points (count-based)
    # Note: ENTSO-E lag may create a ~3h overnight gap, so 24 points
    # can span slightly more than 24 calendar hours.
    last_24 = entries[-24:] if len(entries) > 24 else entries
    latest_slot = last_24[-1]["timestamp_utc"] if last_24 else None

    # Compute current snapshot from latest entry
    latest = last_24[-1] if last_24 else None
    renewable_pct = latest["renewable_pct"] if latest else None
    carbon_free = (
        (latest.get("hydro", 0) + latest.get("wind", 0) + latest.get("solar", 0) + latest.get("nuclear", 0))
        / latest["total_mw"]
        * 100
        if latest and latest["total_mw"] > 0
        else None
    )

    return {
        "count": len(last_24),
        "latest_slot": latest_slot,
        "renewable_pct": round(renewable_pct, 1) if renewable_pct else None,
        "carbon_free_pct": round(carbon_free, 1) if carbon_free else None,
        "hourly": last_24,
    }


@router.get("/history")
def get_generation_history(
    db: DbDep,
    days: int = Query(7, ge=1, le=365, description="Number of past days"),
):
    """
    Daily aggregated generation mix for all SE zones combined (national).
    All aggregation is done in Postgres: first sum zones per slot, then
    average the slots that fall inside each Stockholm-local day.
    """
    from collections import defaultdict

    from app.utils.timezone import stockholm_midnight_utc

    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days - 1)
    range_start = stockholm_midnight_utc(start)
    range_end = stockholm_midnight_utc(today + timedelta(days=1))

    sql = text(
        f"""
        WITH slot_zone AS (
            SELECT timestamp_utc, area, {_PSR_TO_GROUP_SQL} AS grp,
                   SUM(value_mw) AS mw
            FROM generation_mix
            WHERE timestamp_utc >= :range_start
              AND timestamp_utc <  :range_end
            GROUP BY timestamp_utc, area, grp
        ),
        slot AS (
            SELECT timestamp_utc, grp, SUM(mw) AS national_mw
            FROM slot_zone
            GROUP BY timestamp_utc, grp
        )
        SELECT (timestamp_utc AT TIME ZONE 'Europe/Stockholm')::date AS day,
               grp,
               AVG(national_mw) AS avg_mw
        FROM slot
        GROUP BY day, grp
        ORDER BY day, grp
        """
    )
    db_rows = (
        db.execute(
            sql,
            {
                "range_start": range_start.replace(tzinfo=None),
                "range_end": range_end.replace(tzinfo=None),
            },
        )
        .mappings()
        .all()
    )

    by_date: dict[date, dict[str, float]] = defaultdict(dict)
    for r in db_rows:
        by_date[r["day"]][r["grp"]] = float(r["avg_mw"])

    daily = []
    cur = start
    while cur <= today:
        groups = by_date.get(cur)
        if groups:
            entry: dict = {"date": cur.isoformat()}
            total = 0.0
            for g in ("hydro", "nuclear", "wind", "solar", "fossil", "other"):
                mw = groups.get(g, 0.0)
                entry[g] = round(mw)
                total += mw
            renewable = entry.get("hydro", 0) + entry.get("wind", 0) + entry.get("solar", 0)
            entry["total_mw"] = round(total)
            entry["renewable_pct"] = round(renewable / total * 100, 1) if total > 0 else None
            daily.append(entry)
        cur += timedelta(days=1)

    return {
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "daily": daily,
    }


@router.get("/date")
def get_generation_for_date_endpoint(
    db: DbDep,
    date: date = Query(..., description="Target date (YYYY-MM-DD)"),
    area: AreaDep = "SE3",
):
    """
    Generation mix for an arbitrary date (DB only — no live fetch).
    Use for historical charts.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    rows = get_generation_for_date(db, date, area)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No generation data in DB for {date}")

    summary = build_generation_summary(rows)
    return {
        "area": area,
        "date": date.isoformat(),
        "source": "ENTSO-E A75",
        **summary,
    }


@router.get("/hydro-reservoir")
def get_hydro_reservoir(db: DbDep):
    """
    Latest national hydro reservoir level (GWh) aggregated across SE1–SE4,
    plus week-over-week change. Source: ENTSO-E A72 (weekly, P7D).
    """
    # Only use weeks that have data for all 4 areas so the national total is comparable
    per_week = (
        db.query(HydroReservoir.week_start, func.count(HydroReservoir.area).label("n"))
        .group_by(HydroReservoir.week_start)
        .having(func.count(HydroReservoir.area) >= 4)
        .order_by(HydroReservoir.week_start.desc())
        .limit(2)
        .all()
    )
    if not per_week:
        return {
            "week_start": None,
            "stored_gwh": None,
            "change_gwh": None,
            "change_pct": None,
        }

    latest_week = per_week[0].week_start
    prev_week = per_week[1].week_start if len(per_week) >= 2 else None

    latest_mwh = (
        db.query(func.sum(HydroReservoir.stored_energy_mwh)).filter(HydroReservoir.week_start == latest_week).scalar()
        or 0
    )
    result = {
        "week_start": latest_week.isoformat(),
        "stored_gwh": round(float(latest_mwh) / 1000, 0),
        "change_gwh": None,
        "change_pct": None,
    }
    if prev_week:
        prev_mwh = (
            db.query(func.sum(HydroReservoir.stored_energy_mwh)).filter(HydroReservoir.week_start == prev_week).scalar()
            or 0
        )
        diff = float(latest_mwh) - float(prev_mwh)
        result["change_gwh"] = round(diff / 1000, 0)
        if prev_mwh:
            result["change_pct"] = round(diff / float(prev_mwh) * 100, 1)
    return result
