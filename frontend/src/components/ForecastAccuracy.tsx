import { ReactElement, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
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
import { useCoverage } from "../hooks/useCoverage";
import { useForecastAccuracy } from "../hooks/useForecastAccuracy";
import { useForecastBreakdown } from "../hooks/useForecastBreakdown";
import type { Area } from "../types/index";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const MODEL_COLORS: Record<string, string> = {
  lgbm: "#34d399", // emerald-400
  same_weekday_avg: "#94a3b8", // slate-400
};

// The accuracy API returns per-model stats with these fields
interface AccuracyModel {
  mae_sek_kwh: number;
  rmse_sek_kwh?: number;
  n_days: number;
  n_samples: number;
}

// Extended accuracy response from the API
interface AccuracyData {
  days: number;
  models: Record<string, AccuracyModel>;
}

// Breakdown bucket from the API
interface BreakdownBucket {
  key: number;
  mae_sek_kwh: number;
  samples: number;
}

// Breakdown response from the API
interface BreakdownData {
  models: Record<string, BreakdownBucket[]>;
}

interface SortedModel extends AccuracyModel {
  name: string;
}

interface ChartRow {
  label: string;
  [model: string]: string | number | null;
}

interface ForecastAccuracyProps {
  area: Area;
}

function modelLabel(name: string): string {
  return name === "same_weekday_avg" ? "Weekday Avg" : name.toUpperCase();
}

function BreakdownTooltip({
  active,
  payload,
  label,
}: TooltipContentProps<ValueType, NameType>): ReactElement | null {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey as string} style={{ color: p.fill }}>
          {p.name}: {(p.value as number).toFixed(2)} SEK/kWh
        </p>
      ))}
    </div>
  );
}

/**
 * Forecast accuracy card with optional hourly/weekday breakdown chart.
 * Shown in the Tomorrow tab so users can see prediction quality.
 */
export function ForecastAccuracy({
  area,
}: ForecastAccuracyProps): ReactElement | null {
  const [breakdownBy, setBreakdownBy] = useState<"hour" | "weekday" | null>(
    null,
  );
  const { data, loading } = useForecastAccuracy(area, 30);
  const { data: coverage } = useCoverage(area, 30);
  const { data: breakdown } = useForecastBreakdown(
    area,
    30,
    breakdownBy || "hour",
  );

  if (loading || !data) return null;

  // Cast data to the extended API shape
  const accuracyData = data as unknown as AccuracyData;
  const models = accuracyData.models;
  const modelNames = Object.keys(models);
  if (modelNames.length === 0) {
    return (
      <div className="bg-sea-900 rounded-xl p-3 text-center">
        <p className="text-xs text-gray-500">
          No forecast accuracy data yet — predictions need to be recorded first
        </p>
      </div>
    );
  }

  // Show only d+1 models (lgbm, same_weekday_avg); hide multi-horizon lgbm_d* variants
  const sorted: SortedModel[] = modelNames
    .filter((name) => !name.startsWith("lgbm_d"))
    .map((name) => ({ name, ...models[name] }))
    .sort((a, b) => a.mae_sek_kwh - b.mae_sek_kwh);

  const best = sorted[0];

  // Build chart data from breakdown response
  let chartData: ChartRow[] | null = null;
  const breakdownData = breakdown as unknown as BreakdownData | null;
  if (breakdownBy && breakdownData?.models) {
    const allKeys = new Set<number>();
    for (const buckets of Object.values(breakdownData.models)) {
      for (const b of buckets) allKeys.add(b.key);
    }

    chartData = [...allKeys]
      .sort((a, b) => a - b)
      .map((key) => {
        const label =
          breakdownBy === "weekday"
            ? WEEKDAY_LABELS[key]
            : `${String(key).padStart(2, "0")}:00`;
        const row: ChartRow = { label };
        for (const [model, buckets] of Object.entries(breakdownData.models)) {
          const bucket = buckets.find((b) => b.key === key);
          row[model] = bucket?.mae_sek_kwh ?? null;
        }
        return row;
      });
  }

  const chartModels: string[] = chartData
    ? Object.keys((breakdownData as BreakdownData).models)
        .filter((name) => !name.startsWith("lgbm_d"))
        .sort((a, b) => {
          // best model first
          const maeA = models[a]?.mae_sek_kwh ?? 1;
          const maeB = models[b]?.mae_sek_kwh ?? 1;
          return maeA - maeB;
        })
    : [];

  return (
    <div className="bg-sea-900 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs text-gray-500">
          Forecast accuracy (last {accuracyData.days} days)
        </h3>
        {/* Breakdown toggle */}
        <div className="flex gap-1">
          {[
            { id: "hour" as const, label: "By hour" },
            { id: "weekday" as const, label: "By day" },
          ].map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setBreakdownBy(breakdownBy === id ? null : id)}
              className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                breakdownBy === id
                  ? "border-sky-600 text-sky-400 bg-sky-900/20"
                  : "border-sea-700 text-gray-500 hover:text-gray-400"
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

          return (
            <div
              key={m.name}
              className={`flex items-center justify-between px-3 py-2 rounded-lg ${
                isBest
                  ? "bg-emerald-900/20 border border-emerald-800"
                  : "bg-sea-800"
              }`}
            >
              <div>
                <span className="text-sm font-medium text-gray-200">
                  {modelLabel(m.name)}
                </span>
                <span className="text-xs text-gray-500 ml-2">
                  {m.n_days}d &middot; {m.n_samples} pts
                </span>
              </div>
              <div className="text-right">
                <span
                  className={`text-sm font-semibold ${isBest ? "text-emerald-400" : "text-gray-300"}`}
                >
                  MAE {maeSek} SEK/kWh
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Coverage rate badge */}
      {coverage && coverage.n_samples > 0 && (
        <div className="mt-2 px-3 py-2 bg-sea-800 rounded-lg flex items-center justify-between">
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
        <div className="mt-2 px-3 py-2 bg-sea-800 rounded-lg">
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
                tickFormatter={(v: number) => v.toFixed(2)}
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                width={32}
              />
              <Tooltip content={(props) => <BreakdownTooltip {...props} />} />
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
