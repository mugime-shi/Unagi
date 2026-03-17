"""
Tests for imbalance_client.py — no real API calls, all mocked via httpx.

Covers:
  - _parse_zip_response: happy path, Long/Short categories, timestamp offsets
  - _parse_zip_response: missing fields are silently skipped
  - fetch_imbalance_prices: HTTP 200 with valid ZIP, HTTP error, network error, no API key
  - fetch_imbalance_prices: data outside date window raises BalancingError
"""

import io
import zipfile
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.imbalance_client import (
    CATEGORY_LONG,
    CATEGORY_SHORT,
    NS_B,
    BalancingError,
    BalancingPoint,
    _parse_zip_response,
    fetch_imbalance_prices,
)

# ---------------------------------------------------------------------------
# Helpers to build minimal Balancing_MarketDocument XML fixtures
# ---------------------------------------------------------------------------

def _make_xml(start_utc: str, resolution: str, points: list[dict]) -> str:
    """
    Build a minimal Balancing_MarketDocument XML string.
    Uses the default namespace declaration so ElementTree resolves tags as
    {NS_B}TagName — exactly what imbalance_client.py's findall() looks for.
    Each dict in points must have: position, amount, category.
    """
    pts_xml = "\n".join(
        f"""      <Point>
        <position>{p['position']}</position>
        <imbalance_Price.amount>{p['amount']}</imbalance_Price.amount>
        <imbalance_Price.category>{p['category']}</imbalance_Price.category>
      </Point>"""
        for p in points
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Balancing_MarketDocument xmlns="{NS_B}">
  <TimeSeries>
    <Period>
      <timeInterval>
        <start>{start_utc}</start>
      </timeInterval>
      <resolution>{resolution}</resolution>
{pts_xml}
    </Period>
  </TimeSeries>
</Balancing_MarketDocument>
"""


def _make_zip(xml_content: str) -> bytes:
    """Wrap an XML string in an in-memory ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("balancing.xml", xml_content)
    return buf.getvalue()


# Reference start: 2026-03-14 23:00 UTC = 2026-03-15 00:00 CET
SAMPLE_START = "2026-03-14T23:00Z"
SAMPLE_POINTS = [
    {"position": 1, "amount": "50.00", "category": CATEGORY_SHORT},  # A05
    {"position": 2, "amount": "45.00", "category": CATEGORY_SHORT},
    {"position": 1, "amount": "48.00", "category": CATEGORY_LONG},   # A04
]
SAMPLE_XML  = _make_xml(SAMPLE_START, "PT15M", SAMPLE_POINTS)
SAMPLE_ZIP  = _make_zip(SAMPLE_XML)


# ---------------------------------------------------------------------------
# _parse_zip_response unit tests
# ---------------------------------------------------------------------------

def test_parse_returns_correct_point_count():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    assert len(points) == 3


def test_parse_timestamps_are_15min_apart():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    # Sort by timestamp; two A05 + one A04 at 23:00 and 23:15 UTC
    times = sorted({p.timestamp_utc for p in points})
    assert len(times) == 2
    diff = (times[1] - times[0]).total_seconds()
    assert diff == 15 * 60


def test_parse_first_slot_timestamp():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    first_ts = min(p.timestamp_utc for p in points)
    assert first_ts == datetime(2026, 3, 14, 23, 0, tzinfo=timezone.utc)


def test_parse_categories_both_present():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    cats = {p.category for p in points}
    assert CATEGORY_LONG  in cats  # A04
    assert CATEGORY_SHORT in cats  # A05


def test_parse_eur_to_sek_conversion():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    # 50 EUR/MWh → 50 * 11 / 1000 = 0.55 SEK/kWh
    short_p1 = next(
        p for p in points
        if p.category == CATEGORY_SHORT and p.price_eur_mwh == 50.0
    )
    assert abs(short_p1.price_sek_kwh - 0.55) < 1e-4


def test_parse_result_sorted_by_timestamp_then_category():
    points = _parse_zip_response(SAMPLE_ZIP, eur_to_sek=11.0)
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        assert (a.timestamp_utc, a.category) <= (b.timestamp_utc, b.category)


def test_parse_skips_points_missing_fields():
    # Build XML where one Point is missing the amount tag
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Balancing_MarketDocument xmlns="{NS_B}">
  <TimeSeries>
    <Period>
      <timeInterval>
        <start>2026-03-14T23:00Z</start>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point>
        <position>1</position>
        <!-- missing imbalance_Price.amount and category — should be skipped -->
      </Point>
      <Point>
        <position>2</position>
        <imbalance_Price.amount>60.00</imbalance_Price.amount>
        <imbalance_Price.category>{CATEGORY_SHORT}</imbalance_Price.category>
      </Point>
    </Period>
  </TimeSeries>
</Balancing_MarketDocument>
"""
    points = _parse_zip_response(_make_zip(xml), eur_to_sek=11.0)
    assert len(points) == 1
    assert points[0].price_eur_mwh == 60.0


def test_parse_bad_zip_raises_balancing_error():
    with pytest.raises(BalancingError, match="not a valid ZIP"):
        _parse_zip_response(b"not a zip file", eur_to_sek=11.0)


def test_parse_resolution_stored_on_point():
    xml = _make_xml(SAMPLE_START, "PT60M", [{"position": 1, "amount": "70.00", "category": CATEGORY_SHORT}])
    points = _parse_zip_response(_make_zip(xml), eur_to_sek=11.0)
    assert len(points) == 1
    assert points[0].resolution == "PT60M"


# ---------------------------------------------------------------------------
# fetch_imbalance_prices integration tests (HTTP mocked)
# ---------------------------------------------------------------------------

def _make_mock_response(content: bytes, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.content = content
    return mock_resp


@patch("app.services.imbalance_client.httpx.Client")
def test_fetch_returns_balancing_points(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(SAMPLE_ZIP)
    mock_client_cls.return_value = mock_client

    points = fetch_imbalance_prices(
        target_date=date(2026, 3, 15),
        api_key="test-key",
        eur_to_sek=11.0,
    )
    assert len(points) > 0
    assert all(isinstance(p, BalancingPoint) for p in points)
    cats = {p.category for p in points}
    assert CATEGORY_SHORT in cats
    assert CATEGORY_LONG  in cats


@patch("app.services.imbalance_client.httpx.Client")
def test_fetch_raises_on_http_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(b"Unauthorized", status_code=401)
    mock_client_cls.return_value = mock_client

    with pytest.raises(BalancingError, match="HTTP 401"):
        fetch_imbalance_prices(date(2026, 3, 15), api_key="bad-key")


def test_fetch_raises_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.imbalance_client.settings.entsoe_api_key", "")
    with pytest.raises(BalancingError, match="ENTSOE_API_KEY"):
        fetch_imbalance_prices(date(2026, 3, 15))


@patch("app.services.imbalance_client.httpx.Client")
def test_fetch_raises_on_network_error(mock_client_cls):
    import httpx as _httpx
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = _httpx.RequestError("timeout")
    mock_client_cls.return_value = mock_client

    with pytest.raises(BalancingError, match="Network error"):
        fetch_imbalance_prices(date(2026, 3, 15), api_key="test")


@patch("app.services.imbalance_client.httpx.Client")
def test_fetch_raises_when_no_data_in_date_window(mock_client_cls):
    """
    ZIP contains data for a different date — filter should reject it all.
    """
    # Put the start 3 days ahead → outside the window for date(2026, 3, 15)
    future_xml = _make_xml(
        "2026-03-17T23:00Z", "PT15M",
        [{"position": 1, "amount": "55.00", "category": CATEGORY_SHORT}],
    )
    future_zip = _make_zip(future_xml)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(future_zip)
    mock_client_cls.return_value = mock_client

    with pytest.raises(BalancingError, match="No imbalance price data found"):
        fetch_imbalance_prices(date(2026, 3, 15), api_key="test", eur_to_sek=11.0)


@patch("app.services.imbalance_client.httpx.Client")
def test_fetch_filters_to_correct_cet_day(mock_client_cls):
    """
    ZIP with 2 days of data — only the slots within the requested CET day survive.
    2026-03-15 CET = 2026-03-14 23:00Z → 2026-03-15 23:00Z.
    """
    xml_day1 = _make_xml(
        "2026-03-14T23:00Z", "PT15M",
        [{"position": 1, "amount": "50.00", "category": CATEGORY_SHORT}],
    )
    xml_day2 = _make_xml(
        "2026-03-15T23:00Z", "PT15M",   # start of 2026-03-16 CET — outside window
        [{"position": 1, "amount": "60.00", "category": CATEGORY_SHORT}],
    )
    # Both in same ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("day1.xml", xml_day1)
        zf.writestr("day2.xml", xml_day2)
    two_day_zip = buf.getvalue()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(two_day_zip)
    mock_client_cls.return_value = mock_client

    # Requesting 2026-03-15 → only the 23:00Z slot from day1 survives (= CET midnight)
    # The 2026-03-15T23:00Z slot is *excluded* (it's the start of 2026-03-16 CET)
    points = fetch_imbalance_prices(date(2026, 3, 15), api_key="test", eur_to_sek=11.0)
    assert all(p.price_eur_mwh == 50.0 for p in points)
    assert all(p.timestamp_utc < datetime(2026, 3, 15, 23, 0, tzinfo=timezone.utc) for p in points)
