import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCoverage } from "../hooks/useCoverage";
import { useForecastAccuracy } from "../hooks/useForecastAccuracy";
import { useForecastBreakdown } from "../hooks/useForecastBreakdown";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const MODEL_COLORS = {
  lgbm: "#34d399", // emerald-400
  same_weekday_avg: "#94a3b8", // slate-400
};

function modelLabel(name) {
  return name === "same_weekday_avg" ? "Weekday Avg" : name.toUpperCase();
}

function BreakdownTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.fill }}>
          {p.name}: {p.value.toFixed(2)} SEK/kWh
        </p>
      ))}
    </div>
  );
}

/**
 * Forecast accuracy card with optional hourly/weekday breakdown chart.
 * Shown in the Tomorrow tab so users can see prediction quality.
 */
export function ForecastAccuracy({ area }) {
  const [breakdownBy, setBreakdownBy] = useState(null); // null | 'hour' | 'weekday'
  const { data, loading } = useForecastAccuracy(area, 30);
  const { data: coverage } = useCoverage(area, 30);
  const { data: breakdown } = useForecastBreakdown(
    area,
    30,
    breakdownBy || "hour",
  );

  if (loading || !data) return null;

  const models = data.models;
  const modelNames = Object.keys(models);
  if (modelNames.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl p-3 text-center">
        <p className="text-xs text-gray-500">
          No forecast accuracy data yet — predictions need to be recorded first
        </p>
      </div>
    );
  }

  // Sort: best MAE first
  const sorted = modelNames
    .map((name) => ({ name, ...models[name] }))
    .sort((a, b) => a.mae_sek_kwh - b.mae_sek_kwh);

  const best = sorted[0];

  // Build chart data from breakdown response
  let chartData = null;
  if (breakdownBy && breakdown?.models) {
    const allKeys = new Set();
    for (const buckets of Object.values(breakdown.models)) {
      for (const b of buckets) allKeys.add(b.key);
    }

    chartData = [...allKeys]
      .sort((a, b) => a - b)
      .map((key) => {
        const label =
          breakdownBy === "weekday"
            ? WEEKDAY_LABELS[key]
            : `${String(key).padStart(2, "0")}:00`;
        const row = { label };
        for (const [model, buckets] of Object.entries(breakdown.models)) {
          const bucket = buckets.find((b) => b.key === key);
          row[model] = bucket?.mae_sek_kwh ?? null;
        }
        return row;
      });
  }

  const chartModels = chartData
    ? Object.keys(breakdown.models).sort((a, b) => {
        // best model first
        const maeA = models[a]?.mae_sek_kwh ?? 1;
        const maeB = models[b]?.mae_sek_kwh ?? 1;
        return maeA - maeB;
      })
    : [];

  return (
    <div className="bg-gray-900 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs text-gray-500">
          Forecast accuracy (last {data.days} days)
        </h3>
        {/* Breakdown toggle */}
        <div className="flex gap-1">
          {[
            { id: "hour", label: "By hour" },
            { id: "weekday", label: "By day" },
          ].map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setBreakdownBy(breakdownBy === id ? null : id)}
              className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                breakdownBy === id
                  ? "border-indigo-600 text-indigo-400 bg-indigo-900/20"
                  : "border-gray-700 text-gray-500 hover:text-gray-400"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="space-y-2">
        {sorted.map((m) => {
          const isBest = sorted.length > 1 && m.name === best.name;
          const maeSek = m.mae_sek_kwh.toFixed(2);
          const improvement =
            sorted.length > 1 && m.name !== best.name
              ? ((1 - best.mae_sek_kwh / m.mae_sek_kwh) * 100).toFixed(0)
              : null;

          return (
            <div
              key={m.name}
              className={`flex items-center justify-between px-3 py-2 rounded-lg ${
                isBest
                  ? "bg-emerald-900/20 border border-emerald-800"
                  : "bg-gray-800"
              }`}
            >
              <div>
                <span className="text-sm font-medium text-gray-200">
                  {modelLabel(m.name)}
                </span>
                <span className="text-xs text-gray-500 ml-2">
                  {m.n_days}d · {m.n_samples} pts
                </span>
              </div>
              <div className="text-right">
                <span
                  className={`text-sm font-semibold ${isBest ? "text-emerald-400" : "text-gray-300"}`}
                >
                  MAE {maeSek} SEK/kWh
                </span>
                {improvement && (
                  <span className="text-xs text-gray-500 ml-2">
                    (best is {improvement}% better)
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Coverage rate badge */}
      {coverage && coverage.n_samples > 0 && (
        <div className="mt-2 px-3 py-2 bg-gray-800 rounded-lg flex items-center justify-between">
          <span className="text-xs text-gray-400">80% CI coverage</span>
          <span
            className={`text-xs font-semibold ${
              Math.abs(coverage.calibration_error) <= 5
                ? "text-emerald-400"
                : Math.abs(coverage.calibration_error) <= 10
                  ? "text-yellow-400"
                  : "text-red-400"
            }`}
          >
            {coverage.coverage_pct}% ({coverage.n_samples} pts)
          </span>
        </div>
      )}
      {coverage && coverage.n_samples === 0 && (
        <div className="mt-2 px-3 py-2 bg-gray-800 rounded-lg">
          <span className="text-xs text-gray-500">
            Coverage rate: collecting interval data...
          </span>
        </div>
      )}

      {/* Breakdown bar chart */}
      {chartData && chartData.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-gray-500 mb-2">
            MAE by {breakdownBy === "weekday" ? "day of week" : "hour of day"}{" "}
            (SEK/kWh)
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#374151"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                interval={breakdownBy === "hour" ? 1 : 0}
                angle={breakdownBy === "hour" ? -45 : 0}
                textAnchor={breakdownBy === "hour" ? "end" : "middle"}
                height={breakdownBy === "hour" ? 40 : 24}
              />
              <YAxis
                tickFormatter={(v) => v.toFixed(2)}
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                width={32}
              />
              <Tooltip content={<BreakdownTooltip />} />
              {chartModels.map((model) => (
                <Bar
                  key={model}
                  dataKey={model}
                  name={modelLabel(model)}
                  fill={MODEL_COLORS[model] || "#6366f1"}
                  opacity={0.8}
                  radius={[2, 2, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
