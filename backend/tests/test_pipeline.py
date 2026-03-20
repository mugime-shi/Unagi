"""Tests for the split midnight_collect / predict_only pipeline."""

from datetime import date
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# midnight_collect handler
# ---------------------------------------------------------------------------


@patch("app.tasks.fetch_prices._send_pipeline_alert")
@patch("app.tasks.fetch_prices._fetch_gas_prices", return_value={"market": "gas_price", "status": "ok", "rows": 5})
@patch("app.tasks.fetch_prices._fetch_weather_forecast", return_value={"market": "weather_forecast", "status": "ok"})
@patch(
    "app.tasks.fetch_prices.fetch_load_forecast_date",
    return_value={"date": "2026-03-20", "market": "load_forecast", "status": "ok", "rows": 24},
)
@patch(
    "app.tasks.fetch_prices.fetch_balancing_date",
    return_value={"date": "2026-03-19", "market": "balancing", "status": "ok", "rows": 24},
)
@patch(
    "app.tasks.fetch_prices.fetch_generation_date",
    return_value={"date": "2026-03-19", "market": "generation", "status": "ok", "rows": 24},
)
def test_midnight_collect_calls_fetch_not_predict(mock_gen, mock_bal, mock_lf, mock_weather, mock_gas, mock_alert):
    from app.tasks.fetch_prices import lambda_handler

    with patch("app.tasks.fetch_prices._record_predictions") as mock_predict:
        result = lambda_handler({"midnight_collect": True}, None)

    assert result["mode"] == "midnight_collect"
    assert result["statusCode"] == 200
    assert mock_gen.called
    assert mock_bal.called
    assert mock_lf.called
    assert mock_weather.called
    assert mock_gas.called
    mock_predict.assert_not_called()
    mock_alert.assert_not_called()


@patch("app.tasks.fetch_prices._send_pipeline_alert")
@patch("app.tasks.fetch_prices._fetch_gas_prices", return_value={"market": "gas_price", "status": "ok", "rows": 5})
@patch("app.tasks.fetch_prices._fetch_weather_forecast", return_value={"market": "weather_forecast", "status": "ok"})
@patch(
    "app.tasks.fetch_prices.fetch_load_forecast_date",
    return_value={"date": "2026-03-20", "market": "load_forecast", "status": "error", "error": "timeout"},
)
@patch(
    "app.tasks.fetch_prices.fetch_balancing_date",
    return_value={"date": "2026-03-19", "market": "balancing", "status": "ok", "rows": 24},
)
@patch(
    "app.tasks.fetch_prices.fetch_generation_date",
    return_value={"date": "2026-03-19", "market": "generation", "status": "ok", "rows": 24},
)
def test_midnight_collect_alerts_on_failure(mock_gen, mock_bal, mock_lf, mock_weather, mock_gas, mock_alert):
    from app.tasks.fetch_prices import lambda_handler

    result = lambda_handler({"midnight_collect": True}, None)

    assert result["statusCode"] == 207
    mock_alert.assert_called_once()
    call_args = mock_alert.call_args
    assert call_args[0][0] == "midnight_collect"
    results = call_args[0][1]
    failed = [r for r in results if r["status"] == "error"]
    assert len(failed) >= 1


# ---------------------------------------------------------------------------
# predict_only handler — failure reporting
# ---------------------------------------------------------------------------


@patch("app.tasks.fetch_prices._record_predictions", return_value=[])
def test_predict_only_returns_200_on_success(mock_predict):
    from app.tasks.fetch_prices import lambda_handler

    result = lambda_handler({"predict_only": True}, None)

    assert result["statusCode"] == 200
    assert result["mode"] == "predict_only"
    assert result["failures"] == []


@patch(
    "app.tasks.fetch_prices._record_predictions",
    return_value=[{"market": "lgbm SE3", "status": "error", "error": "libgomp missing"}],
)
def test_predict_only_returns_207_on_failure(mock_predict):
    from app.tasks.fetch_prices import lambda_handler

    result = lambda_handler({"predict_only": True}, None)

    assert result["statusCode"] == 207
    assert len(result["failures"]) == 1


@patch("app.tasks.fetch_prices._record_predictions", return_value=[])
def test_predict_only_passes_target_date(mock_predict):
    from app.tasks.fetch_prices import lambda_handler

    result = lambda_handler({"predict_only": True, "target_date": "2026-03-19"}, None)

    assert result["target_date"] == "2026-03-19"
    mock_predict.assert_called_once()
    _, kwargs = mock_predict.call_args
    assert kwargs["target_date"] == date(2026, 3, 19)


# ---------------------------------------------------------------------------
# send_pipeline_alert
# ---------------------------------------------------------------------------


def test_send_pipeline_alert_skips_when_not_configured():
    from app.services.telegram_service import send_pipeline_alert

    with patch("app.services.telegram_service.settings") as mock_settings:
        mock_settings.telegram_bot_token = ""
        mock_settings.telegram_chat_id = ""
        result = send_pipeline_alert(
            "test_step",
            [{"market": "gen", "status": "error"}, {"market": "bal", "status": "ok"}],
        )
    assert result["status"] == "skipped"


@patch("app.services.telegram_service.httpx.Client")
def test_send_pipeline_alert_sends_message(mock_client_cls):
    from app.services.telegram_service import send_pipeline_alert

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    with patch("app.services.telegram_service.settings") as mock_settings:
        mock_settings.telegram_bot_token = "test-token"
        mock_settings.telegram_chat_id = "123"
        result = send_pipeline_alert(
            "midnight_collect",
            [
                {"market": "generation", "date": "2026-03-19", "status": "error", "error": "timeout"},
                {"market": "balancing", "status": "ok"},
            ],
        )

    assert result["status"] == "ok"
    assert result["failed_count"] == 1
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert "midnight" in call_kwargs["json"]["text"]
    assert "collect" in call_kwargs["json"]["text"]
