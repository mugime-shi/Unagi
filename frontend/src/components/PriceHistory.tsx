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
import { dateWithWeekday } from "../utils/formatters";
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
}: TooltipContentProps<ValueType, NameType>): ReactElement | null {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as HistoryDay;
  return (
    <div className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{dateWithWeekday(label as string)}</p>
      <p className="text-white font-semibold">
        avg {d.avg_sek_kwh?.toFixed(3)} SEK/kWh
      </p>
      {d.min_sek_kwh != null && (
        <p className="text-gray-500">
          min {d.min_sek_kwh.toFixed(3)} &middot; max{" "}
          {d.max_sek_kwh!.toFixed(3)}
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
          ? "bg-sea-700 text-white"
          : "text-gray-500 hover:text-gray-300"
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
                ? "bg-sea-700 text-white"
                : "text-gray-600 hover:text-gray-300"
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
        <p className="text-gray-500 text-sm">Loading history...</p>
      </div>
    );
  if (error)
    return (
      <div className="space-y-3">
        {subNav}
        <p className="text-red-400 text-sm">
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
        <p className="text-gray-500 text-sm">
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
      <div className="bg-sea-900 rounded-2xl p-4 space-y-4">
        <h2 className="text-sm font-medium text-gray-300">
          Spot price
          <span className="text-gray-500 ml-1.5">
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
                <stop offset="5%" stopColor="#60a5fa" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#60a5fa" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#374151"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              ticks={ticks}
              tickFormatter={(iso: string) => formatTick(iso, days)}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => v.toFixed(2)}
              width={48}
            />
            <Tooltip content={(props) => <CustomTooltip {...props} />} />
            <ReferenceLine
              y={overallAvg}
              stroke="#9ca3af"
              strokeDasharray="4 4"
              strokeWidth={1}
            />
            <Area
              type="monotone"
              dataKey="avg_sek_kwh"
              stroke="#60a5fa"
              strokeWidth={2}
              fill="url(#histGrad)"
              dot={false}
              activeDot={{ r: 4, fill: "#60a5fa" }}
            />
          </AreaChart>
        </ResponsiveContainer>

        <p className="text-xs text-gray-700 text-center">
          {points.length} days with data out of last {days} &middot; dashed line
          = period average
        </p>
      </div>

      {/* Summary stats — outside chart container for visual separation */}
      <div className="grid grid-cols-3 gap-3 text-center">
        {[
          { label: `${days}-day min`, value: overallMin.toFixed(3) },
          { label: `${days}-day avg`, value: overallAvg.toFixed(3) },
          { label: `${days}-day max`, value: overallMax.toFixed(3) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-sea-800 rounded-xl py-3">
            <p className="text-xs text-gray-500 mb-1">{label}</p>
            <p className="text-base font-semibold">{value}</p>
            <p className="text-[10px] text-gray-600">SEK/kWh</p>
          </div>
        ))}
      </div>
    </div>
  );
}
