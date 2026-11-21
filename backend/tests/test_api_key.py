"""Tests for the X-Unagi-Key API key middleware."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

SECRET = "test-secret-key-1234"
# Matches no route: a request the middleware lets through ends as the router's 404,
# so these tests never touch the DB or ENTSO-E.
PROBE = "/api/v1/__auth_probe__"


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
            resp = _client().get(PROBE)
            # 404 = passed the middleware and reached routing
            assert resp.status_code == 404


class TestApiKeyEnabled:
    """When api_key is set, middleware enforces the header."""

    def test_missing_key_returns_403(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get(PROBE)
            assert resp.status_code == 403
            assert resp.json()["detail"] == "Forbidden"

    def test_wrong_key_returns_403(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get(
                PROBE,
                headers={"X-Unagi-Key": "wrong-key"},
            )
            assert resp.status_code == 403

    def test_correct_key_passes(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get(
                PROBE,
                headers={"X-Unagi-Key": SECRET},
            )
            # 404 = passed the middleware and reached routing
            assert resp.status_code == 404

    def test_health_exempt_without_key(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().get("/health")
            assert resp.status_code == 200

    def test_options_exempt_without_key(self):
        with patch("app.middleware.api_key.settings") as mock:
            mock.api_key = SECRET
            resp = _client().options(PROBE)
            assert resp.status_code != 403
