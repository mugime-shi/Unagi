"""
Pure backfill events (e.g. the Saturday 04:00 UTC {"backfill_generation": 7}) must not run the daily
steps: tomorrow's day-ahead prices / load forecast cannot exist yet.
"""

from unittest.mock import patch

from app.tasks import fetch_prices


def _ok(market):
    return {"market": market, "status": "ok"}


@patch("app.tasks.fetch_prices._send_notifications")
@patch("app.tasks.fetch_prices._publish_feed", return_value=[])
@patch("app.tasks.fetch_prices.fetch_load_forecast_date")
@patch("app.tasks.fetch_prices.fetch_dates")
@patch("app.tasks.fetch_prices.backfill_generation", return_value=[_ok("generation")])
def test_backfill_generation_does_not_fetch_tomorrow(mock_gen, mock_dates, mock_lf, mock_feed, mock_notify):
    result = fetch_prices.lambda_handler({"backfill_generation": 7}, None)

    assert mock_gen.call_count == len(fetch_prices.ALL_AREAS)
    mock_dates.assert_not_called()
    mock_lf.assert_not_called()
    mock_notify.assert_not_called()
    assert result["statusCode"] == 200


@patch("app.tasks.fetch_prices.fetch_dates", return_value=[])
@patch("app.tasks.fetch_prices.backfill_load_forecast", return_value=[_ok("load_forecast")])
def test_backfill_load_forecast_does_not_fetch_tomorrow_prices(mock_lf, mock_dates):
    fetch_prices.lambda_handler({"backfill_load_forecast": 7}, None)

    mock_dates.assert_not_called()
