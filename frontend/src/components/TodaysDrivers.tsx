"use client";

import { useMemo } from "react";
import { useHydroReservoir } from "../hooks/useHydroReservoir";
import { useWindForecastSummary } from "../hooks/useWindForecastSummary";
import type { PricePoint } from "../types/index";

/**
 * "Today's drivers" — the Sweden-wide signals that help explain why today's
 * price looks the way it does. Migrated off the Overview (which stays a clean
 * "what's happening now" view) into the Price tab, next to the price chart.
 *
 * Volatility is computed from the selected zone's own prices (no extra fetch);
 * hydro + wind are national.
 */
function computeVolatility(
  prices: PricePoint[],
): { ratio: number; spread: number } | null {
  if (!prices?.length) return null;
  const byHour = new Map<number, number[]>();
  for (const p of prices) {
    const hour = parseInt(
      new Date(p.timestamp_utc).toLocaleTimeString("sv-SE", {
        timeZone: "Europe/Stockholm",
        hour: "2-digit",
        hour12: false,
      }),
      10,
    );
    const arr = byHour.get(hour) ?? [];
    arr.push(p.price_sek_kwh);
    byHour.set(hour, arr);
  }
  const avgs = Array.from(byHour.values()).map(
    (a) => a.reduce((s, v) => s + v, 0) / a.length,
  );
  if (avgs.length < 2) return null;
  const max = Math.max(...avgs);
  const min = Math.min(...avgs);
  if (min <= 0) return null;
  return {
    ratio: +(max / min).toFixed(1),
    spread: Math.round((max - min) * 100), // öre
  };
}

/**
 * A short plain-language read of the drivers above. Wind and hydro genuinely
 * move spot prices (the card tooltips already say so); we describe their
 * direction and the day's price swing without overclaiming precise causation.
 */
function driversSentence(
  wind: { avg_wind_100m_ms?: number | null } | null,
  hydro: { change_pct?: number | null } | null,
  volatility: { ratio: number; spread: number } | null,
): string | null {
  const clauses: string[] = [];
  const w = wind?.avg_wind_100m_ms;
  if (w != null) {
    const level = w >= 8 ? "Strong" : w >= 5 ? "Moderate" : "Light";
    const effect = w >= 5 ? "easing prices" : "adding little downward push";
    clauses.push(`${level} wind (${w} m/s), ${effect}`);
  }
  const chg = hydro?.change_pct;
  if (chg != null) {
    clauses.push(
      chg >= 0
        ? `reservoirs filling (+${chg}%/wk)`
        : `reservoirs drawing down (${chg}%/wk)`,
    );
  }
  let s = clauses.join("; ");
  if (volatility) {
    const swing =
      volatility.ratio >= 3
        ? `big intraday swings (${volatility.ratio}×, ${volatility.spread} öre between cheap and peak hours)`
        : `a fairly flat day (${volatility.ratio}×)`;
    s = s ? `${s}. Today shows ${swing}.` : `Today shows ${swing}.`;
  } else if (s) {
    s += ".";
  }
  return s || null;
}

export function TodaysDrivers({ prices }: { prices: PricePoint[] }) {
  const { data: hydroReservoir } = useHydroReservoir();
  const { data: windForecast } = useWindForecastSummary(24);
  const volatility = useMemo(() => computeVolatility(prices), [prices]);
  const sentence = driversSentence(windForecast, hydroReservoir, volatility);

  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-sm font-medium text-content-primary mb-3">
        Today&rsquo;s drivers
        <span className="text-content-muted ml-1.5 font-normal">
          what&rsquo;s moving the price
        </span>
      </h2>
      <div className="grid grid-cols-3 gap-3">
        <div
          className="bg-surface-secondary rounded-xl p-3 text-center flex flex-col items-center justify-center"
          title="National hydro storage (SE1–SE4 sum, ENTSO-E A72, weekly) — low levels push winter prices up"
        >
          <p className="text-xs text-content-muted mb-1">Hydro reservoir</p>
          {hydroReservoir?.stored_gwh != null ? (
            <>
              <p className="text-xl font-bold tabular-nums text-content-primary">
                {(hydroReservoir.stored_gwh / 1000).toFixed(1)}
              </p>
              <p className="text-[11px] text-content-faint mt-0.5">
                TWh
                {hydroReservoir.change_pct != null
                  ? ` · ${hydroReservoir.change_pct >= 0 ? "+" : ""}${hydroReservoir.change_pct}%/wk`
                  : ""}
              </p>
            </>
          ) : (
            <p className="text-sm text-content-muted">--</p>
          )}
        </div>

        <div
          className="bg-surface-secondary rounded-xl p-3 text-center flex flex-col items-center justify-center"
          title="Avg 100 m wind forecast next 24 h (Open-Meteo) — strong wind lowers spot prices"
        >
          <p className="text-xs text-content-muted mb-1">Wind next 24h</p>
          {windForecast?.avg_wind_100m_ms != null ? (
            <>
              <p className="text-xl font-bold tabular-nums text-content-primary">
                {windForecast.avg_wind_100m_ms}
              </p>
              <p className="text-[11px] text-content-faint mt-0.5">
                m/s avg · peak {windForecast.peak_wind_100m_ms}
              </p>
            </>
          ) : (
            <p className="text-sm text-content-muted">--</p>
          )}
        </div>

        <div
          className="bg-surface-secondary rounded-xl p-3 text-center flex flex-col items-center justify-center"
          title="Today's peak/off-peak ratio (hourly avg, this zone) — higher = more to save by shifting usage"
        >
          <p className="text-xs text-content-muted mb-1">Volatility today</p>
          {volatility ? (
            <>
              <p className="text-xl font-bold tabular-nums text-content-primary">
                {volatility.ratio}×
              </p>
              <p className="text-[11px] text-content-faint mt-0.5">
                {volatility.spread} öre spread
              </p>
            </>
          ) : (
            <p className="text-sm text-content-muted">--</p>
          )}
        </div>
      </div>
      {sentence && (
        <p className="text-xs text-content-secondary mt-3">{sentence}</p>
      )}
    </div>
  );
}
