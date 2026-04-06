import { ReactElement } from "react";
import {
  Area,
  AreaChart,
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
import { toLocalHour } from "../utils/formatters";
import { useIsMobile } from "../hooks/useIsMobile";
import type { GenerationPoint, PricePoint } from "../types/index";

interface SourceDef {
  key: string;
  color: string;
  label: string;
}

const SOURCES: SourceDef[] = [
  { key: "nuclear", color: "#eab308", label: "Nuclear" },
  { key: "other", color: "#6b7280", label: "Other" },
  { key: "hydro", color: "#3b82f6", label: "Hydro" },
  { key: "wind", color: "#22d3ee", label: "Wind" },
  { key: "solar", color: "#f97316", label: "Solar" },
];

interface GenChartRow {
  hour: string;
  hydro: number | null;
  wind: number | null;
  nuclear: number | null;
  solar: number | null;
  other: number | null;
  fossil: number | null;
  carbon_intensity: number | null;
  [key: string]: string | number | null;
}

// The generation API response extends GenerationResponse with summary fields
interface GenerationData {
  time_series: GenerationPoint[];
  renewable_pct?: number | null;
  carbon_free_pct?: number | null;
  carbon_intensity?: number | null;
  latest_slot?: string | null;
}

interface GenerationChartProps {
  generation: GenerationData | null;
  prices: PricePoint[] | null;
}

function toUtc(iso: string): string {
  return iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z";
}

function lagLabel(latestSlot: string): string {
  const d = new Date(latestSlot);
  const time = d.toLocaleTimeString("sv-SE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Stockholm",
  });
  const tzParts = d
    .toLocaleTimeString("en-SE", {
      timeZone: "Europe/Stockholm",
      timeZoneName: "short",
    })
    .split(" ");
  const tz = tzParts[tzParts.length - 1];
  const ageMin = Math.round((Date.now() - d.getTime()) / 60000);
  const lag =
    ageMin < 60
      ? `~${ageMin} min lag`
      : `~${Math.round((ageMin / 60) * 10) / 10}h lag`;
  return `as of ${time} ${tz} (${lag})`;
}

function CustomTooltip({
  active,
  payload,
  label,
}: TooltipContentProps<ValueType, NameType>): ReactElement | null {
  if (!active || !payload?.length) return null;
  const hasData = payload.some(
    (p) => p.value != null && (p.value as number) > 0,
  );
  if (!hasData) return null;
  const ci = (payload[0]?.payload as GenChartRow)?.carbon_intensity;
  return (
    <div className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-2 text-sm">
      <p className="text-gray-400 mb-1">{label}</p>
      {[...payload].reverse().map((p) =>
        (p.value as number) > 0 ? (
          <p key={p.dataKey as string} style={{ color: p.fill }}>
            {p.name}: {Math.round(p.value as number)} MW
          </p>
        ) : null,
      )}
      {ci != null && (
        <p className="text-gray-400 mt-1 border-t border-sea-700 pt-1">
          {Math.round(ci)} gCO&#x2082;/kWh
        </p>
      )}
    </div>
  );
}

export function GenerationChart({
  generation,
  prices,
}: GenerationChartProps): ReactElement | null {
  if (!generation?.time_series?.length) return null;

  const isMobile = useIsMobile();
  const {
    time_series: timeSeries,
    renewable_pct,
    carbon_free_pct,
    carbon_intensity,
    latest_slot,
  } = generation;

  // Build generation lookup: "HH:00" -> data row
  const genByHour: Record<string, GenerationPoint> = {};
  for (const d of timeSeries) {
    genByHour[toLocalHour(toUtc(d.timestamp_utc))] = d;
  }

  // Use price hourly ticks as X-axis backbone so both charts share the same 24h frame
  const hourLabels: string[] = prices
    ? [
        ...new Set(
          prices
            .map((p) => toLocalHour(p.timestamp_utc))
            .filter((h) => h.endsWith(":00")),
        ),
      ]
    : Object.keys(genByHour).sort();

  const chartData: GenChartRow[] = hourLabels.map((hour) => {
    const d = genByHour[hour];
    return {
      hour,
      hydro: d?.hydro ?? null,
      wind: d?.wind ?? null,
      nuclear: d?.nuclear ?? null,
      solar: d?.solar ?? null,
      other: d?.other ?? null,
      fossil: d?.fossil ?? null,
      carbon_intensity: d?.carbon_intensity ?? null,
    };
  });

  // Determine Y-axis ticks in 1000 MW steps for better readability
  const maxTotalMw = chartData.reduce((max, d) => {
    const total =
      (d.hydro ?? 0) +
      (d.wind ?? 0) +
      (d.nuclear ?? 0) +
      (d.solar ?? 0) +
      (d.other ?? 0);
    return Math.max(max, total);
  }, 0);

  const maxTickK = Math.max(1, Math.ceil(maxTotalMw / 1000));
  const yTicks = Array.from({ length: maxTickK + 1 }, (_, i) => i * 1000);

  const activeSources = SOURCES.filter(({ key }) =>
    chartData.some((d) => ((d[key] as number | null) ?? 0) > 0),
  );

  return (
    <div className="bg-sea-900 rounded-2xl p-4">
      <div className="mb-3">
        <div className="flex items-start justify-between">
          <h2 className="text-sm font-medium text-gray-300">
            Generation mix &middot; MW
          </h2>
          <div className="flex gap-2 flex-wrap justify-end">
            {activeSources.map(({ key, color, label }) => (
              <span
                key={key}
                className="flex items-center gap-1 text-xs text-gray-400"
              >
                <span
                  className="inline-block w-2.5 h-2.5 rounded-sm"
                  style={{ backgroundColor: color + "99" }}
                />
                {label}
              </span>
            ))}
          </div>
        </div>
        {(renewable_pct != null || carbon_free_pct != null) && (
          <p className="text-xs text-gray-500 mt-0.5">
            {renewable_pct != null && (
              <span className="text-green-400">Renewable {renewable_pct}%</span>
            )}
            {renewable_pct != null && carbon_free_pct != null && (
              <span className="text-gray-600"> &middot; </span>
            )}
            {carbon_free_pct != null && (
              <span>Carbon-free {carbon_free_pct}%</span>
            )}
            {carbon_intensity != null && (
              <>
                <span className="text-gray-600"> &middot; </span>
                <span className="text-gray-400">
                  {Math.round(carbon_intensity)} gCO&#x2082;/kWh
                </span>
              </>
            )}
            {latest_slot && (
              <span className="ml-2">&middot; {lagLabel(latest_slot)}</span>
            )}
          </p>
        )}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart
          data={chartData}
          stackOffset="none"
          margin={{ top: 4, right: 16, left: 0, bottom: 24 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#374151"
            vertical={false}
          />
          <XAxis
            dataKey="hour"
            interval={0}
            tickFormatter={(v: string) => {
              if (!v.endsWith(":00")) return "";
              if (!isMobile) return v;
              const h = parseInt(v.slice(0, 2), 10);
              return h % 2 === 0 ? v : "";
            }}
            tick={{ fill: "#9ca3af", fontSize: 11, dy: 4 }}
            angle={-45}
            textAnchor="end"
          />
          <YAxis
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            width={48}
            domain={[0, maxTickK * 1000]}
            ticks={yTicks}
            tickFormatter={(v: number) =>
              v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
            }
          />
          <Tooltip content={(props) => <CustomTooltip {...props} />} />
          {activeSources.map(({ key, color, label }) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              name={label}
              stackId="gen"
              stroke={color}
              fill={color + "60"}
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
