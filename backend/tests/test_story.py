"""
Tests for the today-story rules, rotation and GET /api/v1/story/today.
"""

import math
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.forecast_accuracy import ForecastAccuracy
from app.models.generation_mix import GenerationMix
from app.models.spot_price import SpotPrice
from app.routers import story as story_router
from app.services.story_service import Candidate, StoryData, candidates_for, load_story_data, replay_headlines
from app.utils.timezone import STOCKHOLM, stockholm_midnight_utc

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

D = date(2026, 1, 20)  # winter day, Stockholm = UTC+1


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    story_router._story_cache.clear()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── seeding helpers ──────────────────────────────────────────────────────────


def seed_day(db, area, day, prices, resolution="PT60M"):
    """Insert consecutive slots (SEK/kWh) starting at Stockholm midnight of `day`."""
    step = timedelta(minutes=15 if resolution == "PT15M" else 60)
    start = stockholm_midnight_utc(day)
    for i, p in enumerate(prices):
        db.add(
            SpotPrice(
                area=area,
                timestamp_utc=start + i * step,
                price_eur_mwh=0,
                price_sek_kwh=p,
                resolution=resolution,
            )
        )
    db.commit()


def day_hours(d):
    return round((stockholm_midnight_utc(d + timedelta(days=1)) - stockholm_midnight_utc(d)).total_seconds() / 3600)


def seed_flat(db, area, first, last, price):
    d = first
    while d <= last:
        seed_day(db, area, d, [price] * 24)
        d += timedelta(days=1)


def seed_history(db, area, day, n, fn):
    """n days before `day`; fn(k) -> flat price for the day k days back."""
    for k in range(1, n + 1):
        d = day - timedelta(days=k)
        seed_day(db, area, d, [fn(k)] * day_hours(d))


def kinds(db, day=D, today=None):
    data = load_story_data(db, day, day)
    return {c.kind: c for c in candidates_for(data, day, today or day)}


# ── negative ─────────────────────────────────────────────────────────────────


def add_slot(db, area, ts, price, resolution="PT60M"):
    db.add(
        SpotPrice(
            area=area,
            timestamp_utc=ts,
            price_eur_mwh=0,
            price_sek_kwh=price,
            resolution=resolution,
        )
    )


def test_negative_needs_60_minutes(db):
    prices = [0.3] * 96
    prices[40:43] = [-0.01] * 3  # 45 minutes
    seed_day(db, "SE2", D, prices, "PT15M")
    assert "negative" not in kinds(db)

    db.query(SpotPrice).delete()
    prices[43] = -0.01  # 60 minutes
    seed_day(db, "SE3", D, prices, "PT15M")
    c = kinds(db)["negative"]
    assert c.text == "Prices dip below zero for 1 hour in SE3"
    assert c.score == pytest.approx(49)


def test_negative_counts_mixed_resolutions_and_lists_other_zones(db):
    # SE2: 2h of PT60M + 1h of PT15M negative = 3 hours; SE1 also negative
    start = stockholm_midnight_utc(D)
    for h in (0, 1):
        add_slot(db, "SE2", start + timedelta(hours=h), -0.1)
    for q in range(4):
        add_slot(db, "SE2", start + timedelta(hours=2, minutes=15 * q), -0.1, "PT15M")
    add_slot(db, "SE2", start + timedelta(hours=3), 0.2)
    add_slot(db, "SE1", start, -0.1)
    db.commit()
    c = kinds(db)["negative"]
    assert c.text == "Prices dip below zero for 3 hours in SE2"
    assert c.score == pytest.approx((45 + 4 * 3) * 0.85)  # SE2 area weight
    assert c.sub.endswith("Also negative in SE1.")


def test_negative_hours_on_dst_days(db):
    spring = date(2026, 3, 29)  # 23-hour day
    autumn = date(2026, 10, 25)  # 25-hour day
    seed_day(db, "SE4", spring, [-0.1] * 23)
    seed_day(db, "SE4", autumn, [-0.1] * 25)
    data = load_story_data(db, autumn, autumn)
    assert data.prices["SE4"][spring].neg_minutes == 23 * 60
    assert data.prices["SE4"][autumn].neg_minutes == 25 * 60
    # (a 25-hour day is also the cheapest in months, so look the kind up rather than take the top)
    assert {c.kind: c for c in candidates_for(data, spring, spring)}["negative"].text == (
        "Prices dip below zero for 23 hours in SE4"
    )
    assert {c.kind: c for c in candidates_for(data, autumn, autumn)}["negative"].text == (
        "Prices dip below zero for 25 hours in SE4"
    )


# ── low / high ───────────────────────────────────────────────────────────────


def test_low_needs_14_days_of_window(db):
    seed_history(db, "SE3", D, 13, lambda k: 0.5)
    seed_day(db, "SE3", D, [0.1] * 24)
    assert "low" not in kinds(db)

    seed_day(db, "SE3", D - timedelta(days=14), [0.5] * 24)
    c = kinds(db)["low"]
    assert c.text == "SE3's cheapest day in 14 days"
    assert c.score == pytest.approx(40)


def test_low_since_date_and_sub(db):
    blocker = D - timedelta(days=40)
    seed_history(db, "SE3", D, 60, lambda k: 0.05 if k == 40 else 0.5)
    seed_day(db, "SE3", D, [0.12] * 24)
    c = kinds(db)["low"]
    assert c.text == f"SE3's cheapest day since {blocker.day} {blocker:%B}"
    assert c.sub == "Averaging 12 öre/kWh, against 50 over the past 30 days."
    assert c.score == pytest.approx(40 + 15 * math.log2(40 / 14))


def test_high_and_over_a_year(db):
    seed_history(db, "SE3", D, 365, lambda k: 0.5)
    seed_day(db, "SE3", D, [2.0] * 24)
    c = kinds(db)["high"]
    assert c.text == "SE3's priciest day in over a year"
    assert c.score == 100


def test_low_not_fired_when_not_lowest(db):
    seed_history(db, "SE3", D, 40, lambda k: 0.1 if k == 5 else 0.5)
    seed_day(db, "SE3", D, [0.2] * 24)  # beaten 5 days ago -> N=5 < 14
    assert "low" not in kinds(db)


# ── spread ───────────────────────────────────────────────────────────────────


def _seed_spread(db, today_diff):
    for k in range(1, 41):
        d = D - timedelta(days=k)
        seed_day(db, "SE1", d, [0.1] * 24)
        seed_day(db, "SE4", d, [0.35 + 0.001 * k] * 24)
    seed_day(db, "SE1", D, [0.12] * 24)
    seed_day(db, "SE4", D, [0.12 + today_diff] * 24)


def test_spread_fires_above_p90_and_20_ore(db):
    _seed_spread(db, 0.85)
    c = kinds(db)["spread"]
    assert c.text == "Southern Sweden pays 85 öre more than the north"
    assert c.sub == "SE4 averages 97 öre/kWh, SE1 just 12 — the grid between them is congested."
    assert c.score == pytest.approx(80)


def test_spread_not_fired_inside_history_or_below_20_ore(db):
    _seed_spread(db, 0.25 + 0.02)  # middle of history (0.25..0.29 diffs)
    assert "spread" not in kinds(db)


def test_spread_needs_20_ore_even_when_extreme(db):
    for k in range(1, 41):
        d = D - timedelta(days=k)
        seed_day(db, "SE1", d, [0.1] * 24)
        seed_day(db, "SE4", d, [0.1 + 0.0005 * k] * 24)
    seed_day(db, "SE1", D, [0.1] * 24)
    seed_day(db, "SE4", D, [0.29] * 24)  # above every history day, but 19 öre
    assert "spread" not in kinds(db)


# ── coupled ──────────────────────────────────────────────────────────────────


def _seed_coupled(db, coupled_history_days):
    for k in range(1, 41):
        d = D - timedelta(days=k)
        for i, a in enumerate(("SE1", "SE2", "SE3", "SE4")):
            seed_day(db, a, d, [0.4 if k <= coupled_history_days else 0.1 * (i + 1)] * 24)
    for a in ("SE1", "SE2", "SE3", "SE4"):
        seed_day(db, a, D, [0.41] * 24)


def test_coupled_fires_when_rare(db):
    _seed_coupled(db, 11)  # 27.5% of history coupled
    c = kinds(db)["coupled"]
    assert c.text == "One price for all of Sweden today"
    assert c.sub == "All four zones average 41 öre/kWh — no bottleneck on the grid."
    assert c.score == 35


def test_coupled_not_fired_when_common(db):
    _seed_coupled(db, 12)  # exactly 30% of history coupled
    assert "coupled" not in kinds(db)


def test_coupled_not_fired_when_zones_differ_by_1_ore(db):
    _seed_coupled(db, 11)
    assert "coupled" in kinds(db)
    db.query(SpotPrice).filter(SpotPrice.area == "SE4", SpotPrice.timestamp_utc >= stockholm_midnight_utc(D)).delete()
    seed_day(db, "SE4", D, [0.42] * 24)  # 1 öre apart
    assert "coupled" not in kinds(db)


# ── swing ────────────────────────────────────────────────────────────────────


def _seed_swing(db, today_profile):
    for k in range(1, 41):
        seed_day(db, "SE4", D - timedelta(days=k), [0.1] * 12 + [0.5 + 0.005 * k] * 12)
    seed_day(db, "SE4", D, today_profile)


def test_swing_fires_with_times(db):
    profile = [0.5] * 24
    profile[3], profile[17] = 0.08, 1.88
    _seed_swing(db, profile)
    c = kinds(db)["swing"]
    assert c.text == "SE4 swings 180 öre today"
    assert c.sub == "From 8 öre at 03:00 to 188 at 17:00."
    assert c.score == pytest.approx(45 + 2 * 10)  # beats every history day -> mid-rank 100 minus tie handling


def test_swing_not_fired_for_typical_range(db):
    _seed_swing(db, [0.1] * 12 + [0.5 + 0.005 * 20] * 12)
    assert "swing" not in kinds(db)


# ── wind ─────────────────────────────────────────────────────────────────────


def seed_gen(db, day, wind, other, slots=24):
    start = stockholm_midnight_utc(day)
    for i in range(slots):
        ts = start + timedelta(hours=i)
        db.add(GenerationMix(area="SE3", timestamp_utc=ts, psr_type="B19", value_mw=wind))
        db.add(GenerationMix(area="SE3", timestamp_utc=ts, psr_type="B14", value_mw=other))
    db.commit()


def _seed_wind(db, today_wind, slots=24):
    for k in range(1, 13):
        seed_gen(db, D - timedelta(days=k), 20, 80)  # 20% usual
    seed_gen(db, D, today_wind, 100 - today_wind, slots)


def test_wind_high_and_low(db):
    _seed_wind(db, 40)
    c = kinds(db, today=D + timedelta(days=1))["wind"]
    assert c.text == "Wind supplies 40% of Sweden's power, twice the usual"
    assert c.score == pytest.approx(80)
    assert c.sub is None


def test_wind_low_and_today_suffix(db):
    _seed_wind(db, 8)
    c = kinds(db, today=D)["wind"]
    assert c.text == "Wind falls quiet: 8% of generation vs 20% usual"
    assert c.sub == "So far today."


def test_wind_not_fired_inside_band_or_too_few_slots(db):
    _seed_wind(db, 25)  # ratio 1.25
    assert "wind" not in kinds(db)
    db.query(GenerationMix).filter(GenerationMix.timestamp_utc >= stockholm_midnight_utc(D)).delete()
    db.commit()
    seed_gen(db, D, 40, 60, slots=15)
    assert "wind" not in kinds(db)


# ── forecast ─────────────────────────────────────────────────────────────────


def _seed_forecast(db, today_err, base=0.05):
    for k in range(0, 21):
        d = D - timedelta(days=k)
        seed_day(db, "SE3", d, [0.5] * 24)
        err = today_err if k == 0 else base + 0.01 * k
        for h in range(24):
            db.add(
                ForecastAccuracy(
                    target_date=d,
                    area="SE3",
                    model_name="lgbm",
                    hour=h,
                    predicted_sek_kwh=0.5 + err,
                )
            )
    db.commit()


def test_forecast_good_and_miss(db):
    _seed_forecast(db, 0.03)
    assert kinds(db)["forecast"].text == "Our SE3 forecast nailed today: within 3 öre on average"
    assert kinds(db)["forecast"].score == 35

    db.query(ForecastAccuracy).delete()
    db.query(SpotPrice).delete()
    db.commit()
    _seed_forecast(db, 0.41)
    c = kinds(db)["forecast"]
    assert c.text == "Today caught our SE3 forecast off guard: off by 41 öre per hour"
    assert c.score == 45


def test_forecast_needs_absolute_bounds(db):
    # Best day of a bad month (12 öre) is not "nailed".
    _seed_forecast(db, 0.12, base=0.15)
    assert "forecast" not in kinds(db)

    db.query(ForecastAccuracy).delete()
    db.query(SpotPrice).delete()
    db.commit()
    # Worst day of a calm month (18 öre) is not "off guard".
    _seed_forecast(db, 0.18, base=-0.04)
    assert "forecast" not in kinds(db)


def test_forecast_ignores_se1_and_se2(db):
    for area in ("SE1", "SE2"):
        for k in range(0, 21):
            d = D - timedelta(days=k)
            seed_day(db, area, d, [0.5] * 24)
            err = 0.03 if k == 0 else 0.05 + 0.01 * k
            for h in range(24):
                db.add(
                    ForecastAccuracy(target_date=d, area=area, model_name="lgbm", hour=h, predicted_sek_kwh=0.5 + err)
                )
    db.commit()
    assert "forecast" not in kinds(db)


def test_forecast_not_fired_in_the_middle_or_without_history(db):
    _seed_forecast(db, 0.15)
    assert "forecast" not in kinds(db)

    db.query(ForecastAccuracy).filter(ForecastAccuracy.target_date < D - timedelta(days=5)).delete()
    db.commit()
    assert "forecast" not in kinds(db)


# ── tomorrow ─────────────────────────────────────────────────────────────────


def test_tomorrow_boundary(db):
    seed_day(db, "SE3", D, [0.5] * 24)
    seed_day(db, "SE3", D + timedelta(days=1), [0.65] * 24)
    c = kinds(db)["tomorrow"]
    assert c.text == "Tomorrow SE3 jumps to 65 öre/kWh, from 50 today"
    assert c.sub == "Day-ahead prices for tomorrow are out."

    db.query(SpotPrice).filter(SpotPrice.price_sek_kwh == 0.65).delete()
    db.commit()
    seed_day(db, "SE3", D + timedelta(days=1), [0.64] * 24)
    assert "tomorrow" not in kinds(db)


def test_tomorrow_cheaper(db):
    seed_day(db, "SE3", D, [1.0] * 24)
    seed_day(db, "SE3", D + timedelta(days=1), [0.55] * 24)
    assert kinds(db)["tomorrow"].text == "Tomorrow SE3 drops to 55 öre/kWh, from 100 today"


def test_tomorrow_ignores_ratio_on_near_zero_days(db):
    # 5 → 15 öre is +200% but only 10 öre; not a story.
    seed_day(db, "SE3", D, [0.05] * 24)
    seed_day(db, "SE3", D + timedelta(days=1), [0.15] * 24)
    assert "tomorrow" not in kinds(db)


# ── baseline / rotation / API ────────────────────────────────────────────────


def test_baseline_text(db):
    seed_history(db, "SE3", D, 12, lambda k: 0.5)
    seed_day(db, "SE3", D, [0.41] * 24)
    c = kinds(db)["baseline"]
    assert c.text == "SE3 averages 41 öre/kWh today"
    assert c.sub == "18% below the 30-day average."
    assert c.score == 10


def test_rotation_never_three_in_a_row(db):
    # SE2 is negative every day, so 'negative' is always the top candidate
    for k in range(0, 10):
        seed_day(db, "SE2", D - timedelta(days=k), [-0.1] * 6 + [0.3] * 18)
        seed_day(db, "SE3", D - timedelta(days=k), [0.4] * 24)
    data = load_story_data(db, D, D)
    headlines, _ = replay_headlines(data, D, D)
    seq = [h.kind for h in headlines]
    assert len(seq) == 7
    assert seq[0] == seq[1] == "negative"
    assert seq[2] != "negative"
    assert not any(seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2))


def test_area_weight_lets_se3_beat_se1_within_a_kind(db):
    # Both zones are cheapest in 90 days (raw 40 + 15*log2(90/14) ~ 80.2), so only the weight separates them.
    for area in ("SE1", "SE3"):
        seed_history(db, area, D, 90, lambda k: 0.5)
        seed_day(db, area, D, [0.1] * 24)
    c = kinds(db)["low"]
    assert c.area == "SE3"
    assert c.score == pytest.approx(40 + 15 * math.log2(90 / 14))

    db.query(SpotPrice).filter(SpotPrice.area == "SE3").delete()
    db.commit()
    c = kinds(db)["low"]
    assert c.area == "SE1"
    assert c.score == pytest.approx((40 + 15 * math.log2(90 / 14)) * 0.8)


def test_novelty_penalty_demotes_a_repeating_kind():
    # 'negative' has the top raw score every day; the 3-in-a-row rule alone would give it 5 of 7 days.
    data = StoryData()
    for k in range(7):
        data._cache[D - timedelta(days=k)] = [
            Candidate("negative", "SE3", 49, "n"),
            Candidate("tomorrow", "SE3", 30, "t"),
            Candidate("wind", "ALL", 25, "w"),
            Candidate("baseline", "SE3", 10, "b"),
        ]
    headlines, _ = replay_headlines(data, D, D)
    seq = [h.kind for h in headlines]
    assert seq[:2] == ["negative", "negative"]
    assert seq.count("negative") <= 4
    assert not any(seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2))


def test_story_endpoint_baseline_only(client, db):
    seed_day(db, "SE3", D, [0.41] * 24)
    r = client.get(f"/api/v1/story/today?date={D}")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == D.isoformat()
    assert body["headline"]["kind"] == "baseline"
    assert body["facts"] == []
    assert body["generated_at"]


def test_story_endpoint_empty_db_still_returns_headline(client):
    r = client.get(f"/api/v1/story/today?date={D}")
    assert r.status_code == 200
    assert r.json()["headline"]["kind"] == "baseline"


def test_story_endpoint_rejects_future_date(client):
    tomorrow = datetime.now(STOCKHOLM).date() + timedelta(days=1)
    assert client.get(f"/api/v1/story/today?date={tomorrow}").status_code == 422


def test_story_endpoint_facts_are_distinct_kinds(client, db):
    seed_day(db, "SE2", D, [-0.1] * 6 + [0.3] * 18)
    seed_day(db, "SE3", D, [1.0] * 24)
    seed_day(db, "SE3", D + timedelta(days=1), [0.5] * 24)
    body = client.get(f"/api/v1/story/today?date={D}").json()
    assert body["headline"]["kind"] == "negative"
    fact_kinds = [f["kind"] for f in body["facts"]]
    assert fact_kinds == ["tomorrow", "baseline"]
    assert len(set(fact_kinds)) == len(fact_kinds)
