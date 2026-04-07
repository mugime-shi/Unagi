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
import { formatPrice, PRICE_UNIT } from "../utils/formatters";
import { useChartColors, type ChartColors } from "../hooks/useChartColors";
import { useCoverage } from "../hooks/useCoverage";
import { useForecastAccuracy } from "../hooks/useForecastAccuracy";
import { useForecastBreakdown } from "../hooks/useForecastBreakdown";
import type { Area } from "../types/index";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getModelColor(model: string, cc: ChartColors): string {
  if (model === "lgbm") return cc.lgbm;
  if (model === "same_weekday_avg") return cc.weekdayAvg;
  return cc.fallback;
}

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
  cc,
}: TooltipContentProps<ValueType, NameType> & {
  cc: ChartColors;
}): ReactElement | null {
  if (!active || !payload?.length) return null;
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
        {label}
      </p>
      {payload.map((p) => (
        <p key={p.dataKey as string} style={{ color: p.fill }}>
          {p.name}: {formatPrice(p.value as number)} {PRICE_UNIT}
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
  const cc = useChartColors();
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
      <div className="bg-surface-primary rounded-xl p-3 text-center">
        <p className="text-xs text-content-muted">
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
    <div className="bg-surface-primary rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs text-content-muted">
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
                  ? "border-sky-600 text-sky-600 dark:text-sky-400 bg-sky-100/40 dark:bg-sky-900/20"
                  : "border-surface-tertiary text-content-muted hover:text-content-secondary"
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
          const maeDisplay = formatPrice(m.mae_sek_kwh);

          return (
            <div
              key={m.name}
              className={`flex items-center justify-between px-3 py-2 rounded-lg ${
                isBest
                  ? "bg-surface-secondary border border-surface-tertiary/60"
                  : "bg-surface-secondary"
              }`}
            >
              <div>
                <span className="text-sm font-medium text-content-primary">
                  {modelLabel(m.name)}
                </span>
                <span className="text-xs text-content-muted ml-2">
                  {m.n_days}d &middot; {m.n_samples} pts
                </span>
              </div>
              <div className="text-right">
                <span
                  className={`text-sm font-semibold ${isBest ? "text-content-primary" : "text-content-secondary"}`}
                >
                  MAE {maeDisplay}{" "}
                  <span className="text-content-muted text-[10px] font-normal">
                    {PRICE_UNIT}
                  </span>
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Coverage rate badge */}
      {coverage && coverage.n_samples > 0 && (
        <div className="mt-2 px-3 py-2 bg-surface-secondary rounded-lg flex items-center justify-between">
          <span className="text-xs text-content-secondary">
            80% CI coverage
          </span>
          <span
            className={`text-xs font-semibold ${
              Math.abs(coverage.calibration_error) <= 5
                ? "text-emerald-600 dark:text-emerald-400"
                : Math.abs(coverage.calibration_error) <= 10
                  ? "text-yellow-600 dark:text-yellow-400"
                  : "text-red-600 dark:text-red-400"
            }`}
          >
            {coverage.coverage_pct}% ({coverage.n_samples} pts)
          </span>
        </div>
      )}
      {coverage && coverage.n_samples === 0 && (
        <div className="mt-2 px-3 py-2 bg-surface-secondary rounded-lg">
          <span className="text-xs text-content-muted">
            Coverage rate: collecting interval data...
          </span>
        </div>
      )}

      {/* Breakdown bar chart */}
      {chartData && chartData.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-content-muted mb-2">
            MAE by {breakdownBy === "weekday" ? "day of week" : "hour of day"} (
            {PRICE_UNIT})
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke={cc.grid}
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fill: cc.axis, fontSize: 10 }}
                interval={breakdownBy === "hour" ? 1 : 0}
                angle={breakdownBy === "hour" ? -45 : 0}
                textAnchor={breakdownBy === "hour" ? "end" : "middle"}
                height={breakdownBy === "hour" ? 40 : 24}
              />
              <YAxis
                tickFormatter={(v: number) => formatPrice(v)}
                tick={{ fill: cc.axis, fontSize: 10 }}
                width={32}
              />
              <Tooltip
                content={(props) => <BreakdownTooltip {...props} cc={cc} />}
              />
              {chartModels.map((model) => (
                <Bar
                  key={model}
                  dataKey={model}
                  name={modelLabel(model)}
                  fill={getModelColor(model, cc)}
                  opacity={0.85}
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
