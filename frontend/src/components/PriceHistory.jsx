import { useState } from "react";
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
import { ZoneComparison } from "./ZoneComparison";
import { useHistory } from "../hooks/useHistory";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      <p className="text-white font-semibold">
        avg {d.avg_sek_kwh?.toFixed(3)} SEK/kWh
      </p>
      {d.min_sek_kwh != null && (
        <p className="text-gray-500">
          min {d.min_sek_kwh.toFixed(3)} · max {d.max_sek_kwh.toFixed(3)}
        </p>
      )}
    </div>
  );
}

export function PriceHistory({ area = "SE3" }) {
  const [tab, setTab] = useState("history");
  const { data, loading, error } = useHistory(90, area);

  const tabBtn = (id, label) => (
    <button
      key={id}
      onClick={() => setTab(id)}
      className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
        tab === id
          ? "bg-gray-700 text-white"
          : "text-gray-500 hover:text-gray-300"
      }`}
    >
      {label}
    </button>
  );

  if (tab === "zones") {
    return (
      <div className="space-y-3">
        <div className="flex gap-1">
          {tabBtn("history", "History")}
          {tabBtn("zones", "Zone Comparison")}
        </div>
        <ZoneComparison />
      </div>
    );
  }

  if (loading)
    return (
      <div className="space-y-3">
        <div className="flex gap-1">
          {tabBtn("history", "History")}
          {tabBtn("zones", "Zone Comparison")}
        </div>
        <p className="text-gray-500 text-sm">Loading history…</p>
      </div>
    );
  if (error)
    return (
      <div className="space-y-3">
        <div className="flex gap-1">
          {tabBtn("history", "History")}
          {tabBtn("zones", "Zone Comparison")}
        </div>
        <p className="text-red-400 text-sm">
          Failed to load history: {error.message}
        </p>
      </div>
    );

  const points = (data?.daily ?? []).filter((d) => d.avg_sek_kwh != null);
  if (points.length === 0)
    return (
      <div className="space-y-3">
        <div className="flex gap-1">
          {tabBtn("history", "History")}
          {tabBtn("zones", "Zone Comparison")}
        </div>
        <p className="text-gray-500 text-sm">
          No historical data available yet.
        </p>
      </div>
    );

  const allAvg = points.map((d) => d.avg_sek_kwh);
  const overallAvg = allAvg.reduce((a, b) => a + b, 0) / allAvg.length;
  const overallMin = Math.min(...allAvg);
  const overallMax = Math.max(...allAvg);

  // X-axis: show ~8 evenly-spaced labels
  const step = Math.max(1, Math.floor(points.length / 8));
  const ticks = points
    .filter((_, i) => i % step === 0 || i === points.length - 1)
    .map((d) => d.date);

  // Format date as "Mar 1"
  const fmt = (iso) => {
    const d = new Date(iso + "T12:00:00Z");
    return d.toLocaleDateString("en-SE", { month: "short", day: "numeric" });
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        {tabBtn("history", "History")}
        {tabBtn("zones", "Zone Comparison")}
      </div>
      <div className="bg-gray-900 rounded-2xl p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-gray-300">
            Spot price history — last 90 days · {area}
          </h2>
          <span className="text-xs text-gray-500">SEK/kWh · daily avg</span>
        </div>

        <ResponsiveContainer width="100%" height={300}>
          <AreaChart
            data={points}
            margin={{ top: 4, right: 4, left: -20, bottom: 0 }}
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
              tickFormatter={fmt}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip content={<CustomTooltip />} />
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

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-3 text-center">
          {[
            { label: "90-day min", value: overallMin.toFixed(3) },
            { label: "90-day avg", value: overallAvg.toFixed(3) },
            { label: "90-day max", value: overallMax.toFixed(3) },
          ].map(({ label, value }) => (
            <div key={label} className="bg-gray-800 rounded-xl py-3">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <p className="text-base font-semibold">{value}</p>
              <p className="text-xs text-gray-600">SEK/kWh</p>
            </div>
          ))}
        </div>

        <p className="text-xs text-gray-700 text-center">
          {points.length} days with data out of last 90 · dashed line = period
          average
        </p>
      </div>
    </div>
  );
}
