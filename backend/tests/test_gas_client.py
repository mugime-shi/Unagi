"""
Tests for bundesnetzagentur_client.py — no real API calls, all mocked via httpx.

Covers:
- Final / preliminary (Vorlaeufig) JSON API parsing on the new api.tradinghub.eu host
- Fallback to the legacy host when the new one errors or returns no rows
- Legacy CSV parsing (pre-2026 historical data)
- HTTP error / network error handling
- Graceful degradation (API→CSV fallback)
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.bundesnetzagentur_client import (
    THE_FINAL_API_URL,
    THE_FINAL_API_URL_LEGACY,
    THE_PRELIMINARY_API_URL,
    THE_PREISMONITOR_URL_LEGACY,
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


def _routed_client(routes: dict):
    """Patch httpx.Client so each URL gets its own response (or raises, if the value is an exception)."""

    def get(url, params=None):
        result = routes[url]
        if isinstance(result, Exception):
            raise result
        return result

    patcher = patch("app.services.bundesnetzagentur_client.httpx.Client")
    MockClient = patcher.start()
    MockClient.return_value.__enter__ = lambda s: s
    MockClient.return_value.__exit__ = MagicMock(return_value=False)
    MockClient.return_value.get.side_effect = get
    return patcher


def _ok(json_data):
    return httpx.Response(200, json=json_data, request=_DUMMY_FINAL_REQUEST)


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

    def test_new_host_t00_gastag(self):
        """New host uses T00:00:00 gastag timestamps → still maps to the right date."""
        patcher = _routed_client(
            {
                THE_FINAL_API_URL: _ok(
                    [
                        {"gastag": "2026-10-25T00:00:00", "preisAusgleichsenergieNegativ": 79.931},
                        {"gastag": "2026-10-26T00:00:00", "preisAusgleichsenergieNegativ": 78.68},
                    ]
                )
            }
        )
        try:
            points = fetch_gas_prices_from_final_api(date(2026, 10, 25), date(2026, 10, 26))
        finally:
            patcher.stop()

        assert [(p.trade_date, p.price_eur_mwh) for p in points] == [
            (date(2026, 10, 25), 79.931),
            (date(2026, 10, 26), 78.68),
        ]

    def test_falls_back_to_legacy_when_new_empty(self, caplog):
        """New host returns [] → legacy host is used, with a WARNING."""
        legacy = _ok([{"gastag": "2026-08-25T05:00:00", "preisAusgleichsenergieNegativ": 30.0}])
        patcher = _routed_client({THE_FINAL_API_URL: _ok([]), THE_FINAL_API_URL_LEGACY: legacy})
        try:
            with caplog.at_level("WARNING"):
                points = fetch_gas_prices_from_final_api(date(2026, 8, 25), date(2026, 8, 25))
        finally:
            patcher.stop()

        assert [p.price_eur_mwh for p in points] == [30.0]
        assert any("falling back" in r.message and r.levelname == "WARNING" for r in caplog.records)

    def test_falls_back_to_legacy_when_new_errors(self):
        """New host network error → legacy host is used."""
        legacy = _ok([{"gastag": "2026-08-25T05:00:00", "preisAusgleichsenergieNegativ": 30.0}])
        patcher = _routed_client(
            {THE_FINAL_API_URL: httpx.RequestError("boom"), THE_FINAL_API_URL_LEGACY: legacy},
        )
        try:
            points = fetch_gas_prices_from_final_api(date(2026, 8, 25), date(2026, 8, 25))
        finally:
            patcher.stop()

        assert len(points) == 1

    def test_both_error_raises(self):
        patcher = _routed_client(
            {
                THE_FINAL_API_URL: httpx.Response(500, text="x", request=_DUMMY_FINAL_REQUEST),
                THE_FINAL_API_URL_LEGACY: httpx.RequestError("down"),
            }
        )
        try:
            with pytest.raises(GasPriceError, match="HTTP 500"):
                fetch_gas_prices_from_final_api(date(2026, 8, 25), date(2026, 8, 25))
        finally:
            patcher.stop()

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

    def test_new_endpoint_drops_placeholder_and_future_rows(self):
        """Vorlaeufig: 0-price placeholder for the next gas-day and future dates are dropped."""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        patcher = _routed_client(
            {
                THE_PRELIMINARY_API_URL: _ok(
                    [
                        {"gastag": f"{tomorrow}T06:00:00", "preisAusgleichsenergieNegativ": 0},
                        {"gastag": f"{today}T06:00:00", "preisAusgleichsenergieNegativ": 84.011},
                        {"gastag": f"{tomorrow}T06:00:00", "preisAusgleichsenergieNegativ": 12.0},
                        {"gastag": f"{today - timedelta(days=1)}T06:00:00", "preisAusgleichsenergieNegativ": None},
                    ]
                )
            }
        )
        try:
            points = fetch_gas_prices_from_api()
        finally:
            patcher.stop()

        assert [(p.trade_date, p.price_eur_mwh) for p in points] == [(today, 84.011)]

    def test_falls_back_to_legacy_preismonitor_fields(self):
        """New endpoint empty → legacy host with the old gasTag / negativer_* field names."""
        today = date.today()
        legacy = _ok([{"gasTag": f"{today}T06:00:00+01:00", "negativer_Ausgleichsenergiepreis": 54.544}])
        patcher = _routed_client({THE_PRELIMINARY_API_URL: _ok([]), THE_PREISMONITOR_URL_LEGACY: legacy})
        try:
            points = fetch_gas_prices_from_api()
        finally:
            patcher.stop()

        assert [(p.trade_date, p.price_eur_mwh) for p in points] == [(today, 54.544)]

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

            with pytest.raises(GasPriceError, match="no usable rows"):
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


    def test_falls_back_to_legacy_final_via_fetch_gas_prices(self):
        """End to end: new Final host empty → legacy Final host serves the range."""
        legacy = _ok([{"gastag": "2025-03-05T05:00:00", "preisAusgleichsenergieNegativ": 39.5}])
        patcher = _routed_client({THE_FINAL_API_URL: _ok([]), THE_FINAL_API_URL_LEGACY: legacy})
        try:
            points = fetch_gas_prices(date(2025, 3, 5), date(2025, 3, 5))
        finally:
            patcher.stop()

        assert [p.price_eur_mwh for p in points] == [39.5]

    def test_both_hosts_empty_raises(self):
        patcher = _routed_client({THE_FINAL_API_URL: _ok([]), THE_FINAL_API_URL_LEGACY: _ok([])})
        try:
            with pytest.raises(GasPriceError, match="No THE gas price data"):
                fetch_gas_prices(date(2025, 3, 5), date(2025, 3, 5))
        finally:
            patcher.stop()
