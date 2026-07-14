"""
Tests for the static JSON forecast export (public v1 feed).

Uses an in-memory SQLite DB with StaticPool, same pattern as test_prices.py.
"""

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.forecast_accuracy import ForecastAccuracy
from app.models.spot_price import SpotPrice
from app.services.forecast_export_service import (
    SCHEMA_VERSION,
    build_forecast_export,
    publish_forecast_exports,
    write_forecast_exports,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

STOCKHOLM = ZoneInfo("Europe/Stockholm")
TODAY = date(2026, 7, 13)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


def _seed_prediction(db, target_date, model_name, area="SE3", base_price=0.50, hours=range(24)):
    for hour in hours:
        # Cheapest hours at 02-04 so cheapest_hours is deterministic
        price = base_price - 0.30 if hour in (2, 3, 4) else base_price + hour * 0.01
        db.add(
            ForecastAccuracy(
                target_date=target_date,
                area=area,
                model_name=model_name,
                hour=hour,
                predicted_sek_kwh=price,
                predicted_low_sek_kwh=price - 0.1,
                predicted_high_sek_kwh=price + 0.1,
            )
        )
    db.commit()


def _actual_price(hour, base=0.80):
    # Cheapest ACTUAL hours at 12-14 — deliberately different from the
    # prediction's 02-04, to prove settled days rank by actuals.
    return base - 0.50 if hour in (12, 13, 14) else base + hour * 0.01


def _seed_spot_day(db, target_date, area="SE3", base=0.80, hours=range(24)):
    """Seed a settled day as 15-min rows (kvartspris), four per local hour."""
    for hour in hours:
        value = _actual_price(hour, base)
        for minute, delta in ((0, -0.02), (15, -0.01), (30, 0.01), (45, 0.02)):
            local = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=STOCKHOLM)
            db.add(
                SpotPrice(
                    area=area,
                    timestamp_utc=local.astimezone(timezone.utc),
                    price_eur_mwh=50.0,
                    price_sek_kwh=value + delta,
                    resolution="PT15M",
                )
            )
    db.commit()


def _seed_scored_history(db, area="SE3"):
    """Past predictions with actuals so the accuracy block has data."""
    for offset in range(1, 4):
        target = TODAY - timedelta(days=offset)
        for hour in range(24):
            db.add(
                ForecastAccuracy(
                    target_date=target,
                    area=area,
                    model_name="lgbm",
                    hour=hour,
                    predicted_sek_kwh=0.50,
                    predicted_low_sek_kwh=0.30,
                    predicted_high_sek_kwh=0.70,
                    actual_sek_kwh=0.55,
                )
            )
    db.commit()


def test_export_structure_and_metadata(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["area"] == "SE3"
    assert doc["unit"] == "SEK/kWh"
    assert doc["timezone"] == "Europe/Stockholm"
    assert "license" in doc and "no warranty" in doc["license"].lower()
    assert len(doc["days"]) == 1

    day = doc["days"][0]
    assert day["horizon_days"] == 1
    assert day["kind"] == "forecast"
    assert len(day["hours"]) == 24
    slot = day["hours"][0]
    # Mid-July Stockholm is CEST (UTC+2)
    assert slot["start"] == "2026-07-14T00:00:00+02:00"
    assert slot["end"] == "2026-07-14T01:00:00+02:00"
    assert slot["low"] < slot["value"] < slot["high"]
    # On a forecast day, forecast repeats value (both ARE the prediction)
    assert slot["forecast"] == slot["value"]


def test_cheapest_hours_precomputed(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    doc = build_forecast_export(db, "SE3", today=TODAY)
    assert doc["days"][0]["cheapest_hours"] == [2, 3, 4]


def test_freshest_horizon_wins_dedup(db):
    target = TODAY + timedelta(days=2)
    _seed_prediction(db, target, "lgbm_d3", base_price=0.90)  # stale (recorded 3 days out)
    _seed_prediction(db, target, "lgbm_d2", base_price=0.50)  # fresher (recorded 2 days out)
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert len(doc["days"]) == 1
    day = doc["days"][0]
    assert day["horizon_days"] == 2
    assert len(day["hours"]) == 24  # 24 slots, not 48 stacked
    # Values must come from the fresher lgbm_d2 seed (base 0.50, not 0.90)
    assert day["hours"][0]["value"] == pytest.approx(0.50)


def test_excludes_past_and_other_areas(db):
    _seed_prediction(db, TODAY - timedelta(days=1), "lgbm")  # yesterday: settled and gone
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm", area="SE1")
    doc = build_forecast_export(db, "SE3", today=TODAY)
    assert doc["days"] == []


def test_today_is_settled_actual(db):
    _seed_spot_day(db, TODAY)
    _seed_prediction(db, TODAY, "lgbm")  # what the model had said yesterday
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert len(doc["days"]) == 1
    day = doc["days"][0]
    assert day["kind"] == "actual"
    assert day["horizon_days"] == 0
    assert day["date"] == TODAY.isoformat()
    # Ranked by ACTUAL prices (12-14), not by the prediction's cheap hours (02-04)
    assert day["cheapest_hours"] == [12, 13, 14]
    assert len(day["hours"]) == 24

    slot = day["hours"][0]
    # value = mean of the four 15-min rows = the hour's base value
    assert slot["value"] == pytest.approx(_actual_price(0), abs=1e-9)
    # forecast/low/high preserve what the model had predicted for that hour
    assert slot["forecast"] == pytest.approx(0.50)
    assert slot["low"] == pytest.approx(0.40)
    assert slot["high"] == pytest.approx(0.60)

    expected_avg = sum(_actual_price(h) for h in range(24)) / 24
    assert day["daily_avg"] == pytest.approx(expected_avg, abs=1e-4)


def test_tomorrow_flips_to_actual_once_settled(db):
    tomorrow = TODAY + timedelta(days=1)
    _seed_prediction(db, tomorrow, "lgbm")
    _seed_prediction(db, TODAY + timedelta(days=2), "lgbm_d2")
    _seed_spot_day(db, tomorrow)  # the ~13:00 CET Nord Pool fetch has landed
    doc = build_forecast_export(db, "SE3", today=TODAY)

    by_date = {d["date"]: d for d in doc["days"]}
    assert by_date[tomorrow.isoformat()]["kind"] == "actual"
    assert by_date[tomorrow.isoformat()]["horizon_days"] == 1
    d2 = by_date[(TODAY + timedelta(days=2)).isoformat()]
    assert d2["kind"] == "forecast"


def test_incomplete_settled_day_stays_forecast(db):
    tomorrow = TODAY + timedelta(days=1)
    _seed_prediction(db, tomorrow, "lgbm")
    _seed_spot_day(db, tomorrow, hours=range(6))  # half-fetched day
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert len(doc["days"]) == 1
    day = doc["days"][0]
    assert day["kind"] == "forecast"
    assert day["hours"][0]["value"] == pytest.approx(0.50)


def test_dst_march_day_counts_as_complete(db):
    # 2026-03-29: spring DST switch, local hour 02 does not exist → 23 hours
    dst_day = date(2026, 3, 29)
    _seed_spot_day(db, dst_day, hours=[h for h in range(24) if h != 2])
    doc = build_forecast_export(db, "SE3", today=dst_day)

    assert len(doc["days"]) == 1
    day = doc["days"][0]
    assert day["kind"] == "actual"
    assert len(day["hours"]) == 23
    # No prediction was seeded — verification fields stay null, value works
    assert day["hours"][0]["forecast"] is None
    assert day["hours"][0]["value"] is not None


def test_accuracy_block(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    _seed_scored_history(db)
    doc = build_forecast_export(db, "SE3", today=TODAY)

    acc = doc["accuracy"]
    assert acc["window_days"] == 28
    assert acc["mae_sek_kwh"] == pytest.approx(0.05)
    assert acc["by_horizon"][0]["horizon_days"] == 1
    # All actuals (0.55) fall inside [0.30, 0.70] → 100% coverage
    assert acc["interval_coverage_pct"] == pytest.approx(100.0)


def test_write_forecast_exports_layout(db, tmp_path):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm", area="SE1")

    written = write_forecast_exports(db, tmp_path, areas=("SE1", "SE3"))

    latest = tmp_path / "v1" / "forecast" / "SE3.json"
    index = tmp_path / "v1" / "index.json"
    assert latest.exists() and index.exists()
    archives = list((tmp_path / "v1" / "archive").glob("*/SE3.json"))
    assert len(archives) == 1
    assert latest in written

    doc = json.loads(latest.read_text())
    assert doc["area"] == "SE3"
    idx = json.loads(index.read_text())
    assert idx["areas"] == {"SE1": "forecast/SE1.json", "SE3": "forecast/SE3.json"}
    # Latest and archive snapshot must be byte-identical (audit trail)
    assert latest.read_text() == archives[0].read_text()


class FakeR2Client:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_publish_uploads_expected_objects(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    fake = FakeR2Client()

    keys = publish_forecast_exports(db, client=fake, bucket="unagi-catch", areas=("SE3",))

    assert keys == [
        "v1/forecast/SE3.json",
        f"v1/archive/{keys[1].split('/')[2]}/SE3.json",
        "v1/index.json",
    ]
    by_key = {c["Key"]: c for c in fake.calls}
    latest = by_key["v1/forecast/SE3.json"]
    assert latest["Bucket"] == "unagi-catch"
    assert latest["ContentType"].startswith("application/json")
    assert "max-age=900" in latest["CacheControl"]
    archive_call = next(c for k, c in by_key.items() if k.startswith("v1/archive/"))
    assert "immutable" in archive_call["CacheControl"]
    # Latest and archive payloads are byte-identical (audit trail)
    assert latest["Body"] == archive_call["Body"]
    assert json.loads(by_key["v1/index.json"]["Body"])["areas"] == {"SE3": "forecast/SE3.json"}


def test_publish_without_archive_skips_snapshots(db):
    # Intraday refreshes (after the 12:30 UTC fetch) must not touch the
    # immutable archive — only the latest files and the index.
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    fake = FakeR2Client()

    keys = publish_forecast_exports(db, client=fake, bucket="unagi-catch", areas=("SE3",), archive=False)

    assert keys == ["v1/forecast/SE3.json", "v1/index.json"]
    assert not any(k.startswith("v1/archive/") for k in keys)


def test_publish_noop_when_unconfigured(db):
    # No client given and settings are empty in tests → no-op, no exception
    assert publish_forecast_exports(db) == []
