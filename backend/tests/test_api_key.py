"""Tests for the X-Namazu-Key API key middleware."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

SECRET = "test-secret-key-1234"


def _client():
    return TestClient(app)


class TestApiKeyDisabled:
    """When api_key is empty (default), middleware is a no-op."""

    def test_request_without_key_passes(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = ""
            resp = _client().get("/health")
            assert resp.status_code == 200

    def test_any_endpoint_passes_without_key(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = ""
            resp = _client().get("/api/v1/prices/today")
            # May return 200 or 500 (no DB), but NOT 403
            assert resp.status_code != 403


class TestApiKeyEnabled:
    """When api_key is set, middleware enforces the header."""

    def test_missing_key_returns_403(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get("/api/v1/prices/today")
            assert resp.status_code == 403
            assert resp.json()["detail"] == "Forbidden"

    def test_wrong_key_returns_403(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get(
                "/api/v1/prices/today",
                headers={"X-Namazu-Key": "wrong-key"},
            )
            assert resp.status_code == 403

    def test_correct_key_passes(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get(
                "/api/v1/prices/today",
                headers={"X-Namazu-Key": SECRET},
            )
            # Should not be 403 (may be 500 due to no DB, but auth passed)
            assert resp.status_code != 403

    def test_health_exempt_without_key(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get("/health")
            assert resp.status_code == 200

    def test_options_exempt_without_key(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().options("/api/v1/prices/today")
            assert resp.status_code != 403
