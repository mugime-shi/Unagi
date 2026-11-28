"""
Tests for solar_model: estimate_hourly_generation, simulate_month (SMHI + reference),
and optimize_solar_month (sell/store/self-consume dispatch + tax credit).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.solar_model import (
    estimate_hourly_generation,
    optimize_solar_month,
    simulate_month,
    simulate_month_reference,
)

# ---------------------------------------------------------------------------
# estimate_hourly_generation — pure function
# ---------------------------------------------------------------------------


def test_estimate_at_1000_wm2_equals_kwp():
    """At 1000 W/m² with PR=1.0, generation == panel_kwp kWh."""
    assert estimate_hourly_generation(1000.0, panel_kwp=6.0, performance_ratio=1.0) == pytest.approx(6.0)


def test_estimate_typical_conditions():
    """500 W/m², 6 kWp, PR=0.80 → 2.4 kWh."""
    gen = estimate_hourly_generation(500.0, panel_kwp=6.0, performance_ratio=0.80)
    assert gen == pytest.approx(2.4)


def test_estimate_zero_radiation():
    assert estimate_hourly_generation(0.0, 6.0) == 0.0


def test_estimate_negative_radiation_clamped():
    """Sensor noise can produce tiny negative values; clamp to 0."""
    assert estimate_hourly_generation(-5.0, 6.0) == 0.0


def test_estimate_scales_linearly_with_kwp():
    g1 = estimate_hourly_generation(400.0, panel_kwp=3.0)
    g2 = estimate_hourly_generation(400.0, panel_kwp=6.0)
    assert g2 == pytest.approx(g1 * 2)


# ---------------------------------------------------------------------------
# simulate_month_reference — uses lookup table, no DB
# ---------------------------------------------------------------------------


def test_reference_july_6kwp_in_range():
    """TASKS.md completion condition: 6 kWp July generation in [500, 800] kWh."""
    result = simulate_month_reference(panel_kwp=6.0, year=2026, month=7)
    assert result["data_source"] == "reference"
    assert 500 <= result["total_generation_kwh"] <= 800


def test_reference_december_less_than_july():
    """Winter generation must be much less than summer."""
    july = simulate_month_reference(6.0, 2026, 7)
    dec = simulate_month_reference(6.0, 2026, 12)
    assert dec["total_generation_kwh"] < july["total_generation_kwh"] * 0.1


def test_reference_june_reasonable():
    """June is peak month; 6 kWp should produce ~700–900 kWh."""
    result = simulate_month_reference(panel_kwp=6.0, year=2026, month=6)
    assert 600 <= result["total_generation_kwh"] <= 1000


def test_reference_scales_with_kwp():
    r3 = simulate_month_reference(panel_kwp=3.0, year=2026, month=7)
    r6 = simulate_month_reference(panel_kwp=6.0, year=2026, month=7)
    assert r6["total_generation_kwh"] == pytest.approx(r3["total_generation_kwh"] * 2)


def test_reference_daily_avg_consistent():
    result = simulate_month_reference(6.0, 2026, 7)
    import calendar

    days = calendar.monthrange(2026, 7)[1]
    assert result["daily_avg_kwh"] == pytest.approx(result["total_generation_kwh"] / days, rel=0.01)


def test_reference_all_months_positive():
    for m in range(1, 13):
        r = simulate_month_reference(6.0, 2026, m)
        assert r["total_generation_kwh"] > 0


# ---------------------------------------------------------------------------
# simulate_month — with mock DB
# ---------------------------------------------------------------------------


def _make_weather_row(ts: datetime, radiation: float):
    row = MagicMock()
    row.timestamp_utc = ts
    row.global_radiation_wm2 = radiation
    return row


def test_simulate_month_uses_smhi_data_when_available():
    # 2 hours of data with known radiation
    rows = [
        _make_weather_row(datetime(2026, 7, 1, 10, tzinfo=timezone.utc), 500.0),
        _make_weather_row(datetime(2026, 7, 1, 11, tzinfo=timezone.utc), 700.0),
    ]
    mock_db = MagicMock()

    with patch("app.services.solar_model.get_weather_for_date_range", return_value=rows):
        result = simulate_month(panel_kwp=6.0, year=2026, month=7, db=mock_db)

    assert result["data_source"] == "smhi"
    assert result["hours_with_data"] == 2
    expected = estimate_hourly_generation(500.0, 6.0) + estimate_hourly_generation(700.0, 6.0)
    assert result["total_generation_kwh"] == pytest.approx(expected, rel=0.001)


def test_simulate_month_falls_back_to_reference_when_db_empty():
    mock_db = MagicMock()

    with patch("app.services.solar_model.get_weather_for_date_range", return_value=[]):
        result = simulate_month(panel_kwp=6.0, year=2026, month=7, db=mock_db)

    assert result["data_source"] == "reference"
    assert 500 <= result["total_generation_kwh"] <= 800


def test_simulate_month_smhi_slots_structure():
    rows = [
        _make_weather_row(datetime(2026, 7, 1, 12, tzinfo=timezone.utc), 800.0),
    ]
    mock_db = MagicMock()

    with patch("app.services.solar_model.get_weather_for_date_range", return_value=rows):
        result = simulate_month(panel_kwp=6.0, year=2026, month=7, db=mock_db)

    assert len(result["hourly_slots"]) == 1
    slot = result["hourly_slots"][0]
    assert "timestamp_utc" in slot
    assert "radiation_wm2" in slot
    assert "generation_kwh" in slot
    assert slot["generation_kwh"] == pytest.approx(estimate_hourly_generation(800.0, 6.0), rel=0.001)


def test_simulate_month_zero_radiation_hours_contribute_nothing():
    rows = [
        _make_weather_row(datetime(2026, 12, 1, 1, tzinfo=timezone.utc), 0.0),
        _make_weather_row(datetime(2026, 12, 1, 2, tzinfo=timezone.utc), 0.0),
    ]
    mock_db = MagicMock()

    with patch("app.services.solar_model.get_weather_for_date_range", return_value=rows):
        result = simulate_month(panel_kwp=6.0, year=2026, month=12, db=mock_db)

    assert result["total_generation_kwh"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# optimize_solar_month — mock both SMHI and spot prices
# ---------------------------------------------------------------------------


def _make_day_night_spot(year, month, day, price=0.50):
    """Spot prices for one day: uniform price across all 24 hours."""
    return {datetime(year, month, day, h, tzinfo=timezone.utc): price for h in range(24)}


def _make_day_night_smhi(year, month, day, daytime_rad=400.0):
    """
    SMHI weather rows for one day: solar generation 7–19h, zero at night.
    Simulates the realistic scenario where surplus exists during the day and
    deficit at night — both selling AND buying occur.
    """
    rows = []
    for h in range(24):
        rad = daytime_rad if 7 <= h < 19 else 0.0
        rows.append(_make_weather_row(datetime(year, month, day, h, tzinfo=timezone.utc), rad))
    return rows


def test_optimize_raises_on_missing_spot_prices():
    mock_db = MagicMock()
    with patch("app.services.solar_model.get_weather_for_date_range", return_value=[]):
        with patch("app.services.solar_model._get_hourly_spot", return_value={}):
            with pytest.raises(ValueError, match="No spot price data"):
                optimize_solar_month(6.0, 0.0, 5000, 2026, 7, mock_db)


def test_optimize_returns_expected_keys():
    spot = _make_day_night_spot(2026, 7, 1, price=0.40)
    smhi = _make_day_night_smhi(2026, 7, 1)
    mock_db = MagicMock()
    with patch("app.services.solar_model.get_weather_for_date_range", return_value=smhi):
        with patch("app.services.solar_model._get_hourly_spot", return_value=spot):
            result = optimize_solar_month(6.0, 0.0, 5000, 2026, 7, mock_db)

    for key in (
        "solar_generation_kwh",
        "self_consumed_kwh",
        "sold_to_grid_kwh",
        "bought_from_grid_kwh",
        "revenue_sek",
        "savings_from_self_consumption_sek",
        "total_benefit_without_tax_credit_sek",
        "total_benefit_with_tax_credit_sek",
        "tax_credit",
    ):
        assert key in result, f"Missing key: {key}"


def test_optimize_2025_month_has_tax_credit():
    """
    2025 months should include non-zero tax credit.
    Day/night pattern ensures both selling (day surplus) and buying (night deficit),
    which is required for the tax credit eligible_kwh = min(sold, bought) > 0.
    """
    smhi = _make_day_night_smhi(2025, 7, 1, daytime_rad=400.0)  # generates ~23 kWh daytime
    spot = _make_day_night_spot(2025, 7, 1, price=0.50)
    mock_db = MagicMock()
    with patch("app.services.solar_model.get_weather_for_date_range", return_value=smhi):
        with patch("app.services.solar_model._get_hourly_spot", return_value=spot):
            result = optimize_solar_month(6.0, 0.0, 5000, 2025, 7, mock_db)

    assert result["tax_credit"]["applies"] is True
    assert result["sold_to_grid_kwh"] > 0
    assert result["bought_from_grid_kwh"] > 0
    assert result["total_benefit_with_tax_credit_sek"] > result["total_benefit_without_tax_credit_sek"]


def test_optimize_2026_month_no_tax_credit():
    """2026+ months must not include tax credit."""
    smhi = _make_day_night_smhi(2026, 7, 1)
    spot = _make_day_night_spot(2026, 7, 1, price=0.50)
    mock_db = MagicMock()
    with patch("app.services.solar_model.get_weather_for_date_range", return_value=smhi):
        with patch("app.services.solar_model._get_hourly_spot", return_value=spot):
            result = optimize_solar_month(6.0, 0.0, 5000, 2026, 7, mock_db)

    assert result["tax_credit"]["applies"] is False
    assert result["tax_credit"]["monthly_credit_sek"] == 0.0
    assert result["total_benefit_with_tax_credit_sek"] == result["total_benefit_without_tax_credit_sek"]


def test_optimize_conservation_law():
    """self_consumed + sold ≈ total_generation (energy balance)."""
    smhi = _make_day_night_smhi(2026, 7, 1)
    spot = _make_day_night_spot(2026, 7, 1, price=0.45)
    mock_db = MagicMock()
    with patch("app.services.solar_model.get_weather_for_date_range", return_value=smhi):
        with patch("app.services.solar_model._get_hourly_spot", return_value=spot):
            result = optimize_solar_month(6.0, 0.0, 5000, 2026, 7, mock_db)

    gen = result["solar_generation_kwh"]
    used = result["self_consumed_kwh"] + result["sold_to_grid_kwh"]
    assert used == pytest.approx(gen, rel=0.01)


def test_optimize_battery_reduces_grid_purchases():
    """
    With day/night solar pattern, a battery stores daytime surplus and
    discharges at night — reducing bought_from_grid vs no-battery case.
    """
    smhi = _make_day_night_smhi(2026, 7, 1, daytime_rad=400.0)
    spot = _make_day_night_spot(2026, 7, 1, price=0.45)
    mock_db = MagicMock()

    with patch("app.services.solar_model.get_weather_for_date_range", return_value=smhi):
        with patch("app.services.solar_model._get_hourly_spot", return_value=spot):
            no_bat = optimize_solar_month(6.0, 0.0, 5000, 2026, 7, mock_db)
            with_bat = optimize_solar_month(6.0, 10.0, 5000, 2026, 7, mock_db)

    assert with_bat["bought_from_grid_kwh"] <= no_bat["bought_from_grid_kwh"]
    assert with_bat["battery_effect_sek"] >= -0.01  # battery should not hurt
