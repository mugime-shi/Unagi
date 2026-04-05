import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipPayloadEntry } from "recharts";
import { formatPrice, PRICE_UNIT } from "../utils/formatters";
import { useMultiZone } from "../hooks/useMultiZone";
import type { Area, ZoneDaily } from "../types/index";

interface ZoneDataPoint {
  date: string;
  SE1: number | null;
  SE2: number | null;
  SE3: number | null;
  SE4: number | null;
}

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
  return `${d.toLocaleDateString("en-SE", { month: "short" })} '${String(d.getFullYear()).slice(2)}`;
}

function getAdaptiveTicks(points: ZoneDataPoint[], days: number): string[] {
  if (days <= 7) return points.map((d) => d.date);
  if (days <= 90) {
    const step = Math.max(1, Math.floor(points.length / 7));
    return points
      .filter((_, i) => i % step === 0 || i === points.length - 1)
      .map((d) => d.date);
  }
  return points
    .filter((d, i) => {
      if (i === 0 || i === points.length - 1) return true;
      return new Date(d.date + "T12:00:00").getDate() === 1;
    })
    .map((d) => d.date);
}

// SE1 = cheapest (north), SE4 = most expensive (south)
const ZONE_COLORS: Record<Area, string> = {
  SE1: "#60a5fa", // blue
  SE2: "#34d399", // green
  SE3: "#fbbf24", // amber
  SE4: "#f87171", // red
};

const ZONE_CITIES: Record<Area, string> = {
  SE1: "Lule\u00e5",
  SE2: "Sundsvall",
  SE3: "Stockholm",
  SE4: "Malm\u00f6",
};

interface ZoneTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
}

function ZoneTooltip({ active, payload, label }: ZoneTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-2 text-xs space-y-1">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} style={{ color: p.color }}>
          {String(p.dataKey)}:{" "}
          {p.value != null ? formatPrice(Number(p.value), 1) : "\u2014"}{" "}
          {PRICE_UNIT}
        </p>
      ))}
    </div>
  );
}

/**
 * Merge the four zone arrays into a single array of objects keyed by date.
 * e.g. [{ date: "2026-01-01", SE1: 0.28, SE2: 0.30, SE3: 0.35, SE4: 0.42 }, ...]
 */
function mergeZones(
  zones: Record<string, ZoneDaily[]> | undefined,
): ZoneDataPoint[] {
  if (!zones) return [];
  // Use SE3 as the date spine (all zones return the same date range)
  const spine = zones["SE3"] ?? [];
  return spine.map((row) => {
    const point: ZoneDataPoint = {
      date: row.date,
      SE1: null,
      SE2: null,
      SE3: null,
      SE4: null,
    };
    for (const area of Object.keys(ZONE_COLORS) as Area[]) {
      const match = zones[area]?.find((d) => d.date === row.date);
      point[area] = match?.avg_sek_kwh ?? null;
    }
    return point;
  });
}

interface ZoneComparisonProps {
  days?: number;
}

interface ZoneSummary {
  area: Area;
  city: string;
  avg: number | null;
}

export function ZoneComparison({ days = 90 }: ZoneComparisonProps) {
  const { data, loading, error } = useMultiZone(days);

  if (loading)
    return <p className="text-gray-500 text-sm">Loading zone comparison...</p>;
  if (error)
    return (
      <p className="text-red-400 text-sm">Failed to load: {error.message}</p>
    );

  const points = mergeZones(data?.zones).filter((d) =>
    (Object.keys(ZONE_COLORS) as Area[]).some((z) => d[z] != null),
  );

  if (points.length === 0) {
    return (
      <div className="bg-sea-900 rounded-2xl p-4 space-y-2">
        <h2 className="text-sm font-medium text-gray-300">
          Zone Comparison -- SE1-SE4
        </h2>
        <p className="text-gray-500 text-sm">
          No multi-zone data yet. Run a backfill for SE1, SE2, SE4 to populate
          the chart.
        </p>
        <pre className="text-xs text-gray-600 bg-sea-800 rounded p-3 overflow-x-auto">
          {`# Backfill via Lambda invoke (once):
aws lambda invoke --function-name unagi-scheduler \\
  --payload '{"backfill_days":90}' /dev/null

# Or locally (run 3x):
python -m app.tasks.fetch_prices --backfill 90 --area SE1
python -m app.tasks.fetch_prices --backfill 90 --area SE2
python -m app.tasks.fetch_prices --backfill 90 --area SE4`}
        </pre>
      </div>
    );
  }

  const ticks = getAdaptiveTicks(points, days);

  // Overall avg per zone (for summary cards)
  const summaries: ZoneSummary[] = (Object.keys(ZONE_COLORS) as Area[]).map(
    (area) => {
      const vals = points
        .map((d) => d[area])
        .filter((v): v is number => v != null);
      return {
        area,
        city: ZONE_CITIES[area],
        avg: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null,
      };
    },
  );

  return (
    <div className="bg-sea-900 rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-300">
          Zone Comparison -- SE1-SE4
        </h2>
        <span className="text-xs text-gray-500">{PRICE_UNIT} - daily avg</span>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart
          data={points}
          margin={{ top: 4, right: 4, left: -20, bottom: 0 }}
        >
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
            tickFormatter={(v: number) => formatPrice(v)}
          />
          <Tooltip content={<ZoneTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#9ca3af", paddingTop: 8 }}
            formatter={(value: string) =>
              `${value} \u00b7 ${ZONE_CITIES[value as Area]}`
            }
          />
          {(Object.entries(ZONE_COLORS) as [Area, string][]).map(
            ([area, color]) => (
              <Line
                key={area}
                type="monotone"
                dataKey={area}
                stroke={color}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls={false}
              />
            ),
          )}
        </LineChart>
      </ResponsiveContainer>

      {/* Period avg per zone */}
      <div className="grid grid-cols-4 gap-2 text-center">
        {summaries.map(({ area, city, avg }) => (
          <div key={area} className="bg-sea-800 rounded-xl py-3">
            <p className="text-xs mb-0.5" style={{ color: ZONE_COLORS[area] }}>
              {area}
            </p>
            <p className="text-xs text-gray-500 mb-1">{city}</p>
            <p className="text-sm font-semibold">
              {avg != null ? formatPrice(avg, 1) : "\u2014"}
            </p>
            <p className="text-xs text-gray-600">{PRICE_UNIT}</p>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-700 text-center">
        SE1 (north) is typically cheapest - SE4 (south) most expensive - gap
        reflects transmission constraints
      </p>
    </div>
  );
}
