import {
  AreaChart,
  Area as RechartsArea,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartColors } from "../hooks/useChartColors";
import type { GenChartRow } from "../utils/genHistory";

/** Generation stacked area chart, shared by Overview (hourly) and Trends. */
export function GenChart({
  data,
  cc,
  isMobile,
  shareByType,
}: {
  data: GenChartRow[];
  cc: ChartColors;
  isMobile: boolean;
  shareByType?: Record<string, number> | null;
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
            content={({ active, payload, label }) => {
              if (!active || !payload || payload.length === 0) return null;
              const order: Record<string, number> = {
                Solar: 0,
                Wind: 1,
                Hydro: 2,
                Other: 3,
                Nuclear: 4,
              };
              const sorted = [...payload].sort(
                (a, b) =>
                  (order[a.name ?? ""] ?? 99) - (order[b.name ?? ""] ?? 99),
              );
              const total = payload.reduce(
                (sum, p) => sum + (typeof p.value === "number" ? p.value : 0),
                0,
              );
              return (
                <div
                  style={{
                    background: cc.tooltipBg,
                    border: `1px solid ${cc.tooltipBorder}`,
                    color: cc.tooltipText,
                    borderRadius: 8,
                    fontSize: 12,
                    padding: "8px 12px",
                    minWidth: 140,
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>
                    {label}
                  </div>
                  {sorted.map((p) => (
                    <div
                      key={String(p.dataKey)}
                      style={{
                        color: p.color,
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12,
                        lineHeight: 1.6,
                      }}
                    >
                      <span>{p.name}</span>
                      <span className="tabular-nums">
                        {Math.round((p.value as number) ?? 0)} MW
                      </span>
                    </div>
                  ))}
                  <div
                    style={{
                      borderTop: `1px solid ${cc.tooltipBorder}`,
                      marginTop: 6,
                      paddingTop: 4,
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      fontWeight: 600,
                    }}
                  >
                    <span>Total</span>
                    <span className="tabular-nums">
                      {Math.round(total).toLocaleString()} MW
                    </span>
                  </div>
                </div>
              );
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
      {/* Legend outside chart — share % from the latest slot when available */}
      <div
        className="flex flex-wrap justify-center gap-3 mt-2"
        style={{ fontSize: 11, color: cc.axis }}
      >
        {[
          { label: "Solar", color: cc.solar },
          { label: "Wind", color: cc.wind },
          { label: "Hydro", color: cc.hydro },
          { label: "Other", color: cc.other },
          { label: "Nuclear", color: cc.nuclear },
        ].map(({ label, color }) => {
          const pct = shareByType?.[label];
          return (
            <span key={label} className="flex items-center gap-1">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm"
                style={{ backgroundColor: color + "99" }}
              />
              {label}
              {pct != null && (
                <span className="tabular-nums opacity-70"> {pct}%</span>
              )}
            </span>
          );
        })}
      </div>
    </>
  );
}
