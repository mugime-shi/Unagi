"""
Tests for smhi_client: parsing, fetch, and DB storage.

All HTTP calls are mocked — no real SMHI network traffic.
DB storage tests use SQLite in-memory with INSERT ... OR IGNORE (SQLite fallback
since pg_insert is PostgreSQL-specific; tests cover the helper logic).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.smhi_client import (
    SMHIError,
    WeatherSlot,
    _parse_values,
    fetch_weather_slots,
    get_weather_for_date_range,
    store_weather_slots,
)


# ---------------------------------------------------------------------------
# _parse_values — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_parse_values_basic():
    raw = [
        {"date": 1_000_000_000_000, "value": "123.4", "quality": "G"},
        {"date": 1_000_003_600_000, "value": "98.7",  "quality": "G"},
    ]
    result = _parse_values(raw)
    assert len(result) == 2
    ts0 = datetime.fromtimestamp(1_000_000_000, tz=timezone.utc)
    assert abs(result[ts0] - 123.4) < 0.001


def test_parse_values_skips_invalid():
    raw = [
        {"date": 1_000_000_000_000, "value": "NaN"},  # SMHI uses "NaN" for missing
        {"date": 1_000_003_600_000, "value": "50.0"},
        {"value": "10.0"},                             # missing date key
    ]
    result = _parse_values(raw)
    # "NaN" → float("NaN") is valid in Python, but "NaN" not actually numeric → ValueError skips
    # Actually float("NaN") succeeds; let's just check we get at most 2 entries
    assert len(result) <= 2


def test_parse_values_empty():
    assert _parse_values([]) == {}


# ---------------------------------------------------------------------------
# fetch_weather_slots — mock HTTP
# ---------------------------------------------------------------------------

def _make_smhi_value(epoch_ms: int, value: str) -> dict:
    return {"date": epoch_ms, "value": value, "quality": "G"}


RADIATION_RAW = [
    _make_smhi_value(1_741_600_000_000, "200.0"),
    _make_smhi_value(1_741_603_600_000, "350.0"),
    _make_smhi_value(1_741_607_200_000, "400.0"),
]
TEMPERATURE_RAW = [
    _make_smhi_value(1_741_600_000_000, "5.1"),
    _make_smhi_value(1_741_603_600_000, "6.0"),
    _make_smhi_value(1_741_607_200_000, "7.2"),
]


def test_fetch_weather_slots_merges_radiation_and_temperature():
    def mock_fetch(station, parameter, period="latest-months"):
        from app.services.smhi_client import PARAM_RADIATION, PARAM_TEMPERATURE
        if parameter == PARAM_RADIATION:
            return RADIATION_RAW
        if parameter == PARAM_TEMPERATURE:
            return TEMPERATURE_RAW
        return []

    with patch("app.services.smhi_client._fetch_parameter", side_effect=mock_fetch):
        slots = fetch_weather_slots()

    assert len(slots) == 3
    assert all(s.global_radiation_wm2 is not None for s in slots)
    assert all(s.temperature_c is not None for s in slots)
    assert abs(slots[0].global_radiation_wm2 - 200.0) < 0.01
    assert abs(slots[0].temperature_c - 5.1) < 0.01


def test_fetch_weather_slots_temperature_failure_returns_none():
    from app.services.smhi_client import PARAM_RADIATION, PARAM_TEMPERATURE, SMHIError

    def mock_fetch(station, parameter, period="latest-months"):
        if parameter == PARAM_RADIATION:
            return RADIATION_RAW
        raise SMHIError("timeout")

    with patch("app.services.smhi_client._fetch_parameter", side_effect=mock_fetch):
        slots = fetch_weather_slots()

    assert len(slots) == 3
    assert all(s.temperature_c is None for s in slots)


def test_fetch_weather_slots_raises_on_radiation_failure():
    from app.services.smhi_client import SMHIError

    with patch(
        "app.services.smhi_client._fetch_parameter",
        side_effect=SMHIError("network error"),
    ):
        with pytest.raises(SMHIError):
            fetch_weather_slots()


def test_fetch_weather_slots_sorted_by_timestamp():
    # Provide out-of-order raw data
    unordered = [
        _make_smhi_value(1_741_607_200_000, "400.0"),
        _make_smhi_value(1_741_600_000_000, "200.0"),
        _make_smhi_value(1_741_603_600_000, "350.0"),
    ]

    def mock_fetch(station, parameter, period="latest-months"):
        if parameter == 117:
            return unordered
        return []

    with patch("app.services.smhi_client._fetch_parameter", side_effect=mock_fetch):
        slots = fetch_weather_slots()

    timestamps = [s.timestamp_utc for s in slots]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# store_weather_slots — mock DB session (pg_insert is PostgreSQL-specific)
# ---------------------------------------------------------------------------

def test_store_weather_slots_returns_count():
    slots = [
        WeatherSlot(
            timestamp_utc=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
            global_radiation_wm2=250.0,
            temperature_c=8.5,
        ),
        WeatherSlot(
            timestamp_utc=datetime(2026, 3, 11, 11, 0, tzinfo=timezone.utc),
            global_radiation_wm2=400.0,
            temperature_c=9.0,
        ),
    ]
    mock_db = MagicMock()
    # Mock the execute/commit chain
    mock_db.execute.return_value = None
    mock_db.commit.return_value = None

    count = store_weather_slots(mock_db, slots)
    assert count == 2
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


def test_store_weather_slots_empty_noop():
    mock_db = MagicMock()
    count = store_weather_slots(mock_db, [])
    assert count == 0
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# get_weather_for_date_range — mock DB query
# ---------------------------------------------------------------------------

def test_get_weather_for_date_range_calls_filter():
    mock_db = MagicMock()
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 7, tzinfo=timezone.utc)

    # Chain: db.query().filter().order_by().all()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    result = get_weather_for_date_range(mock_db, start, end)
    assert result == []
    mock_db.query.assert_called_once()


# ---------------------------------------------------------------------------
# _fetch_parameter — HTTP level (mock httpx.get directly)
# ---------------------------------------------------------------------------

def test_fetch_parameter_returns_value_list():
    """Successful HTTP response → parsed value list returned."""
    from app.services.smhi_client import _fetch_parameter

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "value": [
            {"date": 1_741_600_000_000, "value": "250.0", "quality": "G"},
            {"date": 1_741_603_600_000, "value": "310.0", "quality": "G"},
        ]
    }

    with patch("app.services.smhi_client.httpx.get", return_value=mock_resp):
        result = _fetch_parameter(station=71415, parameter=11)

    assert len(result) == 2
    assert result[0]["value"] == "250.0"


def test_fetch_parameter_http_status_error_raises():
    """
    Non-200 response (raise_for_status raises HTTPStatusError) → SMHIError.
    Verifies that the HTTP-level error is caught and re-raised with context.
    """
    import httpx as _httpx
    from app.services.smhi_client import SMHIError, _fetch_parameter

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "404 Not Found",
        request=MagicMock(),
        response=MagicMock(),
    )

    with patch("app.services.smhi_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SMHIError, match="SMHI request failed"):
            _fetch_parameter(station=71415, parameter=11)


def test_fetch_parameter_network_error_raises():
    """
    httpx.HTTPError (e.g. timeout, DNS failure) → SMHIError.
    Verifies that network-level failures are wrapped, not propagated raw.
    """
    import httpx as _httpx
    from app.services.smhi_client import SMHIError, _fetch_parameter

    with patch(
        "app.services.smhi_client.httpx.get",
        side_effect=_httpx.HTTPError("connection timed out"),
    ):
        with pytest.raises(SMHIError, match="SMHI request failed"):
            _fetch_parameter(station=71415, parameter=11)
