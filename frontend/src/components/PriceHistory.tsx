import { ReactElement, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  NameType,
  ValueType,
} from "recharts/types/component/DefaultTooltipContent";
import type { TooltipContentProps } from "recharts";
import { ZoneComparison } from "./ZoneComparison";
import { dateWithWeekday, formatPrice, PRICE_UNIT } from "../utils/formatters";
import { useChartColors, type ChartColors } from "../hooks/useChartColors";
import { useHistory } from "../hooks/useHistory";
import { useIsMobile } from "../hooks/useIsMobile";
import type { Area as AreaType, HistoryDay } from "../types/index";

interface PriceHistoryProps {
  area?: AreaType;
}

interface RangeDef {
  label: string;
  days: number;
}

function CustomTooltip({
  active,
  payload,
  label,
  cc,
}: TooltipContentProps<ValueType, NameType> & {
  cc: ChartColors;
}): ReactElement | null {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as HistoryDay;
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs border"
      style={{
        background: cc.tooltipBg,
        borderColor: cc.tooltipBorder,
        color: cc.tooltipText,
      }}
    >
      <p style={{ color: cc.axis }} className="mb-1">
        {dateWithWeekday(label as string)}
      </p>
      <p className="font-semibold">
        avg {d.avg_sek_kwh != null ? formatPrice(d.avg_sek_kwh, 1) : "\u2014"}{" "}
        {PRICE_UNIT}
      </p>
      {d.min_sek_kwh != null && (
        <p style={{ color: cc.axisDim }}>
          min {formatPrice(d.min_sek_kwh, 1)} &middot; max{" "}
          {formatPrice(d.max_sek_kwh!, 1)}
        </p>
      )}
    </div>
  );
}

const RANGES: RangeDef[] = [
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
];

function formatTick(iso: string, days: number): string {
  const d = new Date(iso + "T12:00:00");
  if (days <= 7) {
    const wd = d.toLocaleDateString("en-SE", { weekday: "short" });
    return `${wd} ${d.getMonth() + 1}/${d.getDate()}`;
  }
  if (days <= 90) {
    return d.toLocaleDateString("en-SE", { month: "short", day: "numeric" });
  }
  if (days <= 180) {
    return d.toLocaleDateString("en-SE", { month: "short" });
  }
  // 1Y: "Jan '26"
  return `${d.toLocaleDateString("en-SE", { month: "short" })} '${String(d.getFullYear()).slice(2)}`;
}

function getAdaptiveTicks(points: HistoryDay[], days: number): string[] {
  if (days <= 7) return points.map((d) => d.date);
  if (days <= 90) {
    const step = Math.max(1, Math.floor(points.length / 7));
    return points
      .filter((_, i) => i % step === 0 || i === points.length - 1)
      .map((d) => d.date);
  }
  // 6M / 1Y: first of each month
  return points
    .filter((d, i) => {
      if (i === 0 || i === points.length - 1) return true;
      return new Date(d.date + "T12:00:00").getDate() === 1;
    })
    .map((d) => d.date);
}

export function PriceHistory({
  area = "SE3",
}: PriceHistoryProps): ReactElement {
  const cc = useChartColors();
  const [tab, setTab] = useState<"history" | "zones">("history");
  const [days, setDays] = useState<number>(90);
  const isMobile = useIsMobile();
  const chartHeight = isMobile ? 300 : 350;
  const { data, loading, error } = useHistory(days, area);

  const tabBtn = (id: "history" | "zones", label: string): ReactElement => (
    <button
      key={id}
      onClick={() => setTab(id)}
      className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
        tab === id
          ? "bg-surface-tertiary text-content-primary"
          : "text-content-muted hover:text-content-secondary"
      }`}
    >
      {label}
    </button>
  );

  const subNav = (
    <div className="flex items-center justify-between">
      <div className="flex gap-1">
        {tabBtn("history", "Daily")}
        {tabBtn("zones", "Zone Comparison")}
      </div>
      <div className="flex gap-1">
        {RANGES.map(({ label, days: d }) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
              days === d
                ? "bg-surface-tertiary text-content-primary"
                : "text-content-faint hover:text-content-secondary"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  if (tab === "zones") {
    return (
      <div className="space-y-3">
        {subNav}
        <ZoneComparison days={days} />
      </div>
    );
  }

  if (loading)
    return (
      <div className="space-y-3">
        {subNav}
        <p className="text-content-muted text-sm">Loading history...</p>
      </div>
    );
  if (error)
    return (
      <div className="space-y-3">
        {subNav}
        <p className="text-red-500 text-sm">
          Failed to load history: {error.message}
        </p>
      </div>
    );

  const points = (data?.daily ?? []).filter(
    (d): d is HistoryDay & { avg_sek_kwh: number } => d.avg_sek_kwh != null,
  );
  if (points.length === 0)
    return (
      <div className="space-y-3">
        {subNav}
        <p className="text-content-muted text-sm">
          No historical data available yet.
        </p>
      </div>
    );

  const allAvg = points.map((d) => d.avg_sek_kwh);
  const overallAvg = allAvg.reduce((a, b) => a + b, 0) / allAvg.length;
  const overallMin = Math.min(...allAvg);
  const overallMax = Math.max(...allAvg);

  const ticks = getAdaptiveTicks(points, days);

  return (
    <div className="space-y-3">
      {subNav}
      <div className="bg-surface-primary rounded-2xl p-4 space-y-4">
        <h2 className="text-sm font-medium text-content-primary">
          Spot price
          <span className="text-content-muted ml-1.5">
            last {days} days &middot; {area}
          </span>
        </h2>

        <ResponsiveContainer width="100%" height={chartHeight}>
          <AreaChart
            data={points}
            margin={{ top: 24, right: 4, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="histGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={cc.daFill} stopOpacity={0.3} />
                <stop offset="95%" stopColor={cc.daFill} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={cc.grid}
              vertical={false}
            />
            <XAxis
              dataKey="date"
              ticks={ticks}
              tickFormatter={(iso: string) => formatTick(iso, days)}
              tick={{ fill: cc.axisDim, fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: cc.axisDim, fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => formatPrice(v)}
              width={isMobile ? 32 : 48}
            />
            <Tooltip
              content={(props) => <CustomTooltip {...props} cc={cc} />}
            />
            <ReferenceLine
              y={overallAvg}
              stroke={cc.axis}
              strokeDasharray="4 4"
              strokeWidth={1}
            />
            <Area
              type="monotone"
              dataKey="avg_sek_kwh"
              stroke={cc.daLine}
              strokeWidth={2}
              fill="url(#histGrad)"
              dot={false}
              activeDot={{ r: 4, fill: cc.daLine }}
            />
          </AreaChart>
        </ResponsiveContainer>

        <p className="text-xs text-content-faint text-center">
          {points.length} days with data out of last {days} &middot; dashed line
          = period average
        </p>
      </div>

      {/* Summary stats — outside chart container for visual separation */}
      <div className="grid grid-cols-3 gap-3 text-center">
        {[
          { label: `${days}-day min`, value: formatPrice(overallMin, 1) },
          { label: `${days}-day avg`, value: formatPrice(overallAvg, 1) },
          { label: `${days}-day max`, value: formatPrice(overallMax, 1) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-surface-secondary rounded-xl py-3">
            <p className="text-xs text-content-muted mb-1">{label}</p>
            <p className="text-base font-semibold text-content-primary">
              {value}
            </p>
            <p className="text-[10px] text-content-faint">{PRICE_UNIT}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
