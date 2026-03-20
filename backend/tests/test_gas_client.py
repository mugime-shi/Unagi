"""
Tests for bundesnetzagentur_client.py — no real API calls, all mocked via httpx.

Covers:
- Preismonitor JSON API parsing (primary source, 2026+)
- Legacy CSV parsing (pre-2026 historical data)
- HTTP error / network error handling
- Graceful degradation (API→CSV fallback)
"""

from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.bundesnetzagentur_client import (
    GasPriceError,
    _parse_the_csv,
    fetch_gas_prices,
    fetch_gas_prices_from_api,
    fetch_gas_prices_from_final_api,
)  # noqa: F401

_DUMMY_API_REQUEST = httpx.Request("GET", "https://datenservice-api.tradinghub.eu/api/evoq/GetPreismonitorTabelle")
_DUMMY_FINAL_REQUEST = httpx.Request(
    "GET", "https://datenservice-api.tradinghub.eu/api/evoq/GetAusgleichsenergieFinalTabelle"
)


# ---------------------------------------------------------------------------
# Final API tests (historical date-range queries)
# ---------------------------------------------------------------------------


class TestFetchGasPricesFromFinalApi:
    def test_success_multiple_days(self):
        """Final API returns multiple days → parsed correctly."""
        json_data = [
            {"gastag": "2025-03-05T05:00:00", "preisAusgleichsenergieNegativ": 39.5},
            {"gastag": "2025-03-04T05:00:00", "preisAusgleichsenergieNegativ": 41.0},
            {"gastag": "2025-03-03T05:00:00", "preisAusgleichsenergieNegativ": 44.2},
        ]
        mock_resp = httpx.Response(200, json=json_data, request=_DUMMY_FINAL_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            points = fetch_gas_prices_from_final_api(date(2025, 3, 3), date(2025, 3, 5))

        assert len(points) == 3
        assert points[0].trade_date == date(2025, 3, 3)
        assert points[0].price_eur_mwh == 44.2
        assert points[2].trade_date == date(2025, 3, 5)
        assert points[2].price_eur_mwh == 39.5

    def test_api_error(self):
        """Final API returns 500 → GasPriceError."""
        mock_resp = httpx.Response(500, text="Internal Error", request=_DUMMY_FINAL_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            with pytest.raises(GasPriceError, match="HTTP 500"):
                fetch_gas_prices_from_final_api(date(2025, 3, 1), date(2025, 3, 5))


# ---------------------------------------------------------------------------
# Preismonitor API tests (current day)
# ---------------------------------------------------------------------------


class TestFetchGasPricesFromApi:
    def test_success(self):
        """JSON API returns valid data → parse into GasPricePoint."""
        json_data = [
            {
                "gasTag": "2026-03-19T06:00:00+01:00",
                "positiver_Ausgleichsenergiepreis": 56.77,
                "negativer_Ausgleichsenergiepreis": 54.544,
                "flexibilitätskostenbeitrag": 0,
                "differenzmengenpreis": 54.885,
            }
        ]
        mock_resp = httpx.Response(200, json=json_data, request=_DUMMY_API_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            points = fetch_gas_prices_from_api()

        assert len(points) == 1
        assert points[0].trade_date == date(2026, 3, 19)
        assert points[0].price_eur_mwh == 54.544
        assert points[0].source == "the_reference"

    def test_api_404(self):
        """JSON API returns 404 → GasPriceError."""
        mock_resp = httpx.Response(404, text="Not Found", request=_DUMMY_API_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            with pytest.raises(GasPriceError, match="HTTP 404"):
                fetch_gas_prices_from_api()

    def test_api_empty_json(self):
        """JSON API returns empty list → GasPriceError."""
        mock_resp = httpx.Response(200, json=[], request=_DUMMY_API_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            with pytest.raises(GasPriceError, match="empty or invalid"):
                fetch_gas_prices_from_api()

    def test_network_error(self):
        """Network failure → GasPriceError."""
        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.side_effect = httpx.RequestError("connection refused")

            with pytest.raises(GasPriceError, match="Network error"):
                fetch_gas_prices_from_api()


# ---------------------------------------------------------------------------
# CSV parsing tests
# ---------------------------------------------------------------------------


class TestParseCsv:
    def test_german_format(self):
        """Semicolon-delimited, German decimal comma → correct parse."""
        csv = "Gashandelstag;Referenzpreis (EUR/MWh)\n02.01.2025;34,52\n03.01.2025;35,10\n"
        points = _parse_the_csv(csv)
        assert len(points) == 2
        assert points[0].trade_date == date(2025, 1, 2)
        assert points[0].price_eur_mwh == 34.52
        assert points[1].trade_date == date(2025, 1, 3)
        assert points[1].price_eur_mwh == 35.10

    def test_empty_csv(self):
        """CSV with only header → empty list."""
        csv = "Gashandelstag;Referenzpreis (EUR/MWh)\n"
        assert _parse_the_csv(csv) == []

    def test_malformed_rows_skipped(self):
        """Invalid rows are silently skipped."""
        csv = "header\nbad_data\n02.01.2025;34,52\n;;\n"
        points = _parse_the_csv(csv)
        assert len(points) == 1
        assert points[0].price_eur_mwh == 34.52

    def test_sorted_output(self):
        """Output is sorted by date regardless of input order."""
        csv = "h\n03.01.2025;35,00\n01.01.2025;33,00\n02.01.2025;34,00\n"
        points = _parse_the_csv(csv)
        dates = [p.trade_date for p in points]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Integrated fetch_gas_prices tests (API + CSV fallback)
# ---------------------------------------------------------------------------


class TestFetchGasPrices:
    def test_final_api_used_for_historical(self):
        """fetch_gas_prices uses Final API for historical date ranges."""
        final_data = [
            {"gastag": "2025-03-05T05:00:00", "preisAusgleichsenergieNegativ": 39.5},
        ]
        mock_resp = httpx.Response(200, json=final_data, request=_DUMMY_FINAL_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            points = fetch_gas_prices(date(2025, 3, 5), date(2025, 3, 5))

        assert len(points) == 1
        assert points[0].price_eur_mwh == 39.5

    def test_no_data_raises_error(self):
        """Both APIs return no data → GasPriceError."""
        mock_resp = httpx.Response(200, json=[], request=_DUMMY_FINAL_REQUEST)

        with patch("app.services.bundesnetzagentur_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = lambda s: s
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = mock_resp

            with pytest.raises(GasPriceError, match="No THE gas price data"):
                fetch_gas_prices(date(2025, 3, 19), date(2025, 3, 19))
