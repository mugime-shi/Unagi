import logging

import httpx
import pytest

from app.logging_utils import install_log_redaction, redact_secrets
from app.services.entsoe_client import EntsoEError, fetch_day_ahead_prices

DUMMY = "dummy-token-0000"


def test_redact_secrets_masks_query_param():
    url = f"https://web-api.tp.entsoe.eu/api?securityToken={DUMMY}&documentType=A44"
    out = redact_secrets(url)
    assert DUMMY not in out
    assert "securityToken=REDACTED&documentType=A44" in out


def test_redact_secrets_leaves_other_text_alone():
    assert redact_secrets("no secrets here, key figures: 3") == "no secrets here, key figures: 3"


def test_log_record_factory_scrubs_any_logger(caplog):
    install_log_redaction()
    with caplog.at_level(logging.INFO):
        logging.getLogger("some.other.lib").info("GET %s", f"https://x/api?securityToken={DUMMY}&a=1")
    assert caplog.records
    assert DUMMY not in caplog.text
    assert "securityToken=REDACTED" in caplog.text


def test_traceback_is_scrubbed(caplog):
    install_log_redaction()
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError(f"boom https://x/api?securityToken={DUMMY}")
        except RuntimeError:
            logging.getLogger("app.test").exception("failed")
    assert DUMMY not in caplog.text


def test_httpx_request_url_not_logged_at_info(monkeypatch, caplog):
    """httpx's INFO 'HTTP Request: GET <url>' line must be suppressed, so the URL never reaches the logs."""
    install_log_redaction()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<ok/>"))
    with caplog.at_level(logging.INFO), httpx.Client(transport=transport) as client:
        client.get(f"https://web-api.tp.entsoe.eu/api?securityToken={DUMMY}")
    assert DUMMY not in caplog.text


def test_entsoe_network_error_message_has_no_token(monkeypatch):
    def boom(self, *args, **kwargs):
        raise httpx.ConnectError(f"failed for https://web-api.tp.entsoe.eu/api?securityToken={DUMMY}&x=1")

    monkeypatch.setattr(httpx.Client, "get", boom)
    from datetime import date

    with pytest.raises(EntsoEError) as excinfo:
        fetch_day_ahead_prices(date(2026, 1, 1), "SE3", api_key=DUMMY, eur_to_sek=11.0)
    assert DUMMY not in str(excinfo.value)
