"""
Weather router — wind forecast summary for the Overview page.

Endpoints:
  GET /api/v1/weather/wind-forecast-summary — avg/peak wind speed (m/s)
      over the next N hours, from Open-Meteo.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.openmeteo_client import OpenMeteoError, fetch_forecast

router = APIRouter(prefix="/weather", tags=["weather"])


def _kmh_to_ms(v: float) -> float:
    return v / 3.6


@router.get("/wind-forecast-summary")
def wind_forecast_summary(
    hours: int = Query(24, ge=1, le=168, description="Hours ahead (1–168)"),
):
    """
    Average and peak 100 m wind speed forecast over the next `hours` hours.
    Open-Meteo is queried for a single Swedish mid-south reference point
    (see openmeteo_client.py) — strong winds here correlate with strong
    spot-price deflation across SE3/SE4.
    """
    forecast_days = min(7, hours // 24 + 2)
    try:
        slots = fetch_forecast(forecast_days=forecast_days)
    except OpenMeteoError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    upcoming = [
        s for s in slots if s["target_utc"] >= now and s["target_utc"] <= end and s.get("wind_speed_100m") is not None
    ]
    if not upcoming:
        return {
            "hours_ahead": hours,
            "avg_wind_100m_ms": None,
            "peak_wind_100m_ms": None,
            "peak_at_utc": None,
            "sample_count": 0,
        }

    wind_vals_kmh = [s["wind_speed_100m"] for s in upcoming]
    peak_slot = max(upcoming, key=lambda s: s["wind_speed_100m"])
    return {
        "hours_ahead": hours,
        "avg_wind_100m_ms": round(_kmh_to_ms(sum(wind_vals_kmh) / len(wind_vals_kmh)), 1),
        "peak_wind_100m_ms": round(_kmh_to_ms(peak_slot["wind_speed_100m"]), 1),
        "peak_at_utc": peak_slot["target_utc"].isoformat(),
        "sample_count": len(upcoming),
    }
