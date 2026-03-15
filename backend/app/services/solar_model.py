"""
Solar generation estimation model (Layer 2).

Core formula:
  generation_kwh = panel_kwp × (radiation_wm2 / 1000) × performance_ratio

Where:
  panel_kwp         — Installed capacity (kWp). 1 kWp generates 1 kWh at 1000 W/m²
  radiation_wm2     — Hourly average global radiation (W/m²) from SMHI
  performance_ratio — System efficiency (temperature loss, wiring, inverter, ageing)
                      Typical range: 0.75–0.85. Default: 0.80

Two data modes:
  1. "smhi"      — Uses real hourly W/m² from weather_data table (preferred)
  2. "reference" — Falls back to Göteborg monthly-average lookup table when DB
                   has no data for the requested month. Generates a daily total
                   without hourly breakdown.

Göteborg (SE3) monthly reference radiation (kWh/m²/day):
  Source: DOMAIN_KNOWLEDGE.md (typical Swedish PV system sizing values)

Tax credit (skattereduktion):
  2025 and earlier: 0.60 SEK/kWh sold, up to min(sold_kwh, bought_kwh), annual cap 18,000 SEK
  2026 onwards:     abolished (= 0)
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.services.smhi_client import DEFAULT_STATION, get_weather_for_date_range

DEFAULT_PERFORMANCE_RATIO = 0.80

# Battery dispatch thresholds (relative to daily average spot price)
HIGH_PRICE_THRESHOLD = 1.20   # sell surplus / discharge battery when price > avg × this
LOW_PRICE_THRESHOLD  = 0.80   # charge battery / buy from grid when price < avg × this

# Tax credit (skattereduktion) — abolished from 2026-01-01
TAX_CREDIT_RATE_SEK = 0.60    # SEK per eligible kWh sold
TAX_CREDIT_ANNUAL_CAP = 18_000.0  # SEK per year
TAX_CREDIT_END_YEAR = 2025    # last year with credit

# Monthly average global radiation for Göteborg (kWh/m²/day)
# Key: month number (1–12)
MONTHLY_RADIATION_KWH_M2_DAY: dict[int, float] = {
    1:  0.3,
    2:  0.8,
    3:  1.8,
    4:  3.5,
    5:  5.0,
    6:  5.5,
    7:  5.2,
    8:  4.2,
    9:  2.5,
    10: 1.2,
    11: 0.4,
    12: 0.2,
}


# ---------------------------------------------------------------------------
# Core formula
# ---------------------------------------------------------------------------

def estimate_hourly_generation(
    radiation_wm2: float,
    panel_kwp: float,
    performance_ratio: float = DEFAULT_PERFORMANCE_RATIO,
) -> float:
    """
    Estimate PV output for one hour given an average radiation reading.

    SMHI parameter 11 gives hourly-mean W/m².
    Over 1 hour: W/m² × 1h = Wh/m²  →  /1000 = kWh/m²  →  × kWp = kWh generated.
    Negative radiation (sensor noise) is clamped to 0.
    """
    if radiation_wm2 <= 0:
        return 0.0
    return panel_kwp * (radiation_wm2 / 1000.0) * performance_ratio


# ---------------------------------------------------------------------------
# Monthly simulation
# ---------------------------------------------------------------------------

def simulate_month(
    panel_kwp: float,
    year: int,
    month: int,
    db: Session,
    performance_ratio: float = DEFAULT_PERFORMANCE_RATIO,
    station_id: int = DEFAULT_STATION,
) -> dict:
    """
    Estimate total solar generation for a calendar month.

    Tries real SMHI hourly data first; falls back to reference table.

    Returns:
        {
          "panel_kwp": 6.0,
          "performance_ratio": 0.80,
          "year": 2026, "month": 7,
          "total_generation_kwh": 712.4,
          "daily_avg_kwh": 22.98,
          "data_source": "smhi" | "reference",
          "hours_with_data": 744,          # smhi only
          "hourly_slots": [                # smhi only
            {"timestamp_utc": "...", "radiation_wm2": 320.0, "generation_kwh": 1.54},
            ...
          ]
        }
    """
    days_in_month = calendar.monthrange(year, month)[1]

    # --- Try real SMHI data ---
    start_utc = datetime(year, month, 1, 0, 0, tzinfo=timezone.utc)
    # End = first moment of next month (exclusive upper bound via <=)
    if month == 12:
        end_utc = datetime(year + 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    else:
        end_utc = datetime(year, month + 1, 1, 0, 0, tzinfo=timezone.utc)

    rows = get_weather_for_date_range(db, start_utc, end_utc, station_id=station_id)

    if rows:
        slots = []
        total = 0.0
        for r in rows:
            rad = float(r.global_radiation_wm2) if r.global_radiation_wm2 is not None else 0.0
            gen = estimate_hourly_generation(rad, panel_kwp, performance_ratio)
            total += gen
            slots.append({
                "timestamp_utc": r.timestamp_utc.isoformat(),
                "radiation_wm2": round(rad, 2),
                "generation_kwh": round(gen, 4),
            })
        return {
            "panel_kwp": panel_kwp,
            "performance_ratio": performance_ratio,
            "year": year,
            "month": month,
            "total_generation_kwh": round(total, 2),
            "daily_avg_kwh": round(total / days_in_month, 2),
            "data_source": "smhi",
            "hours_with_data": len(rows),
            "hourly_slots": slots,
        }

    # --- Fallback: reference table ---
    return simulate_month_reference(panel_kwp, year, month, performance_ratio)


def simulate_month_reference(
    panel_kwp: float,
    year: int,
    month: int,
    performance_ratio: float = DEFAULT_PERFORMANCE_RATIO,
) -> dict:
    """
    Estimate monthly generation using the Göteborg reference radiation table.
    No hourly breakdown — only a monthly total.
    """
    days_in_month = calendar.monthrange(year, month)[1]
    daily_radiation_kwh_m2 = MONTHLY_RADIATION_KWH_M2_DAY[month]

    # kWh/m²/day × days × kWp × performance_ratio
    total = panel_kwp * daily_radiation_kwh_m2 * days_in_month * performance_ratio

    return {
        "panel_kwp": panel_kwp,
        "performance_ratio": performance_ratio,
        "year": year,
        "month": month,
        "total_generation_kwh": round(total, 2),
        "daily_avg_kwh": round(total / days_in_month, 2),
        "data_source": "reference",
        "reference_radiation_kwh_m2_day": daily_radiation_kwh_m2,
    }


# ---------------------------------------------------------------------------
# Solar optimization (sell / store / self-consume)
# ---------------------------------------------------------------------------

def _get_hourly_spot(db: Session, year: int, month: int) -> dict[datetime, float]:
    """
    Return {hour_utc: avg_spot_sek_kwh} for the given month.
    15-min slots are averaged into 1-h buckets.
    Returns empty dict if no data in DB for that month.
    """
    from app.config import settings
    from app.services.price_service import get_prices_for_date_range

    days = calendar.monthrange(year, month)[1]
    rows = get_prices_for_date_range(
        db, date(year, month, 1), date(year, month, days), area=settings.default_area
    )
    hourly: dict[datetime, list[float]] = defaultdict(list)
    for r in rows:
        hour = r.timestamp_utc.replace(minute=0, second=0, microsecond=0)
        hourly[hour].append(float(r.price_sek_kwh))
    return {h: sum(v) / len(v) for h, v in hourly.items()}


def _run_hourly_sim(
    hourly_gen: dict[datetime, float],
    hourly_cons_kwh: float,
    hourly_spot: dict[datetime, float],
    battery_kwh: float,
    overhead_sek_kwh: float,
    vat_rate: float,
) -> dict:
    """
    Simulate hour-by-hour dispatch for one month.

    Dispatch rule (threshold-based):
      - price > daily_avg × HIGH → prefer to sell surplus / discharge battery for deficit
      - price < daily_avg × LOW  → prefer to charge battery / buy from grid (cheap)
      - otherwise                → self-consume first, then sell surplus / discharge for deficit

    Args:
        hourly_gen:      {timestamp_utc: generation_kwh}
        hourly_cons_kwh: uniform consumption per hour (kWh)
        hourly_spot:     {timestamp_utc: spot_sek_kwh}
        battery_kwh:     battery capacity (0 = no battery)
        overhead_sek_kwh: fixed per-kWh adder (margin + grid + tax + elcert), before VAT
        vat_rate:        VAT multiplier (e.g. 0.25)

    Returns aggregated monthly metrics dict.
    """
    # Build daily averages for threshold calculation
    daily_spot: dict[date, list[float]] = defaultdict(list)
    for ts, price in hourly_spot.items():
        daily_spot[ts.date()].append(price)
    daily_avg: dict[date, float] = {
        d: sum(v) / len(v) for d, v in daily_spot.items()
    }

    sold = bought = revenue = 0.0
    battery_soc = 0.0
    total_cons = hourly_cons_kwh * len(hourly_gen)

    for ts in sorted(hourly_gen):
        gen  = hourly_gen[ts]
        spot = hourly_spot.get(ts, 0.0)
        avg  = daily_avg.get(ts.date(), spot)
        net  = gen - hourly_cons_kwh

        is_high = spot > avg * HIGH_PRICE_THRESHOLD
        is_low  = spot < avg * LOW_PRICE_THRESHOLD

        if net >= 0:                    # surplus generation
            surplus = net
            if is_high or battery_kwh == 0:
                # High price window (or no battery): sell all surplus immediately.
                # Exporting at peak price maximises revenue.
                sold    += surplus
                revenue += surplus * spot
            else:
                # Low/normal price: store in battery first; sell only what doesn't fit.
                # Saved kWh will displace expensive grid purchases in later hours.
                charge = min(surplus, battery_kwh - battery_soc)
                battery_soc += charge
                leftover = surplus - charge
                sold    += leftover
                revenue += leftover * spot
        else:                           # deficit — generation < consumption
            deficit = -net
            if not is_low and battery_soc > 0:
                # Price is normal/high: discharge battery to cover the deficit.
                # Avoids buying at full retail when we already have stored energy.
                discharge    = min(deficit, battery_soc)
                battery_soc -= discharge
                bought      += deficit - discharge
            else:
                # Price is low (cheap to buy) or battery empty: purchase from grid.
                bought += deficit

    # Savings = energy not purchased from grid × average full retail price.
    # "Not purchased" = direct self-consumption + battery discharge — both avoid
    # paying margin + grid fee + energy tax + VAT on top of spot price.
    total_spots  = list(hourly_spot.values())
    avg_spot_all = sum(total_spots) / len(total_spots) if total_spots else 0.0
    avg_full_retail = (avg_spot_all + overhead_sek_kwh) * (1 + vat_rate)
    savings = (total_cons - bought) * avg_full_retail

    return {
        "self_consumed_kwh":    round(total_cons - bought, 2),
        "sold_to_grid_kwh":     round(sold, 2),
        "bought_from_grid_kwh": round(bought, 2),
        "revenue_sek":          round(revenue, 2),
        "savings_sek":          round(savings, 2),
        "avg_spot_sek_kwh":     round(avg_spot_all, 4),
    }


def optimize_solar_month(
    panel_kwp: float,
    battery_kwh: float,
    annual_consumption_kwh: float,
    year: int,
    month: int,
    db: Session,
    performance_ratio: float = DEFAULT_PERFORMANCE_RATIO,
) -> dict:
    """
    Full monthly solar optimization: generation → dispatch → revenue → tax credit.

    Uses real SMHI hourly data when available; falls back to reference table.
    Requires spot price data in DB for financial calculations.

    Returns structured dict ready for the API response.
    Raises ValueError if no spot price data is found for the requested month.
    """
    from app.services.consumption_optimizer import (
        ELCERT_SEK, ENERGY_TAX_SEK, GRID_FEE_SEK, MARGIN_SEK, VAT_RATE,
    )
    overhead = MARGIN_SEK + GRID_FEE_SEK + ENERGY_TAX_SEK + ELCERT_SEK

    days_in_month   = calendar.monthrange(year, month)[1]
    hours_in_month  = days_in_month * 24
    hourly_cons_kwh = annual_consumption_kwh / 8760.0   # uniform

    # --- Generation data ---
    gen_result  = simulate_month(panel_kwp, year, month, db, performance_ratio)
    data_source = gen_result["data_source"]

    # --- Spot prices (required) ---
    hourly_spot = _get_hourly_spot(db, year, month)
    if not hourly_spot:
        raise ValueError(
            f"No spot price data for {year}-{month:02d}. "
            "Run fetch_prices for that month first."
        )

    # --- Build hourly generation dict ---
    if data_source == "smhi" and "hourly_slots" in gen_result:
        hourly_gen: dict[datetime, float] = {
            datetime.fromisoformat(s["timestamp_utc"]): s["generation_kwh"]
            for s in gen_result["hourly_slots"]
        }
    else:
        # Reference mode: distribute total generation uniformly over hours with spot data
        gen_per_hour = gen_result["total_generation_kwh"] / hours_in_month
        hourly_gen = {ts: gen_per_hour for ts in hourly_spot}

    # --- Simulate without battery (baseline) ---
    base = _run_hourly_sim(
        hourly_gen, hourly_cons_kwh, hourly_spot,
        battery_kwh=0.0, overhead_sek_kwh=overhead, vat_rate=VAT_RATE,
    )

    # --- Simulate with battery (if any) ---
    if battery_kwh > 0:
        opt = _run_hourly_sim(
            hourly_gen, hourly_cons_kwh, hourly_spot,
            battery_kwh=battery_kwh, overhead_sek_kwh=overhead, vat_rate=VAT_RATE,
        )
    else:
        opt = base

    battery_effect_sek = round(
        (opt["revenue_sek"] + opt["savings_sek"])
        - (base["revenue_sek"] + base["savings_sek"]), 2
    )

    total_benefit      = round(opt["revenue_sek"] + opt["savings_sek"], 2)
    total_benefit_base = round(base["revenue_sek"] + base["savings_sek"], 2)

    # --- Tax credit (skattereduktion) ---
    credit_applies = year <= TAX_CREDIT_END_YEAR
    # Swedish tax law caps the credit at min(sold, bought).
    # Households that export more than they import cannot claim credit on the excess —
    # this prevents pure generators from benefiting from a consumer-oriented subsidy.
    eligible_kwh   = min(opt["sold_to_grid_kwh"], opt["bought_from_grid_kwh"])
    monthly_credit = round(eligible_kwh * TAX_CREDIT_RATE_SEK, 2) if credit_applies else 0.0

    eligible_kwh_base  = min(base["sold_to_grid_kwh"], base["bought_from_grid_kwh"])
    monthly_credit_base = round(eligible_kwh_base * TAX_CREDIT_RATE_SEK, 2) if credit_applies else 0.0

    return {
        "month": f"{year}-{month:02d}",
        "panel_kwp": panel_kwp,
        "battery_kwh": battery_kwh,
        "performance_ratio": performance_ratio,
        "data_source": data_source,
        # Generation
        "solar_generation_kwh": gen_result["total_generation_kwh"],
        # Dispatch (with battery / optimized)
        "self_consumed_kwh":    opt["self_consumed_kwh"],
        "sold_to_grid_kwh":     opt["sold_to_grid_kwh"],
        "bought_from_grid_kwh": opt["bought_from_grid_kwh"],
        # Financials (with battery / optimized)
        "avg_spot_sek_kwh":                 opt["avg_spot_sek_kwh"],
        "revenue_sek":                       opt["revenue_sek"],
        "savings_from_self_consumption_sek": opt["savings_sek"],
        "battery_effect_sek":                battery_effect_sek,
        "total_benefit_without_tax_credit_sek": total_benefit,
        "total_benefit_with_tax_credit_sek":    round(total_benefit + monthly_credit, 2),
        # Baseline (no battery) — for with/without battery comparison in UI
        "baseline": {
            "self_consumed_kwh":    base["self_consumed_kwh"],
            "sold_to_grid_kwh":     base["sold_to_grid_kwh"],
            "bought_from_grid_kwh": base["bought_from_grid_kwh"],
            "revenue_sek":          base["revenue_sek"],
            "savings_sek":          base["savings_sek"],
            "total_benefit_sek":    total_benefit_base,
            "total_benefit_with_tax_credit_sek": round(total_benefit_base + monthly_credit_base, 2),
        },
        # Tax credit detail
        "tax_credit": {
            "applies": credit_applies,
            "rate_sek_kwh": TAX_CREDIT_RATE_SEK,
            "eligible_kwh": round(eligible_kwh, 2),
            "monthly_credit_sek": monthly_credit,
            "annual_projected_sek": round(monthly_credit * 12, 2),
            "annual_cap_sek": TAX_CREDIT_ANNUAL_CAP,
            "note": (
                "Skattereduktion applies until end of 2025"
                if credit_applies else
                "Skattereduktion abolished from 2026-01-01"
            ),
        },
    }
