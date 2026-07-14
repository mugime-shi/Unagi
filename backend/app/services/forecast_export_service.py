"""
Static JSON export of the public forecast feed.

Builds one self-describing JSON document per bidding zone, intended to be
published as static files behind a CDN (no server, no auth). Consumers:
Home Assistant REST sensors, scripts, AI agents.

Schema stability contract (v1): fields are only ever ADDED within a schema
version — never renamed, removed, or re-typed. Breaking changes require a
new /v2/ path.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.forecast_accuracy import ForecastAccuracy
from app.services.backtest_service import get_accuracy, get_coverage_rate

STOCKHOLM = ZoneInfo("Europe/Stockholm")
SCHEMA_VERSION = 1
EXPORT_AREAS = ("SE1", "SE2", "SE3", "SE4")
ACCURACY_WINDOW_DAYS = 28
N_CHEAPEST_HOURS = 3

# model_name → forecast horizon in days (lower horizon = fresher prediction)
_MODEL_HORIZONS = {"lgbm": 1, **{f"lgbm_d{h}": h for h in range(2, 8)}}

_LICENSE = (
    "Free for personal, non-commercial use with attribution: Unagi — unagieel.net. "
    "Commercial use requires permission (hello@unagieel.net). "
    "Forecasts are estimates provided as-is, with no warranty. Not financial or trading advice."
)


def _slot_times(target_date: date, hour: int) -> tuple[str, str]:
    """ISO8601 start/end (with Stockholm UTC offset) for a local-hour slot."""
    start = datetime(target_date.year, target_date.month, target_date.day, hour, tzinfo=STOCKHOLM)
    end = start + timedelta(hours=1)
    return start.isoformat(), end.isoformat()


def _freshest_predictions(db: Session, area: str, today: date) -> dict[date, list[ForecastAccuracy]]:
    """
    Future predictions grouped by target_date, deduplicated per (date, hour)
    to the lowest-horizon (= freshest) model row.

    Dedup happens in Python so the query stays portable to SQLite (tests).
    Row count is bounded (7 days × 24 h × 7 models), so this is cheap.
    """
    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.area == area,
            ForecastAccuracy.model_name.in_(_MODEL_HORIZONS.keys()),
            ForecastAccuracy.target_date > today,
            ForecastAccuracy.target_date <= today + timedelta(days=7),
        )
        .all()
    )

    best: dict[tuple[date, int], ForecastAccuracy] = {}
    for row in rows:
        key = (row.target_date, row.hour)
        current = best.get(key)
        if current is None or _MODEL_HORIZONS[row.model_name] < _MODEL_HORIZONS[current.model_name]:
            best[key] = row

    by_date: dict[date, list[ForecastAccuracy]] = {}
    for row in best.values():
        by_date.setdefault(row.target_date, []).append(row)
    for slots in by_date.values():
        slots.sort(key=lambda r: r.hour)
    return by_date


def _build_accuracy_block(db: Session, area: str) -> dict:
    """Live accuracy summary so the file itself says how much to trust it."""
    models = get_accuracy(db, area, days=ACCURACY_WINDOW_DAYS)
    coverage = get_coverage_rate(db, area, days=ACCURACY_WINDOW_DAYS)

    by_horizon = []
    for model_name, horizon in sorted(_MODEL_HORIZONS.items(), key=lambda kv: kv[1]):
        stats = models.get(model_name)
        if stats:
            by_horizon.append(
                {
                    "horizon_days": horizon,
                    "mae_sek_kwh": stats["mae_sek_kwh"],
                    "n_days": stats["n_days"],
                }
            )

    baseline = models.get("same_weekday_avg")
    return {
        "window_days": ACCURACY_WINDOW_DAYS,
        "mae_sek_kwh": models.get("lgbm", {}).get("mae_sek_kwh"),
        "baseline_mae_sek_kwh": baseline["mae_sek_kwh"] if baseline else None,
        "interval_coverage_pct": coverage.get("coverage_pct"),
        "interval_expected_pct": coverage.get("expected_pct"),
        "by_horizon": by_horizon,
    }


def build_forecast_export(db: Session, area: str = "SE3", today: date | None = None) -> dict:
    """Build the public v1 forecast document for one bidding zone."""
    today = today or datetime.now(tz=STOCKHOLM).date()
    by_date = _freshest_predictions(db, area, today)

    days = []
    for target_date in sorted(by_date.keys()):
        slots = by_date[target_date]
        hours = []
        for row in slots:
            start, end = _slot_times(target_date, row.hour)
            hours.append(
                {
                    "start": start,
                    "end": end,
                    "value": float(row.predicted_sek_kwh),
                    "low": float(row.predicted_low_sek_kwh) if row.predicted_low_sek_kwh is not None else None,
                    "high": float(row.predicted_high_sek_kwh) if row.predicted_high_sek_kwh is not None else None,
                }
            )

        values = [(float(r.predicted_sek_kwh), r.hour) for r in slots]
        cheapest = sorted(h for _, h in sorted(values)[:N_CHEAPEST_HOURS])
        horizon = min(_MODEL_HORIZONS[r.model_name] for r in slots)

        days.append(
            {
                "date": target_date.isoformat(),
                "horizon_days": horizon,
                "daily_avg": round(sum(v for v, _ in values) / len(values), 4),
                "cheapest_hours": cheapest,
                "hours": hours,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "area": area,
        "unit": "SEK/kWh",
        "price_basis": "Nord Pool day-ahead spot price, excl. VAT, grid fees and retailer markup",
        "timezone": "Europe/Stockholm",
        "resolution": "PT1H",
        "days": days,
        "accuracy": _build_accuracy_block(db, area),
        "links": {
            "dashboard": "https://unagieel.net",
            "feedback": "hello@unagieel.net",
        },
        "license": _LICENSE,
    }


def write_forecast_exports(
    db: Session,
    out_dir: str | Path,
    areas: tuple[str, ...] = EXPORT_AREAS,
    archive: bool = True,
) -> list[Path]:
    """
    Write v1 forecast files for all areas plus an index.

    Layout:
        <out>/v1/forecast/SE3.json          — latest, overwritten each run
        <out>/v1/archive/<date>/SE3.json    — frozen daily snapshot (audit trail)
        <out>/v1/index.json                 — area list + generated_at
    """
    out = Path(out_dir)
    written: list[Path] = []
    stamp_date = datetime.now(tz=STOCKHOLM).date().isoformat()

    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "areas": {},
        "license": _LICENSE,
    }

    for area in areas:
        doc = build_forecast_export(db, area)
        payload = json.dumps(doc, indent=1, ensure_ascii=False)

        latest = out / "v1" / "forecast" / f"{area}.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(payload)
        written.append(latest)

        if archive:
            snapshot = out / "v1" / "archive" / stamp_date / f"{area}.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(payload)
            written.append(snapshot)

        index["areas"][area] = f"forecast/{area}.json"

    index_path = out / "v1" / "index.json"
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False))
    written.append(index_path)
    return written


# ── R2 publishing (catch.unagieel.net) ───────────────────────────────────────

_CACHE_LATEST = "public, max-age=900"  # feed refreshes a few times per day
_CACHE_ARCHIVE = "public, max-age=31536000, immutable"  # frozen snapshots never change


def _make_r2_client():
    """S3-compatible client for Cloudflare R2. Lazy import keeps boto3 optional locally."""
    import boto3

    from app.config import settings

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def publish_forecast_exports(
    db: Session,
    client=None,
    bucket: str | None = None,
    areas: tuple[str, ...] = EXPORT_AREAS,
    archive: bool = True,
) -> list[str]:
    """
    Build and upload the v1 feed to R2. Returns the uploaded object keys.

    No-op (returns []) when R2 is not configured, so the daily task can call
    this unconditionally in every environment.
    """
    if client is None:
        from app.config import settings

        if not (settings.r2_endpoint and settings.r2_bucket and settings.r2_access_key_id):
            return []
        bucket = settings.r2_bucket
        client = _make_r2_client()

    def _put(key: str, payload: str, cache_control: str) -> None:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            CacheControl=cache_control,
        )

    stamp_date = datetime.now(tz=STOCKHOLM).date().isoformat()
    uploaded: list[str] = []

    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "areas": {},
        "license": _LICENSE,
    }

    for area in areas:
        payload = json.dumps(build_forecast_export(db, area), indent=1, ensure_ascii=False)

        latest_key = f"v1/forecast/{area}.json"
        _put(latest_key, payload, _CACHE_LATEST)
        uploaded.append(latest_key)

        if archive:
            snapshot_key = f"v1/archive/{stamp_date}/{area}.json"
            _put(snapshot_key, payload, _CACHE_ARCHIVE)
            uploaded.append(snapshot_key)

        index["areas"][area] = f"forecast/{area}.json"

    index_key = "v1/index.json"
    _put(index_key, json.dumps(index, indent=1, ensure_ascii=False), _CACHE_LATEST)
    uploaded.append(index_key)
    return uploaded
