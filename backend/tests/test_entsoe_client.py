"""
Tests for entsoe_client.py — no real API calls, all mocked via httpx.
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.entsoe_client import (
    EntsoEError,
    PricePoint,
    _parse_xml,
    fetch_day_ahead_prices,
)

# ---------------------------------------------------------------------------
# Minimal ENTSO-E XML fixture (PT60M, 3 points for simplicity)
# ---------------------------------------------------------------------------
SAMPLE_XML_60M = """\
<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument
    xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>test</mRID>
  <type>A44</type>
  <TimeSeries>
    <mRID>ts1</mRID>
    <Period>
      <timeInterval>
        <start>2026-03-07T23:00Z</start>
        <end>2026-03-08T23:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>50.00</price.amount></Point>
      <Point><position>2</position><price.amount>80.00</price.amount></Point>
      <Point><position>3</position><price.amount>120.00</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""

SAMPLE_XML_15M = """\
<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument
    xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>test15</mRID>
  <type>A44</type>
  <TimeSeries>
    <mRID>ts2</mRID>
    <Period>
      <timeInterval>
        <start>2026-03-07T23:00Z</start>
        <end>2026-03-08T23:00Z</end>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><price.amount>40.00</price.amount></Point>
      <Point><position>2</position><price.amount>60.00</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""


# ---------------------------------------------------------------------------
# _parse_xml unit tests
# ---------------------------------------------------------------------------

def test_parse_xml_60m_returns_sorted_points():
    points = _parse_xml(SAMPLE_XML_60M, eur_to_sek=11.0)
    assert len(points) == 3
    assert points[0].timestamp_utc == datetime(2026, 3, 7, 23, 0, tzinfo=timezone.utc)
    assert points[1].timestamp_utc == datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc)
    assert points[2].timestamp_utc == datetime(2026, 3, 8, 1, 0, tzinfo=timezone.utc)
    assert points[0].resolution == "PT60M"


def test_parse_xml_eur_to_sek_conversion():
    points = _parse_xml(SAMPLE_XML_60M, eur_to_sek=11.0)
    # 50 EUR/MWh * 11 / 1000 = 0.55 SEK/kWh
    assert abs(points[0].price_sek_kwh - 0.55) < 1e-4
    assert abs(points[1].price_sek_kwh - 0.88) < 1e-4


def test_parse_xml_15m_timestamps():
    points = _parse_xml(SAMPLE_XML_15M, eur_to_sek=11.0)
    assert len(points) == 2
    assert points[0].timestamp_utc == datetime(2026, 3, 7, 23, 0, tzinfo=timezone.utc)
    assert points[1].timestamp_utc == datetime(2026, 3, 7, 23, 15, tzinfo=timezone.utc)
    assert points[0].resolution == "PT15M"


def test_parse_xml_different_rates():
    points_11 = _parse_xml(SAMPLE_XML_60M, eur_to_sek=11.0)
    points_12 = _parse_xml(SAMPLE_XML_60M, eur_to_sek=12.0)
    # 50 EUR/MWh * 12 / 1000 = 0.60 SEK/kWh
    assert abs(points_12[0].price_sek_kwh - 0.60) < 1e-4
    assert points_12[0].price_sek_kwh > points_11[0].price_sek_kwh


# ---------------------------------------------------------------------------
# fetch_day_ahead_prices integration tests (HTTP mocked)
# ---------------------------------------------------------------------------

def _make_mock_response(xml_text: str, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = xml_text
    return mock_resp


@patch("app.services.entsoe_client.httpx.Client")
def test_fetch_returns_price_points(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(SAMPLE_XML_60M)
    mock_client_cls.return_value = mock_client

    points = fetch_day_ahead_prices(
        target_date=date(2026, 3, 8),
        api_key="test-key",
        eur_to_sek=11.0,
    )
    assert len(points) > 0
    assert all(isinstance(p, PricePoint) for p in points)


@patch("app.services.entsoe_client.httpx.Client")
def test_fetch_raises_on_http_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response("Unauthorized", status_code=401)
    mock_client_cls.return_value = mock_client

    with pytest.raises(EntsoEError, match="HTTP 401"):
        fetch_day_ahead_prices(date(2026, 3, 8), api_key="bad-key")


def test_fetch_raises_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.entsoe_client.settings.entsoe_api_key", "")
    with pytest.raises(EntsoEError, match="ENTSOE_API_KEY"):
        fetch_day_ahead_prices(date(2026, 3, 8))


@patch("app.services.entsoe_client.httpx.Client")
def test_fetch_raises_on_network_error(mock_client_cls):
    """httpx.RequestError (e.g. DNS failure, timeout) must be wrapped in EntsoEError."""
    import httpx as _httpx

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = _httpx.RequestError("connection refused")
    mock_client_cls.return_value = mock_client

    with pytest.raises(EntsoEError, match="Network error"):
        fetch_day_ahead_prices(date(2026, 3, 8), api_key="test")


@patch("app.services.entsoe_client.httpx.Client")
def test_fetch_no_data_in_date_window_raises(mock_client_cls):
    """
    XML with all points outside the requested date window must raise EntsoEError.
    Simulates ENTSO-E returning tomorrow's data when we request today's.
    """
    # Shift the fixture's timestamps by 2 days → outside the 2026-03-07 window
    xml_wrong_date = SAMPLE_XML_60M.replace(
        "2026-03-07T23:00Z", "2026-03-09T23:00Z"
    ).replace(
        "<end>2026-03-08T23:00Z</end>", "<end>2026-03-10T23:00Z</end>"
    )

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _make_mock_response(xml_wrong_date)
    mock_client_cls.return_value = mock_client

    with pytest.raises(EntsoEError, match="No price data found"):
        fetch_day_ahead_prices(date(2026, 3, 7), api_key="test", eur_to_sek=11.0)


# ---------------------------------------------------------------------------
# _parse_xml edge cases
# ---------------------------------------------------------------------------

def test_parse_resolution_unknown_raises():
    """Unsupported resolution string (e.g. PT30M) must raise EntsoEError."""
    from app.services.entsoe_client import _parse_resolution

    with pytest.raises(EntsoEError, match="Unknown resolution"):
        _parse_resolution("PT30M")


def test_parse_xml_api_error_reason():
    """Reason code != 999 in the XML response must raise EntsoEError."""
    error_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument
    xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>err1</mRID>
  <type>A44</type>
  <Reason>
    <code>998</code>
    <text>No matching data found for the requested period</text>
  </Reason>
</Publication_MarketDocument>
"""
    with pytest.raises(EntsoEError, match="998"):
        _parse_xml(error_xml, eur_to_sek=11.0)


def test_parse_xml_multiple_timeseries_merged():
    """Two TimeSeries blocks are merged and the result is sorted by timestamp."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument
    xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>multi</mRID>
  <type>A44</type>
  <TimeSeries>
    <mRID>ts1</mRID>
    <Period>
      <timeInterval>
        <start>2026-03-07T23:00Z</start>
        <end>2026-03-08T00:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>50.00</price.amount></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <mRID>ts2</mRID>
    <Period>
      <timeInterval>
        <start>2026-03-08T00:00Z</start>
        <end>2026-03-08T01:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>80.00</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""
    points = _parse_xml(xml, eur_to_sek=11.0)
    assert len(points) == 2
    # Merged and sorted chronologically
    assert points[0].timestamp_utc < points[1].timestamp_utc
    assert abs(points[0].price_eur_mwh - 50.0) < 0.01
    assert abs(points[1].price_eur_mwh - 80.0) < 0.01
