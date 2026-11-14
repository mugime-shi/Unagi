"use client";

import { useEffect, useMemo, useState } from "react";
import { useNational24h } from "../hooks/useNational24h";
import type { ZonePriceSummary } from "../hooks/useAllZonePrices";
import { useAllZonePrices } from "../hooks/useAllZonePrices";
import { useWeeklyForecast } from "../hooks/useWeeklyForecast";
import { useForecastAccuracy } from "../hooks/useForecastAccuracy";
import { useCoverage } from "../hooks/useCoverage";
import { useChartColors } from "../hooks/useChartColors";
import { useIsMobile } from "../hooks/useIsMobile";
import { UpdateBadge } from "./UpdateBadge";
import { TodayStory } from "./TodayStory";
import { MapAttribution, SwedenMap } from "./SwedenMap";
import { TrendArrow } from "./TrendArrow";
import { useOutages } from "../hooks/useOutages";
import { WeeklySummary } from "./WeeklySummary";
import { formatPrice, PRICE_UNIT, currentCETHour } from "../utils/formatters";
import type { Area } from "../types/index";
import { GenChart } from "./GenChart";
import { national24hToRows, type GenChartRow } from "../utils/genHistory";

interface OverviewProps {
  onZoneClick: (zone: Area) => void;
  /** Jump to the Prices/Tomorrow tab for a forecast date (from the 7-day cards). */
  onDateSelect?: (date: string) => void;
  /** Open Prices → Trends → Generation (long-range history). */
  onOpenTrends?: () => void;
}

const ZONE_LABELS: Record<Area, string> = {
  SE1: "SE1 · Luleå, Umeå",
  SE2: "SE2 · Sundsvall, Östersund",
  SE3: "SE3 · Stockholm, Göteborg",
  SE4: "SE4 · Malmö, Helsingborg",
};

// ── Small components ──

function Sparkline({
  slots,
  color,
  width = 80,
  height = 24,
}: {
  slots: { hour: number; price: number }[];
  color: string;
  width?: number;
  height?: number;
}) {
  if (slots.length < 2) return null;
  const prices = slots.map((s) => s.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const stepX = width / (slots.length - 1);
  const points = slots
    .map(
      (s, i) => `${i * stepX},${height - ((s.price - min) / range) * height}`,
    )
    .join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// Price direction over the next known (day-ahead) hours. Sweden's spot prices
// are fixed a day ahead, so this reads the actual upcoming curve — not a
// forecast. Returns null when there is no forward signal (end of day) or the
// move stays within a small deadband (treated as steady → no arrow).
function priceTrend(
  current: number | null,
  slots: { hour: number; price: number }[],
  nowHour: number,
): "up" | "down" | null {
  if (current == null) return null;
  const next = slots.filter((s) => s.hour > nowHour).slice(0, 3);
  if (next.length === 0) return null;
  const nextAvg = next.reduce((sum, s) => sum + s.price, 0) / next.length;
  const deltaOre = (nextAvg - current) * 100;
  const DEADBAND_ORE = 3;
  if (deltaOre > DEADBAND_ORE) return "up";
  if (deltaOre < -DEADBAND_ORE) return "down";
  return null;
}

// ── Main Overview ──

export function Overview({
  onZoneClick,
  onDateSelect,
  onOpenTrends,
}: OverviewProps) {
  // Today's national hourly generation (single API call)
  const { data: nat24h, loading: nat24hLoading } = useNational24h();
  const { data: priceData, loading: priceLoading } = useAllZonePrices();
  // One outages fetch, shared by the zone map and the nuclear board
  const outages = useOutages();

  // Next-7-days forecast + track record. Area-selectable (SE3 default); the
  // backend has forecasts for all four zones. Overview only mounts on its own
  // layer, so these fetch only while the Overview is shown.
  const [weeklyArea, setWeeklyArea] = useState<Area>("SE3");
  const { data: weekly, loading: weeklyLoading } = useWeeklyForecast(
    weeklyArea,
    true,
  );
  const { data: accuracy } = useForecastAccuracy(weeklyArea, 28);
  const { data: coverage } = useCoverage(weeklyArea, 30);
  const d1Mae = accuracy?.models?.lgbm?.mae_sek_kwh ?? null; // d+1 MAE (SEK/kWh)
  const baseMae = accuracy?.models?.same_weekday_avg?.mae_sek_kwh ?? null;

  const cc = useChartColors();
  const isMobile = useIsMobile();
  // Map layout switches at 900 px: below that the overlay cards would not fit
  const isNarrow = useIsMobile(900);
  const [hoverZone, setHoverZone] = useState<Area | null>(null);
  const nowHour = currentCETHour(); // for zone-tile price trend arrows
  const zones: Area[] = ["SE1", "SE2", "SE3", "SE4"];
  const zoneColors: Record<Area, string> = {
    SE1: cc.SE1,
    SE2: cc.SE2,
    SE3: cc.SE3,
    SE4: cc.SE4,
  };

  // ── Chart data ──
  const genChartData: GenChartRow[] = useMemo(() => {
    if (!nat24h?.hourly?.length) return [];
    return national24hToRows(nat24h.hourly);
  }, [nat24h]);

  const chartLoading = nat24hLoading && !nat24h;

  // Generation mix share % at the latest slot (drives legend % annotations)
  const shareByType = useMemo<Record<string, number> | null>(() => {
    if (!genChartData.length) return null;
    const latest = genChartData[genChartData.length - 1];
    const total =
      latest.hydro + latest.nuclear + latest.wind + latest.solar + latest.other;
    if (total <= 0) return null;
    return {
      Solar: Math.round((latest.solar / total) * 100),
      Wind: Math.round((latest.wind / total) * 100),
      Hydro: Math.round((latest.hydro / total) * 100),
      Other: Math.round((latest.other / total) * 100),
      Nuclear: Math.round((latest.nuclear / total) * 100),
    };
  }, [genChartData]);

  // Wall clock for the lag label; ticking state keeps render pure (react-hooks/purity).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  // Lag info
  const lagText = useMemo(() => {
    if (!nat24h?.latest_slot) return null;
    const d = new Date(nat24h.latest_slot);
    const time = d.toLocaleTimeString("sv-SE", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/Stockholm",
    });
    const tz = d
      .toLocaleTimeString("en-SE", {
        timeZone: "Europe/Stockholm",
        timeZoneName: "short",
      })
      .split(" ")
      .pop();
    const ageMin = Math.round((now - d.getTime()) / 60000);
    const lag =
      ageMin < 60 ? `~${ageMin} min lag` : `~${(ageMin / 60).toFixed(1)}h lag`;
    return `as of ${time} ${tz} (${lag})`;
  }, [nat24h, now]);

  // Latest-slot carbon intensity (gCO2/kWh) — approx coefficients:
  // fossil ≈ 400 gCO2/kWh, other ≈ 20 gCO2/kWh, renewable + nuclear ≈ 0
  const latestCarbonIntensity = useMemo<number | null>(() => {
    if (!nat24h?.hourly?.length) return null;
    const latest = nat24h.hourly[nat24h.hourly.length - 1];
    const total = latest.total_mw;
    if (!total || total <= 0) return null;
    const co2 = (latest.fossil ?? 0) * 400 + (latest.other ?? 0) * 20;
    return Math.round(co2 / total);
  }, [nat24h]);

  // Compose an env badges line: "Renewable X% · Carbon-free Y% · ZgCO₂/kWh"
  const envBadgeLine = useMemo<string | null>(() => {
    if (!nat24h) return null;
    const parts: string[] = [];
    if (nat24h.renewable_pct != null) {
      parts.push(`Renewable ${nat24h.renewable_pct}%`);
    }
    if (nat24h.carbon_free_pct != null) {
      parts.push(`Carbon-free ${nat24h.carbon_free_pct}%`);
    }
    if (latestCarbonIntensity != null) {
      parts.push(`${latestCarbonIntensity}gCO₂/kWh`);
    }
    return parts.length > 0 ? parts.join(" · ") : null;
  }, [nat24h, latestCarbonIntensity]);

  // Surface zones whose latest generation slot lags more than 1 h behind the
  // freshest zone. Anything smaller is normal ENTSO-E publication jitter.
  const laggingZones = useMemo<{ zone: string; hoursBehind: number }[]>(() => {
    if (!nat24h?.zone_latest) return [];
    const entries = Object.entries(nat24h.zone_latest).filter(
      ([, iso]) => typeof iso === "string" && iso.length > 0,
    ) as [string, string][];
    if (entries.length < 2) return [];
    const times = entries.map(([zone, iso]) => ({
      zone,
      ms: new Date(iso).getTime(),
    }));
    const newest = Math.max(...times.map((t) => t.ms));
    return times
      .filter((t) => newest - t.ms > 60 * 60 * 1000)
      .map((t) => ({
        zone: t.zone,
        hoursBehind: +((newest - t.ms) / (60 * 60 * 1000)).toFixed(1),
      }))
      .sort((a, b) => b.hoursBehind - a.hoursBehind);
  }, [nat24h]);

  return (
    <div className="space-y-4">
      <TodayStory />

      {/* Zone prices lead the page: "what does it cost right now" is the most
          common question. Generation mix (the background/context) moves below
          the forecast so the actionable "what's coming" sits above the fold. */}
      <div>
        <div className="bg-surface-primary rounded-2xl p-4">
          {/* Title + badge row like the Prices / Cost tabs, but a card-title h2: the global h1 rule (Fraunces, 26px)
              is unlayered and beats Tailwind classes, and a display serif inside a card stood out. The badge
              refreshes the whole page, not just the map. */}
          <div className="flex flex-col sm:flex-row gap-1 sm:gap-4 sm:items-center sm:justify-between mb-3">
            <h2 className="text-base font-medium text-content-primary">
              Sweden Electricity Overview
            </h2>
            <UpdateBadge />
          </div>
          <SwedenMap
            layout={isNarrow ? "compact" : "wide"}
            prices={priceData}
            outages={outages.data}
            outagesError={!!outages.error}
            onZoneClick={onZoneClick}
            hoverZone={hoverZone}
            onHoverZone={setHoverZone}
            trends={
              priceData
                ? (Object.fromEntries(
                    zones.map((zone) => [
                      zone,
                      priceTrend(
                        priceData[zone].current_sek_kwh,
                        priceData[zone].slots,
                        nowHour,
                      ),
                    ]),
                  ) as Record<Area, "up" | "down" | null>)
                : null
            }
          />
          {isNarrow && (
            <div className="mt-4">
              {priceLoading && !priceData ? (
                <div className="space-y-2 animate-pulse">
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="h-12 bg-surface-secondary rounded"
                    />
                  ))}
                </div>
              ) : priceData ? (
                <div className="space-y-1">
                  {zones.map((zone) => {
                    const z = priceData[zone];
                    const color = zoneColors[zone];
                    return (
                      <button
                        key={zone}
                        onClick={() => onZoneClick(zone)}
                        className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl bg-surface-secondary hover:bg-surface-tertiary transition-colors text-left"
                      >
                        <span
                          className="inline-block w-1 h-8 rounded-full shrink-0"
                          style={{ backgroundColor: color }}
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm sm:text-base font-medium text-content-primary whitespace-nowrap overflow-hidden text-ellipsis">
                            {ZONE_LABELS[zone]}
                          </p>
                          <p className="text-[10px] text-content-muted">
                            Today avg{" "}
                            {z.today_avg_sek_kwh != null
                              ? formatPrice(z.today_avg_sek_kwh)
                              : "—"}{" "}
                            {PRICE_UNIT}
                          </p>
                        </div>
                        <div className="hidden sm:block">
                          <Sparkline
                            slots={z.slots}
                            color={color}
                            width={100}
                            height={26}
                          />
                        </div>
                        <div className="text-right shrink-0">
                          <p className="text-[10px] text-content-muted uppercase tracking-wide">
                            now
                          </p>
                          <p className="text-lg font-semibold text-content-primary tabular-nums leading-tight flex items-center justify-end gap-1">
                            <TrendArrow
                              trend={priceTrend(
                                z.current_sek_kwh,
                                z.slots,
                                nowHour,
                              )}
                            />
                            <span>
                              {z.current_sek_kwh != null
                                ? formatPrice(z.current_sek_kwh)
                                : "—"}
                            </span>
                          </p>
                          <p className="text-[10px] text-content-faint">
                            {PRICE_UNIT}
                          </p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          )}
        </div>
        <MapAttribution layout={isNarrow ? "compact" : "wide"} />
      </div>

      {/* Next 7 days — SE3 forecast + our own accuracy (transparency). This is
          "what's coming". */}
      {(weeklyLoading || weekly?.days?.length || d1Mae != null) && (
        <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
          <WeeklySummary
            area={weeklyArea}
            onAreaChange={setWeeklyArea}
            data={weekly}
            loading={weeklyLoading}
            includeTomorrow
            onDateSelect={onDateSelect}
          />
          {d1Mae != null && (
            <p className="text-xs text-content-muted">
              Track record · {weeklyArea} · 28d: d+1 error{" "}
              <span className="text-content-secondary tabular-nums">
                {Math.round(d1Mae * 100)} öre
              </span>
              {baseMae != null && (
                <>
                  {" vs "}
                  <span className="tabular-nums">
                    {Math.round(baseMae * 100)} öre
                  </span>{" "}
                  baseline
                </>
              )}
              {coverage && coverage.n_samples > 0 && (
                <>
                  {" · 80% CI "}
                  <span className="text-content-secondary tabular-nums">
                    {Math.round(coverage.coverage_pct)}% covered
                  </span>
                </>
              )}
            </p>
          )}
        </div>
      )}

      {/* Generation mix — the supply-side context behind the prices above.
          Sits last: it's the "why", read after the "what" and "what's next". */}
      <div className="bg-surface-primary rounded-2xl p-4">
        <div className="mb-1">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-base font-medium text-content-primary">
              Generation mix
              <span className="text-content-muted ml-1.5 font-normal">
                MW, hourly, SE1–SE4
              </span>
            </h2>
            {onOpenTrends && (
              <button
                type="button"
                onClick={onOpenTrends}
                className="shrink-0 text-xs text-content-muted hover:text-content-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded transition-colors"
              >
                Trends →
              </button>
            )}
          </div>
          {(envBadgeLine || lagText) && (
            <p className="text-xs text-content-muted mt-0.5">
              {envBadgeLine && <span>{envBadgeLine}</span>}
              {envBadgeLine && lagText && <span> · </span>}
              {lagText && <span>{lagText}</span>}
            </p>
          )}
          {laggingZones.length > 0 && (
            <p
              className="text-[11px] text-amber-600 dark:text-amber-400 mt-1"
              title="Some SE zones are lagging behind ENTSO-E publication. Totals include all zones that have reported; the shaded area may grow retroactively as missing slots arrive."
            >
              ⚠ Delayed:{" "}
              {laggingZones
                .map((z) => `${z.zone} ${z.hoursBehind}h behind`)
                .join(" · ")}
            </p>
          )}
        </div>
        {chartLoading ? (
          <div
            className="bg-surface-secondary rounded-xl animate-pulse"
            style={{ height: isMobile ? 280 : 360 }}
          />
        ) : genChartData.length > 0 ? (
          <GenChart
            data={genChartData}
            cc={cc}
            isMobile={isMobile}
            shareByType={shareByType}
          />
        ) : (
          <p className="text-sm text-content-muted text-center py-16">
            No generation data available
          </p>
        )}
      </div>
    </div>
  );
}
