"""Multi-point (wind-belt averaged) forecast wind — MULTI_POINT_WIND_AREAS flag."""

from datetime import datetime, timezone

import pytest

from app.services.openmeteo_client import (
    AREA_WIND_POINTS,
    _apply_belt_wind,
    multi_point_wind_areas,
)


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("MULTI_POINT_WIND_AREAS", raising=False)


def _ts(hour: int) -> datetime:
    return datetime(2026, 7, 21, hour, tzinfo=timezone.utc)


def test_flag_unset_means_no_areas():
    assert multi_point_wind_areas() == []


def test_flag_parses_known_areas_only(monkeypatch):
    monkeypatch.setenv("MULTI_POINT_WIND_AREAS", "SE1, SE9,SE4,SE2")
    # SE4/SE9 have no belt points defined → ignored
    assert multi_point_wind_areas() == ["SE1", "SE2"]


def test_belt_points_exist_for_flaggable_areas():
    for area, points in AREA_WIND_POINTS.items():
        assert len(points) >= 3, area


def test_apply_belt_wind_overrides_matching_slots():
    slots = [
        {"target_utc": _ts(0), "wind_speed_10m": 1.0, "wind_speed_100m": 2.0},
        {"target_utc": _ts(1), "wind_speed_10m": 3.0, "wind_speed_100m": 4.0},
    ]
    belt = {_ts(0): (10.0, 20.0)}
    replaced = _apply_belt_wind(slots, belt)
    assert replaced == 1
    assert slots[0]["wind_speed_10m"] == 10.0
    assert slots[0]["wind_speed_100m"] == 20.0
    # slot without belt entry keeps single-point values
    assert slots[1]["wind_speed_10m"] == 3.0
    assert slots[1]["wind_speed_100m"] == 4.0


def test_apply_belt_wind_keeps_value_when_belt_side_missing():
    slots = [{"target_utc": _ts(0), "wind_speed_10m": 1.0, "wind_speed_100m": 2.0}]
    _apply_belt_wind(slots, {_ts(0): (None, 25.0)})
    assert slots[0]["wind_speed_10m"] == 1.0  # None side untouched
    assert slots[0]["wind_speed_100m"] == 25.0
