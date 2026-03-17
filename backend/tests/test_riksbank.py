"""Tests for Riksbank SWEA API client."""

from datetime import date
from unittest.mock import patch

import httpx
import pytest

from app.services.riksbank_client import (
    _FALLBACK_RATE,
    fetch_eur_sek_rate,
    get_eur_sek_rate,
)

_DUMMY_REQUEST = httpx.Request("GET", "https://api.riksbank.se/swea/v1/Observations/Latest/SEKEURPMI")


def _mock_response(rate: float = 10.769, pub_date: str = "2026-03-16", status: int = 200):
    if status == 200:
        resp = httpx.Response(status, json={"date": pub_date, "value": rate}, request=_DUMMY_REQUEST)
    else:
        resp = httpx.Response(status, request=_DUMMY_REQUEST)
    return resp


class TestFetchEurSekRate:
    def test_success(self):
        with patch("app.services.riksbank_client.httpx.get", return_value=_mock_response(10.5, "2026-03-14")):
            rate, pub_date = fetch_eur_sek_rate()
            assert rate == 10.5
            assert pub_date == date(2026, 3, 14)

    def test_fallback_on_http_error(self):
        with patch("app.services.riksbank_client.httpx.get", side_effect=httpx.ConnectError("network down")):
            rate, pub_date = fetch_eur_sek_rate()
            assert rate == _FALLBACK_RATE
            assert pub_date is None

    def test_fallback_on_bad_json(self):
        resp = httpx.Response(200, json={"unexpected": "data"}, request=_DUMMY_REQUEST)
        with patch("app.services.riksbank_client.httpx.get", return_value=resp):
            rate, pub_date = fetch_eur_sek_rate()
            assert rate == _FALLBACK_RATE
            assert pub_date is None

    def test_fallback_on_http_500(self):
        with patch("app.services.riksbank_client.httpx.get", return_value=_mock_response(status=500)):
            rate, pub_date = fetch_eur_sek_rate()
            assert rate == _FALLBACK_RATE
            assert pub_date is None


class TestGetEurSekRate:
    def test_returns_float(self):
        with patch("app.services.riksbank_client.httpx.get", return_value=_mock_response(10.8)):
            from app.services.riksbank_client import _cached_rate_for_date
            _cached_rate_for_date.cache_clear()

            rate = get_eur_sek_rate()
            assert isinstance(rate, float)
            assert rate == 10.8

    def test_cached_per_day(self):
        with patch("app.services.riksbank_client.httpx.get", return_value=_mock_response(10.8)) as mock_get:
            from app.services.riksbank_client import _cached_rate_for_date
            _cached_rate_for_date.cache_clear()

            rate1 = get_eur_sek_rate()
            rate2 = get_eur_sek_rate()
            assert rate1 == rate2
            assert mock_get.call_count == 1
