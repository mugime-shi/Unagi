import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMultiZone } from "../hooks/useMultiZone";

// SE1 = cheapest (north), SE4 = most expensive (south)
const ZONE_COLORS = {
  SE1: "#60a5fa", // blue
  SE2: "#34d399", // green
  SE3: "#fbbf24", // amber
  SE4: "#f87171", // red
};

const ZONE_CITIES = {
  SE1: "Luleå",
  SE2: "Sundsvall",
  SE3: "Göteborg",
  SE4: "Malmö",
};

function ZoneTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs space-y-1">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.dataKey}: {p.value != null ? p.value.toFixed(3) : "—"} SEK/kWh
        </p>
      ))}
    </div>
  );
}

/**
 * Merge the four zone arrays into a single array of objects keyed by date.
 * e.g. [{ date: "2026-01-01", SE1: 0.28, SE2: 0.30, SE3: 0.35, SE4: 0.42 }, ...]
 */
function mergeZones(zones) {
  if (!zones) return [];
  // Use SE3 as the date spine (all zones return the same date range)
  const spine = zones["SE3"] ?? [];
  return spine.map((row) => {
    const point = { date: row.date };
    for (const area of Object.keys(ZONE_COLORS)) {
      const match = zones[area]?.find((d) => d.date === row.date);
      point[area] = match?.avg_sek_kwh ?? null;
    }
    return point;
  });
}

export function ZoneComparison() {
  const { data, loading, error } = useMultiZone(90);

  if (loading)
    return <p className="text-gray-500 text-sm">Loading zone comparison…</p>;
  if (error)
    return (
      <p className="text-red-400 text-sm">Failed to load: {error.message}</p>
    );

  const points = mergeZones(data?.zones).filter((d) =>
    Object.keys(ZONE_COLORS).some((z) => d[z] != null),
  );

  if (points.length === 0) {
    return (
      <div className="bg-gray-900 rounded-2xl p-4 space-y-2">
        <h2 className="text-sm font-medium text-gray-300">
          Zone Comparison — SE1–SE4
        </h2>
        <p className="text-gray-500 text-sm">
          No multi-zone data yet. Run a backfill for SE1, SE2, SE4 to populate
          the chart.
        </p>
        <pre className="text-xs text-gray-600 bg-gray-800 rounded p-3 overflow-x-auto">
          {`# Backfill via Lambda invoke (once):
aws lambda invoke --function-name namazu-scheduler \\
  --payload '{"backfill_days":90}' /dev/null

# Or locally (run 3×):
python -m app.tasks.fetch_prices --backfill 90 --area SE1
python -m app.tasks.fetch_prices --backfill 90 --area SE2
python -m app.tasks.fetch_prices --backfill 90 --area SE4`}
        </pre>
      </div>
    );
  }

  // X-axis ticks: ~8 evenly spaced
  const step = Math.max(1, Math.floor(points.length / 8));
  const ticks = points
    .filter((_, i) => i % step === 0 || i === points.length - 1)
    .map((d) => d.date);

  const fmt = (iso) => iso;

  // Overall avg per zone (for summary cards)
  const summaries = Object.keys(ZONE_COLORS).map((area) => {
    const vals = points.map((d) => d[area]).filter((v) => v != null);
    return {
      area,
      city: ZONE_CITIES[area],
      avg: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null,
    };
  });

  return (
    <div className="bg-gray-900 rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-300">
          Zone Comparison — SE1–SE4
        </h2>
        <span className="text-xs text-gray-500">SEK/kWh · daily avg</span>
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
          <Tooltip content={<ZoneTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#9ca3af", paddingTop: 8 }}
            formatter={(value) => `${value} · ${ZONE_CITIES[value]}`}
          />
          {Object.entries(ZONE_COLORS).map(([area, color]) => (
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
          ))}
        </LineChart>
      </ResponsiveContainer>

      {/* 90-day avg per zone */}
      <div className="grid grid-cols-4 gap-2 text-center">
        {summaries.map(({ area, city, avg }) => (
          <div key={area} className="bg-gray-800 rounded-xl py-3">
            <p className="text-xs mb-0.5" style={{ color: ZONE_COLORS[area] }}>
              {area}
            </p>
            <p className="text-xs text-gray-500 mb-1">{city}</p>
            <p className="text-sm font-semibold">
              {avg != null ? avg.toFixed(3) : "—"}
            </p>
            <p className="text-xs text-gray-600">SEK/kWh</p>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-700 text-center">
        SE1 (north) is typically cheapest · SE4 (south) most expensive · gap
        reflects transmission constraints
      </p>
    </div>
  );
}
