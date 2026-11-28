"""
Consumption cost optimizer for Layer 1.

Compares three scenarios for a given monthly electricity consumption:
  1. Fixed-price contract  — user pays a flat per-kWh rate
  2. Dynamic (no shift)    — pays spot avg + overhead, no behaviour change
  3. Dynamic (optimized)   — shifts a fraction of daily usage to cheapest hours

Swedish electricity price components (SE3 / Göteborg, 2025):
  Spot price    : market (Nord Pool, from DB)
  Margin        : 0.086 SEK/kWh  (Tibber typical)
  Grid fee      : 0.300 SEK/kWh  (Göteborg Energi SE3 average)
  Energy tax    : 0.439 SEK/kWh  (2025 rate)
  Elcert        : 0.010 SEK/kWh  (electricity certificate surcharge)
  VAT           : 25 %            (applied on the sum of all above)

All output prices are per kWh including VAT.
"""

from dataclasses import dataclass

# Default price components (öre/kWh → SEK/kWh)
MARGIN_SEK = 0.086
GRID_FEE_SEK = 0.300
ENERGY_TAX_SEK = 0.439
ELCERT_SEK = 0.010
VAT_RATE = 0.25

# Optimization defaults
DEFAULT_SHIFTABLE_PCT = 0.30  # 30 % of daily consumption can be shifted
DEFAULT_SHIFT_HOURS = 8  # shift to the cheapest 8 hours per day


@dataclass
class PriceComponents:
    margin_sek_kwh: float = MARGIN_SEK
    grid_fee_sek_kwh: float = GRID_FEE_SEK
    energy_tax_sek_kwh: float = ENERGY_TAX_SEK
    elcert_sek_kwh: float = ELCERT_SEK
    vat_rate: float = VAT_RATE

    @property
    def overhead_sek_kwh(self) -> float:
        """Fixed per-kWh adder on top of spot, before VAT."""
        return self.margin_sek_kwh + self.grid_fee_sek_kwh + self.energy_tax_sek_kwh + self.elcert_sek_kwh

    def total_per_kwh(self, spot_sek_kwh: float) -> float:
        """All-in per-kWh cost including VAT."""
        return (spot_sek_kwh + self.overhead_sek_kwh) * (1 + self.vat_rate)


def _avg_spot_dynamic(hourly_prices: list[float]) -> float:
    """Unweighted average spot price across all hours (no behaviour change)."""
    if not hourly_prices:
        return 0.0
    return sum(hourly_prices) / len(hourly_prices)


def _avg_spot_optimized(
    daily_price_groups: list[list[float]],
    shiftable_pct: float = DEFAULT_SHIFTABLE_PCT,
    shift_hours: int = DEFAULT_SHIFT_HOURS,
) -> float:
    """
    Weighted average spot price when the user can shift `shiftable_pct` of
    daily consumption to the cheapest `shift_hours` per day.

    Physical interpretation:
      - `shiftable_pct` of daily kWh can be freely moved to the cheapest hours
        (e.g. EV charging, washing machine, dishwasher)
      - `(1 - shiftable_pct)` is baseline load that cannot be shifted and
        is assumed to spread uniformly across all hours

    This always gives avg_optimized <= avg_dynamic because:
      shiftable * cheap_avg + (1-shiftable) * full_avg <= full_avg
      ⟺ shiftable * (cheap_avg - full_avg) <= 0  (true, since cheap_avg <= full_avg)
    """
    if not daily_price_groups:
        return 0.0

    total_weighted = 0.0
    total_days = 0

    for prices in daily_price_groups:
        n = len(prices)
        if n == 0:
            continue
        sorted_p = sorted(prices)
        cheap_avg = sum(sorted_p[: min(shift_hours, n)]) / min(shift_hours, n)
        full_avg = sum(prices) / n

        # shiftable fraction goes to cheapest hours; rest stays at full-day average
        day_weighted_avg = shiftable_pct * cheap_avg + (1 - shiftable_pct) * full_avg
        total_weighted += day_weighted_avg
        total_days += 1

    return total_weighted / total_days if total_days else 0.0


def simulate(
    monthly_kwh: float,
    fixed_price_sek_kwh: float,
    spot_prices_sek: list[float],
    daily_price_groups: list[list[float]],
    components: PriceComponents | None = None,
    shiftable_pct: float = DEFAULT_SHIFTABLE_PCT,
    shift_hours: int = DEFAULT_SHIFT_HOURS,
    monthly_avg_spot_sek: float | None = None,
) -> dict:
    """
    Run the four-scenario comparison.

    Args:
        monthly_kwh:           Monthly consumption in kWh.
        fixed_price_sek_kwh:   All-in fixed contract price (incl. VAT).
        spot_prices_sek:       Flat list of all hourly spot prices in the period (SEK/kWh).
        daily_price_groups:    Same data grouped by day [[h0,h1,...], [h0,h1,...], ...].
        components:            Price component settings (defaults to SE3 2025 values).
        shiftable_pct:         Fraction of consumption that can be shifted (0–1).
        shift_hours:           How many cheapest hours per day to shift into.
        monthly_avg_spot_sek:  Current-month average spot price (SEK/kWh), for
                               Göteborg Energi-style monthly-average contracts.
                               If None, this scenario is omitted from the result.

    Returns:
        A dict with fixed / dynamic / optimized (+ optional monthly_avg) breakdown.
    """
    if components is None:
        components = PriceComponents()

    # --- Fixed ---
    fixed_monthly = monthly_kwh * fixed_price_sek_kwh

    # --- Dynamic (no shift) ---
    avg_spot = _avg_spot_dynamic(spot_prices_sek)
    dynamic_per_kwh = components.total_per_kwh(avg_spot)
    dynamic_monthly = monthly_kwh * dynamic_per_kwh

    # --- Optimized ---
    opt_spot = _avg_spot_optimized(daily_price_groups, shiftable_pct, shift_hours)
    optimized_per_kwh = components.total_per_kwh(opt_spot)
    optimized_monthly = monthly_kwh * optimized_per_kwh

    def _savings(cost: float) -> dict:
        diff = fixed_monthly - cost
        pct = (diff / fixed_monthly * 100) if fixed_monthly else 0.0
        return {"savings_vs_fixed_sek": round(diff, 2), "savings_pct": round(pct, 1)}

    result = {
        "monthly_kwh": monthly_kwh,
        "price_components": {
            "margin_sek_kwh": components.margin_sek_kwh,
            "grid_fee_sek_kwh": components.grid_fee_sek_kwh,
            "energy_tax_sek_kwh": components.energy_tax_sek_kwh,
            "elcert_sek_kwh": components.elcert_sek_kwh,
            "vat_rate": components.vat_rate,
        },
        "fixed": {
            "price_per_kwh_sek": round(fixed_price_sek_kwh, 4),
            "monthly_cost_sek": round(fixed_monthly, 2),
        },
        "dynamic": {
            "avg_spot_sek_kwh": round(avg_spot, 4),
            "total_per_kwh_sek": round(dynamic_per_kwh, 4),
            "monthly_cost_sek": round(dynamic_monthly, 2),
            **_savings(dynamic_monthly),
        },
        "optimized": {
            "description": (f"Shift {int(shiftable_pct * 100)}% of daily consumption to cheapest {shift_hours}h"),
            "avg_spot_sek_kwh": round(opt_spot, 4),
            "total_per_kwh_sek": round(optimized_per_kwh, 4),
            "monthly_cost_sek": round(optimized_monthly, 2),
            **_savings(optimized_monthly),
        },
    }

    # --- Monthly average contract (e.g. Göteborg Energi) ---
    if monthly_avg_spot_sek is not None:
        mavg_per_kwh = components.total_per_kwh(monthly_avg_spot_sek)
        mavg_monthly = monthly_kwh * mavg_per_kwh
        result["monthly_avg"] = {
            "avg_spot_sek_kwh": round(monthly_avg_spot_sek, 4),
            "total_per_kwh_sek": round(mavg_per_kwh, 4),
            "monthly_cost_sek": round(mavg_monthly, 2),
            **_savings(mavg_monthly),
        }

    return result
