"use client";

import { useMemo, useState } from "react";
import {
  AreaChart,
  Area as RechartsArea,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useNational24h } from "../hooks/useNational24h";
import { useAllZonePrices } from "../hooks/useAllZonePrices";
import { useGenerationHistory } from "../hooks/useGenerationHistory";
import { useChartColors } from "../hooks/useChartColors";
import { useIsMobile } from "../hooks/useIsMobile";
import { UpdateBadge } from "./UpdateBadge";
import { formatPrice, PRICE_UNIT } from "../utils/formatters";
import type { Area } from "../types/index";
import type { GenHistoryDay } from "../hooks/useGenerationHistory";
import type { National24hEntry } from "../hooks/useNational24h";

interface OverviewProps {
  onZoneClick: (zone: Area) => void;
}

const ZONE_LABELS: Record<Area, string> = {
  SE1: "SE1 · Luleå",
  SE2: "SE2 · Sundsvall",
  SE3: "SE3 · Stockholm",
  SE4: "SE4 · Malmö",
};

type TimeRange = "24h" | "7d" | "30d" | "90d" | "180d" | "365d";

const RANGES: { id: TimeRange; label: string; days: number }[] = [
  { id: "24h", label: "24H", days: 1 },
  { id: "7d", label: "7d", days: 7 },
  { id: "30d", label: "30d", days: 30 },
  { id: "90d", label: "3mo", days: 90 },
  { id: "180d", label: "6mo", days: 180 },
  { id: "365d", label: "1yr", days: 365 },
];

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

// ── Unified chart data type ──
interface GenChartRow {
  label: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  other: number;
}

function national24hToRows(hourly: National24hEntry[]): GenChartRow[] {
  return hourly.map((h) => ({
    label: h.hour_label,
    hydro: h.hydro,
    nuclear: h.nuclear,
    wind: h.wind,
    solar: h.solar,
    other: h.other + h.fossil,
  }));
}

function historyToRows(
  daily: GenHistoryDay[],
  rangeDays: number,
): GenChartRow[] {
  // Aggregate based on range for appropriate granularity
  // 7d/30d: daily (no aggregation)
  // 90d (3mo): weekly
  // 180d (6mo): bi-weekly
  // 365d (1yr): monthly
  if (rangeDays <= 30) {
    return daily.map((d) => ({
      label: d.date.slice(5),
      hydro: d.hydro,
      nuclear: d.nuclear,
      wind: d.wind,
      solar: d.solar,
      other: d.other + d.fossil,
    }));
  }

  // Aggregate into buckets
  const bucketDays = rangeDays <= 90 ? 7 : rangeDays <= 180 ? 14 : 30;
  const buckets: {
    label: string;
    hydro: number[];
    nuclear: number[];
    wind: number[];
    solar: number[];
    other: number[];
  }[] = [];
  let current: (typeof buckets)[0] | null = null;
  let count = 0;

  for (const d of daily) {
    if (count % bucketDays === 0) {
      current = {
        label:
          bucketDays >= 30
            ? (() => {
                // "2025-04" → "Apr '25"
                const [y, m] = d.date.split("-");
                const months = [
                  "Jan",
                  "Feb",
                  "Mar",
                  "Apr",
                  "May",
                  "Jun",
                  "Jul",
                  "Aug",
                  "Sep",
                  "Oct",
                  "Nov",
                  "Dec",
                ];
                return `${months[parseInt(m, 10) - 1]} '${y.slice(2)}`;
              })()
            : d.date.slice(5), // "MM-DD" for weekly/bi-weekly
        hydro: [],
        nuclear: [],
        wind: [],
        solar: [],
        other: [],
      };
      buckets.push(current);
    }
    current!.hydro.push(d.hydro);
    current!.nuclear.push(d.nuclear);
    current!.wind.push(d.wind);
    current!.solar.push(d.solar);
    current!.other.push(d.other + d.fossil);
    count++;
  }

  const avg = (arr: number[]) =>
    arr.length > 0
      ? Math.round(arr.reduce((s, v) => s + v, 0) / arr.length)
      : 0;

  return buckets.map((b) => ({
    label: b.label,
    hydro: avg(b.hydro),
    nuclear: avg(b.nuclear),
    wind: avg(b.wind),
    solar: avg(b.solar),
    other: avg(b.other),
  }));
}

// ── Generation stacked area chart (unified) ──
function GenChart({
  data,
  cc,
  isMobile,
}: {
  data: GenChartRow[];
  cc: ReturnType<typeof useChartColors>;
  isMobile: boolean;
}) {
  return (
    <>
      <ResponsiveContainer width="100%" height={isMobile ? 300 : 380}>
        <AreaChart
          data={data}
          stackOffset="none"
          margin={{ top: 4, right: 4, left: 0, bottom: 28 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={cc.grid}
            vertical={false}
          />
          <XAxis
            dataKey="label"
            tick={{ fill: cc.axis, fontSize: 10, dy: 4 }}
            tickLine={false}
            axisLine={{ stroke: cc.grid }}
            angle={-45}
            textAnchor="end"
            interval={isMobile ? Math.max(1, Math.floor(data.length / 10)) : 0}
          />
          <YAxis
            width={isMobile ? 36 : 48}
            tick={{ fill: cc.axisDim, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) =>
              v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`
            }
          />
          <Tooltip
            contentStyle={{
              background: cc.tooltipBg,
              border: `1px solid ${cc.tooltipBorder}`,
              color: cc.tooltipText,
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v, name) => [`${Math.round(v as number)} MW`, name]}
            itemSorter={(item) => {
              const order: Record<string, number> = {
                Solar: 0,
                Wind: 1,
                Hydro: 2,
                Other: 3,
                Nuclear: 4,
              };
              return order[item.name ?? ""] ?? 99;
            }}
          />
          <RechartsArea
            dataKey="nuclear"
            name="Nuclear"
            stackId="gen"
            fill={cc.nuclear + "99"}
            stroke={cc.nuclear}
          />
          <RechartsArea
            dataKey="other"
            name="Other"
            stackId="gen"
            fill={cc.other + "99"}
            stroke={cc.other}
          />
          <RechartsArea
            dataKey="hydro"
            name="Hydro"
            stackId="gen"
            fill={cc.hydro + "99"}
            stroke={cc.hydro}
          />
          <RechartsArea
            dataKey="wind"
            name="Wind"
            stackId="gen"
            fill={cc.wind + "99"}
            stroke={cc.wind}
          />
          <RechartsArea
            dataKey="solar"
            name="Solar"
            stackId="gen"
            fill={cc.solar + "99"}
            stroke={cc.solar}
          />
        </AreaChart>
      </ResponsiveContainer>
      {/* Legend outside chart to avoid overlap with rotated X-axis labels */}
      <div
        className="flex justify-center gap-3 mt-2"
        style={{ fontSize: 11, color: cc.axis }}
      >
        {[
          { label: "Solar", color: cc.solar },
          { label: "Wind", color: cc.wind },
          { label: "Hydro", color: cc.hydro },
          { label: "Other", color: cc.other },
          { label: "Nuclear", color: cc.nuclear },
        ].map(({ label, color }) => (
          <span key={label} className="flex items-center gap-1">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: color + "99" }}
            />
            {label}
          </span>
        ))}
      </div>
    </>
  );
}

// ── Zone price line chart (7d+) ──
function ZonePriceHistoryChart({
  zones,
  cc,
  isMobile,
  rangeDays,
  onZoneClick,
}: {
  zones: Record<Area, { date: string; avg: number | null }[]>;
  cc: ReturnType<typeof useChartColors>;
  isMobile: boolean;
  rangeDays: number;
  onZoneClick: (zone: Area) => void;
}) {
  const zoneKeys: Area[] = ["SE1", "SE2", "SE3", "SE4"];
  const zoneColors: Record<Area, string> = {
    SE1: cc.SE1,
    SE2: cc.SE2,
    SE3: cc.SE3,
    SE4: cc.SE4,
  };

  // Merge all dates
  const allDates = new Set<string>();
  for (const z of zoneKeys) {
    for (const d of zones[z] ?? []) allDates.add(d.date);
  }
  const datesSorted = Array.from(allDates).sort();

  // Build raw daily data
  const rawData = datesSorted.map((date) => {
    const row: { date: string; [key: string]: string | number | null } = {
      date,
    };
    for (const z of zoneKeys) {
      const entry = zones[z]?.find((d) => d.date === date);
      row[z] = entry?.avg != null ? Math.round(entry.avg * 100) : null;
    }
    return row;
  });

  // Aggregate for longer ranges (same bucketing as generation)
  const bucketDays =
    rangeDays <= 30 ? 1 : rangeDays <= 90 ? 7 : rangeDays <= 180 ? 14 : 30;
  const granLabel =
    bucketDays === 1
      ? "daily"
      : bucketDays === 7
        ? "weekly"
        : bucketDays === 14
          ? "bi-weekly"
          : "monthly";

  const chartData: Record<string, string | number | null>[] = [];
  if (bucketDays === 1) {
    for (const row of rawData) {
      chartData.push({
        date: row.date.slice(5),
        ...Object.fromEntries(zoneKeys.map((z) => [z, row[z]])),
      });
    }
  } else {
    for (let i = 0; i < rawData.length; i += bucketDays) {
      const chunk = rawData.slice(i, i + bucketDays);
      const label =
        bucketDays >= 30
          ? (() => {
              const [y, m] = chunk[0].date.split("-");
              const months = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
              ];
              return `${months[parseInt(m, 10) - 1]} '${y.slice(2)}`;
            })()
          : chunk[0].date.slice(5);
      const row: Record<string, string | number | null> = { date: label };
      for (const z of zoneKeys) {
        const vals = chunk
          .map((c) => c[z])
          .filter((v): v is number => v != null);
        row[z] =
          vals.length > 0
            ? Math.round(vals.reduce((s, v) => s + v, 0) / vals.length)
            : null;
      }
      chartData.push(row);
    }
  }

  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-sm font-medium text-content-primary mb-1">
        Spot price by zone
        <span className="text-content-muted ml-1.5 font-normal">
          {PRICE_UNIT}, {granLabel} average
        </span>
      </h2>
      <ResponsiveContainer width="100%" height={isMobile ? 220 : 280}>
        <LineChart
          data={chartData}
          margin={{ top: 4, right: 4, left: 0, bottom: 36 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={cc.grid}
            vertical={false}
          />
          <XAxis
            dataKey="date"
            tick={{ fill: cc.axis, fontSize: 10, dy: 4 }}
            tickLine={false}
            axisLine={{ stroke: cc.grid }}
            angle={-45}
            textAnchor="end"
            interval={
              isMobile ? Math.max(1, Math.floor(chartData.length / 10)) : 0
            }
          />
          <YAxis
            width={isMobile ? 36 : 48}
            tick={{ fill: cc.axisDim, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: cc.tooltipBg,
              border: `1px solid ${cc.tooltipBorder}`,
              color: cc.tooltipText,
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v) => [`${v} ${PRICE_UNIT}`, ""]}
          />
          {zoneKeys.map((z) => (
            <Line
              key={z}
              dataKey={z}
              name={z}
              stroke={zoneColors[z]}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {/* Legend outside chart */}
      <div
        className="flex justify-center gap-4 mt-2"
        style={{ fontSize: 11, color: cc.axis }}
      >
        {zoneKeys.map((z) => (
          <button
            key={z}
            onClick={() => onZoneClick(z)}
            className="flex items-center gap-1 hover:opacity-80 cursor-pointer"
          >
            <span
              className="inline-block w-3 h-0.5 rounded"
              style={{ backgroundColor: zoneColors[z] }}
            />
            {z}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Main Overview ──

export function Overview({ onZoneClick }: OverviewProps) {
  const [range, setRange] = useState<TimeRange>("24h");
  const is24h = range === "24h";
  const rangeDays = RANGES.find((r) => r.id === range)?.days ?? 1;

  // 24H data (single API call)
  const { data: nat24h, loading: nat24hLoading } = useNational24h();
  const { data: priceData, loading: priceLoading } = useAllZonePrices();

  // Historical data (7d+)
  const { data: genHistory, loading: genHistLoading } = useGenerationHistory(
    is24h ? 0 : rangeDays,
  );

  const cc = useChartColors();
  const isMobile = useIsMobile();
  const zones: Area[] = ["SE1", "SE2", "SE3", "SE4"];
  const zoneColors: Record<Area, string> = {
    SE1: cc.SE1,
    SE2: cc.SE2,
    SE3: cc.SE3,
    SE4: cc.SE4,
  };

  // Multi-zone prices (7d+)
  const [multiZone, setMultiZone] = useState<Record<
    Area,
    { date: string; avg: number | null }[]
  > | null>(null);
  const [multiZoneLoading, setMultiZoneLoading] = useState(false);

  useMemo(() => {
    if (is24h) {
      setMultiZone(null);
      return;
    }
    setMultiZoneLoading(true);
    import("../utils/api").then(({ apiFetch }) => {
      apiFetch(`/api/v1/prices/multi-zone?days=${rangeDays}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((json) => {
          if (!json?.zones) return;
          const result: Record<string, { date: string; avg: number | null }[]> =
            {};
          for (const [zone, days] of Object.entries(json.zones)) {
            result[zone] = (
              days as { date: string; avg_sek_kwh: number | null }[]
            ).map((d) => ({ date: d.date, avg: d.avg_sek_kwh }));
          }
          setMultiZone(
            result as Record<Area, { date: string; avg: number | null }[]>,
          );
        })
        .finally(() => setMultiZoneLoading(false));
    });
  }, [range, rangeDays, is24h]);

  // ── Chart data ──
  const genChartData: GenChartRow[] = useMemo(() => {
    if (is24h) {
      if (!nat24h?.hourly?.length) return [];
      return national24hToRows(nat24h.hourly);
    }
    if (!genHistory?.daily?.length) return [];
    return historyToRows(genHistory.daily, rangeDays);
  }, [is24h, nat24h, genHistory, rangeDays]);

  // ── Renewable card values ──
  const renewableNow = nat24h?.renewable_pct ?? null;
  const renewableAvg = useMemo(() => {
    if (is24h && nat24h?.hourly?.length) {
      const vals = nat24h.hourly
        .map((h) => h.renewable_pct)
        .filter((v): v is number => v != null);
      return vals.length > 0
        ? Math.round(vals.reduce((s, v) => s + v, 0) / vals.length)
        : null;
    }
    if (!genHistory?.daily?.length) return null;
    const vals = genHistory.daily
      .map((d) => d.renewable_pct)
      .filter((v): v is number => v != null);
    return vals.length > 0
      ? Math.round(vals.reduce((s, v) => s + v, 0) / vals.length)
      : null;
  }, [is24h, nat24h, genHistory]);

  const avgLabel = is24h
    ? "24h avg"
    : `avg (${RANGES.find((r) => r.id === range)?.label})`;
  const chartLoading = is24h
    ? nat24hLoading && !nat24h
    : genHistLoading && !genHistory;

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
    const ageMin = Math.round((Date.now() - d.getTime()) / 60000);
    const lag =
      ageMin < 60 ? `~${ageMin} min lag` : `~${(ageMin / 60).toFixed(1)}h lag`;
    return `as of ${time} ${tz} (${lag})`;
  }, [nat24h]);

  // Chart subtitle
  const chartSubtitle = is24h
    ? "MW, hourly, SE1–SE4"
    : `MW, ${rangeDays <= 30 ? "daily" : rangeDays <= 90 ? "weekly" : rangeDays <= 180 ? "bi-weekly" : "monthly"} avg, SE1–SE4`;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row gap-1 sm:gap-4 sm:items-start sm:justify-between">
        <h1 className="text-lg font-semibold text-content-primary">
          Sweden Electricity Overview
        </h1>
        <UpdateBadge />
      </div>

      {/* Time range selector */}
      <div className="flex gap-1">
        {RANGES.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setRange(id)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              range === id
                ? "bg-sky-600 text-white"
                : "bg-surface-secondary text-content-secondary hover:bg-surface-tertiary"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Generation chart */}
      <div className="bg-surface-primary rounded-2xl p-4">
        <div className="mb-1">
          <h2 className="text-sm font-medium text-content-primary">
            Generation mix
            <span className="text-content-muted ml-1.5 font-normal">
              {chartSubtitle}
            </span>
          </h2>
          {is24h && lagText && (
            <p className="text-xs text-content-muted mt-0.5">{lagText}</p>
          )}
        </div>
        {chartLoading ? (
          <div
            className="bg-surface-secondary rounded-xl animate-pulse"
            style={{ height: isMobile ? 280 : 360 }}
          />
        ) : genChartData.length > 0 ? (
          <GenChart data={genChartData} cc={cc} isMobile={isMobile} />
        ) : (
          <p className="text-sm text-content-muted text-center py-16">
            No generation data available
          </p>
        )}
      </div>

      {/* Renewable cards — 2 cards: now + avg */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-surface-primary rounded-2xl p-4 text-center flex flex-col items-center justify-center">
          <p className="text-xs text-content-muted mb-1">Renewable now</p>
          {renewableNow != null ? (
            <p className="text-2xl font-bold text-green-600 dark:text-green-400 tabular-nums">
              {renewableNow}%
            </p>
          ) : (
            <p className="text-sm text-content-muted">--</p>
          )}
        </div>
        <div className="bg-surface-primary rounded-2xl p-4 text-center flex flex-col items-center justify-center">
          <p className="text-xs text-content-muted mb-1">
            Renewable {avgLabel}
          </p>
          {renewableAvg != null ? (
            <p className="text-2xl font-bold text-green-600/70 dark:text-green-400/70 tabular-nums">
              {renewableAvg}%
            </p>
          ) : (
            <p className="text-sm text-content-muted">--</p>
          )}
        </div>
      </div>

      {/* Zone prices */}
      {is24h ? (
        <div className="bg-surface-primary rounded-2xl p-4">
          <h2 className="text-sm font-medium text-content-primary mb-1">
            Spot price by zone
          </h2>
          <p className="text-xs text-content-muted mb-3">
            Click a zone for hourly details
          </p>
          {priceLoading && !priceData ? (
            <div className="space-y-2 animate-pulse">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-12 bg-surface-secondary rounded" />
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
                      <p className="text-sm font-medium text-content-primary">
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
                      <p className="text-lg font-semibold text-content-primary tabular-nums">
                        {z.current_sek_kwh != null
                          ? formatPrice(z.current_sek_kwh)
                          : "—"}
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
      ) : multiZoneLoading ? (
        <div className="bg-surface-primary rounded-2xl p-4 animate-pulse">
          <div className="h-[260px] bg-surface-secondary rounded-xl" />
        </div>
      ) : multiZone ? (
        <ZonePriceHistoryChart
          zones={multiZone}
          cc={cc}
          isMobile={isMobile}
          rangeDays={rangeDays}
          onZoneClick={onZoneClick}
        />
      ) : null}
    </div>
  );
}
