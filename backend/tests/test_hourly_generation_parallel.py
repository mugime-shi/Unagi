"""hourly_generation runs its 8 (area x date) fetches concurrently, preserving result order."""

import time
from datetime import date, timedelta
from unittest.mock import patch

from app.tasks import fetch_prices


def _slow_ok(gen_date, area):
    time.sleep(0.3)
    return {"date": gen_date.isoformat(), "market": "generation", "status": "ok", "rows": 1, "area": area}


def _expected_order():
    today = date.today()
    yesterday = today - timedelta(days=1)
    return [(d.isoformat(), a) for a in fetch_prices.ALL_AREAS for d in (yesterday, today)]


@patch("app.tasks.fetch_prices.fetch_generation_date", side_effect=_slow_ok)
def test_hourly_generation_runs_concurrently_in_order(mock_gen):
    start = time.monotonic()
    result = fetch_prices.lambda_handler({"hourly_generation": True}, None)
    elapsed = time.monotonic() - start

    assert result["statusCode"] == 200
    assert result["mode"] == "hourly_generation"
    assert mock_gen.call_count == 8
    assert [(r["date"], r["area"]) for r in result["results"]] == _expected_order()
    assert elapsed < 1.5  # serial would be >= 2.4s


def test_hourly_generation_unexpected_exception_keeps_other_results():
    def fake(gen_date, area):
        if (area, gen_date) == ("SE2", date.today()):
            raise RuntimeError("boom")
        return _slow_ok(gen_date, area)

    with patch("app.tasks.fetch_prices.fetch_generation_date", side_effect=fake):
        result = fetch_prices.lambda_handler({"hourly_generation": True}, None)

    assert result["statusCode"] == 207
    results = result["results"]
    assert len(results) == 8
    statuses = [r["status"] for r in results]
    assert statuses.count("error") == 1
    bad = results[3]  # SE2 today: area index 1 * 2 + 1
    assert bad["status"] == "error" and bad["error"] == "boom"
    assert bad["date"] == date.today().isoformat() and bad["market"] == "generation"
    assert all(r["status"] == "ok" for i, r in enumerate(results) if i != 3)
