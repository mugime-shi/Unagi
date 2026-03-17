"""
Riksbank SWEA API client — fetches the daily EUR/SEK exchange rate.

Endpoint: GET https://api.riksbank.se/swea/v1/Observations/Latest/SEKEURPMI
Returns: {"date": "YYYY-MM-DD", "value": 10.769}

No authentication required. Published every Swedish business day at 16:15.
On weekends/holidays the latest available rate is returned.
"""

import logging
from functools import lru_cache
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.riksbank.se/swea/v1/Observations/Latest/SEKEURPMI"
_FALLBACK_RATE = 11.0
_TIMEOUT = 5.0  # seconds


class RiksbankError(Exception):
    pass


def fetch_eur_sek_rate() -> tuple[float, date | None]:
    """
    Fetch the latest EUR/SEK rate from Riksbank.

    Returns (rate, published_date). On failure, returns (_FALLBACK_RATE, None).
    """
    try:
        resp = httpx.get(_BASE_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["value"])
        pub_date = date.fromisoformat(data["date"])
        logger.info("Riksbank EUR/SEK: %.4f (published %s)", rate, pub_date)
        return rate, pub_date
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("Riksbank API failed, using fallback %.1f: %s", _FALLBACK_RATE, e)
        return _FALLBACK_RATE, None


@lru_cache(maxsize=1)
def _cached_rate_for_date(today: date) -> tuple[float, date | None]:
    """Cache the rate per calendar day (avoids redundant API calls within the same day)."""
    return fetch_eur_sek_rate()


def get_eur_sek_rate() -> float:
    """
    Get the current EUR/SEK rate (cached per day).

    Used by entsoe_client and esett_client for EUR/MWh → SEK/kWh conversion.
    Falls back to 11.0 on API failure.
    """
    rate, _ = _cached_rate_for_date(date.today())
    return rate
