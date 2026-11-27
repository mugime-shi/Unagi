"""
Global test fixtures.

The test suite runs inside the dev container, which loads backend/.env —
and that file holds PRODUCTION credentials (R2, Telegram). Any test that
reaches a code path doing real I/O with those settings would hit production:
on 2026-07-14 a publish test silently overwrote the live public feed on R2.
This fixture blanks every outbound-write credential for every test.

backend/.env (and formerly CI) also carries a real ENTSO-E API key. Route tests on
an empty SQLite DB fall back to a live ENTSO-E fetch when the key is set, so the
result would depend on the network and on the time of day. The key is blanked too.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _no_production_credentials(monkeypatch):
    monkeypatch.setattr(settings, "entsoe_api_key", "")
    monkeypatch.setattr(settings, "r2_endpoint", "")
    monkeypatch.setattr(settings, "r2_bucket", "")
    monkeypatch.setattr(settings, "r2_access_key_id", "")
    monkeypatch.setattr(settings, "r2_secret_access_key", "")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
