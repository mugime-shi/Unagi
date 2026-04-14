"use client";

import { useMemo, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useChartColors } from "../hooks/useChartColors";
import { useMonthlyAverages } from "../hooks/useMonthlyAverages";
import { useIsMobile } from "../hooks/useIsMobile";
import { PRICE_UNIT } from "../utils/formatters";
import type { Area } from "../types/index";

// ── Göteborg Energi Nät 2026 (GNM63, max 63A) ──
// Source: https://api.goteborgenergi.cloud/gridtariff/v0/tariffs
// Valid period: 2026-01-01 to 2027-01-01
const ELNAT_FAST_SEK_YR = 1968; // SEK/year exkl moms
const ELNAT_OVERF_ORE = 18.4; // öre/kWh exkl moms
const ENERGISKATT_ORE = 36.0; // öre/kWh exkl moms (2026)
const MOMS_RATE = 0.25;

type DwellingType = "lagenhet" | "villa_utan" | "villa_med";

const DWELLINGS: { id: DwellingType; label: string; kwhYear: number }[] = [
  { id: "lagenhet", label: "Apartment", kwhYear: 2000 },
  { id: "villa_utan", label: "House", kwhYear: 5000 },
  { id: "villa_med", label: "House + heating", kwhYear: 20000 },
];

interface ChartRow {
  month: string;
  monthLabel: string;
  spot: number;
  elnat: number;
  skatt: number;
  moms: number;
}

const MONTH_LABELS: Record<string, string> = {
  "01": "Jan",
  "02": "Feb",
  "03": "Mar",
  "04": "Apr",
  "05": "Maj",
  "06": "Jun",
  "07": "Jul",
  "08": "Aug",
  "09": "Sep",
  "10": "Okt",
  "11": "Nov",
  "12": "Dec",
};

interface CostFloorProps {
  area: Area;
}

function CustomTooltip({
  active,
  payload,
  cc,
}: {
  active?: boolean;
  payload?: {
    name: string;
    value: number;
    color: string;
    payload?: ChartRow;
  }[];
  label?: string;
  cc: ReturnType<typeof useChartColors>;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + p.value, 0);
  // Full month-year from the data point (e.g. "2026-04" → "Apr 2026")
  const row = payload[0]?.payload;
  const fullLabel = row?.month
    ? `${MONTH_LABELS[row.month.slice(5)] ?? row.month.slice(5)} ${row.month.slice(0, 4)}`
    : "";
  return (
    <div
      className="rounded-lg px-3 py-2 text-sm shadow-lg border"
      style={{
        backgroundColor: cc.tooltipBg,
        borderColor: cc.tooltipBorder,
        color: cc.tooltipText,
      }}
    >
      <p className="font-medium mb-1">{fullLabel}</p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block w-2.5 h-2.5 rounded-sm"
            style={{ backgroundColor: p.color }}
          />
          <span className="flex-1">{p.name}</span>
          <span className="tabular-nums font-mono">
            {p.value.toFixed(1)} {PRICE_UNIT}
          </span>
        </div>
      ))}
      <div
        className="border-t mt-1 pt-1 text-xs font-medium flex justify-between"
        style={{ borderColor: cc.tooltipBorder }}
      >
        <span>Total</span>
        <span className="tabular-nums font-mono">
          {total.toFixed(1)} {PRICE_UNIT}
        </span>
      </div>
    </div>
  );
}

export function CostFloor({ area }: CostFloorProps) {
  const [dwelling, setDwelling] = useState<DwellingType>("lagenhet");
  const { data, loading, error } = useMonthlyAverages(12, area);
  const cc = useChartColors();
  const isMobile = useIsMobile();

  const kwhYear = DWELLINGS.find((d) => d.id === dwelling)!.kwhYear;

  // Amortize fixed fee into öre/kWh
  const elnatFastOre = (ELNAT_FAST_SEK_YR / kwhYear) * 100;
  const elnatTotalOre = elnatFastOre + ELNAT_OVERF_ORE;

  const chartData: ChartRow[] = useMemo(() => {
    if (!data?.months) return [];
    return data.months.map((m, i) => {
      const spotOre = m.avg_sek_kwh * 100;
      const base = spotOre + elnatTotalOre + ENERGISKATT_ORE;
      const momsOre = base * MOMS_RATE;
      const mm = m.month.slice(5);
      const yy = m.month.slice(2, 4);
      const label = MONTH_LABELS[mm] ?? mm;
      // Show 'YY suffix on January or on the very first bar
      const showYear = mm === "01" || i === 0;
      return {
        month: m.month,
        monthLabel: showYear ? `${label} '${yy}` : label,
        spot: Math.round(spotOre * 10) / 10,
        elnat: Math.round(elnatTotalOre * 10) / 10,
        skatt: Math.round(ENERGISKATT_ORE * 10) / 10,
        moms: Math.round(momsOre * 10) / 10,
      };
    });
  }, [data, elnatTotalOre]);

  // Current month summary (last in array)
  const current = chartData.length > 0 ? chartData[chartData.length - 1] : null;
  const currentTotal = current
    ? current.spot + current.elnat + current.skatt + current.moms
    : null;

  return (
    <div className="space-y-4">
      {/* Title + dwelling selector */}
      <div className="bg-surface-primary rounded-2xl p-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
          <div className="flex-1">
            <h2 className="text-sm font-medium text-content-primary">
              Electricity cost breakdown
            </h2>
            <p className="text-xs text-content-muted mt-0.5">
              Minimum cost per kWh — regardless of electricity retailer
              {chartData.length > 0 && (
                <span className="ml-1 text-content-faint">
                  · {chartData[0].month} –{" "}
                  {chartData[chartData.length - 1].month}
                </span>
              )}
            </p>
          </div>
          <div className="flex gap-1">
            {DWELLINGS.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setDwelling(id)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  dwelling === id
                    ? "bg-sky-600 text-white"
                    : "bg-surface-secondary text-content-secondary hover:bg-surface-tertiary"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Summary box */}
        {currentTotal != null && current && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4">
            <div className="sm:col-span-1 bg-surface-secondary rounded-xl py-3 px-3 text-center">
              <p className="text-[10px] text-content-muted mb-0.5">
                Total incl. VAT
              </p>
              <p className="text-xl font-bold text-content-primary tabular-nums">
                {currentTotal.toFixed(0)}
              </p>
              <p className="text-[10px] text-content-faint">{PRICE_UNIT}</p>
            </div>
            {(
              [
                {
                  label: "Spot price",
                  value: current.spot,
                  color: cc.costSpot,
                },
                {
                  label: "Grid fee",
                  value: current.elnat,
                  color: cc.costElnat,
                },
                {
                  label: "Energy tax",
                  value: current.skatt,
                  color: cc.costSkatt,
                },
                { label: "VAT", value: current.moms, color: cc.costMoms },
              ] as const
            ).map(({ label, value, color }) => (
              <div
                key={label}
                className="bg-surface-secondary rounded-xl py-3 px-3 text-center"
              >
                <p className="text-[10px] text-content-muted mb-0.5 flex items-center justify-center gap-1">
                  <span
                    className="inline-block w-2 h-2 rounded-sm"
                    style={{ backgroundColor: color }}
                  />
                  {label}
                </p>
                <p className="text-sm font-semibold text-content-primary tabular-nums">
                  {value.toFixed(1)}
                </p>
                <p className="text-[10px] text-content-faint">{PRICE_UNIT}</p>
              </div>
            ))}
          </div>
        )}

        {/* Grid fee caveat */}
        <p className="text-[10px] text-content-faint px-1">
          Grid fee based on Göteborg Energi Nät (SE3). Actual fees vary by
          network operator — even within the same price area.
        </p>

        {/* Loading / error states */}
        {loading && !data && (
          <div className="animate-pulse">
            <div className="h-[280px] bg-surface-secondary rounded-xl" />
          </div>
        )}
        {error && (
          <p className="text-red-500 text-sm">
            Failed to load data: {error.message}
          </p>
        )}

        {/* Stacked bar chart */}
        {chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={isMobile ? 260 : 320}>
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke={cc.grid}
                vertical={false}
              />
              <XAxis
                dataKey="monthLabel"
                tick={{ fill: cc.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: cc.grid }}
              />
              <YAxis
                width={isMobile ? 36 : 48}
                tick={{ fill: cc.axisDim, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `${v}`}
              />
              <Tooltip
                content={<CustomTooltip cc={cc} />}
                cursor={{ fill: cc.grid, opacity: 0.3 }}
              />
              <Legend
                iconType="square"
                iconSize={10}
                wrapperStyle={{ fontSize: 11, color: cc.axis }}
              />
              <Bar
                dataKey="spot"
                name="Spot price"
                stackId="cost"
                fill={cc.costSpot}
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="elnat"
                name="Grid fee"
                stackId="cost"
                fill={cc.costElnat}
              />
              <Bar
                dataKey="skatt"
                name="Energy tax"
                stackId="cost"
                fill={cc.costSkatt}
              />
              <Bar
                dataKey="moms"
                name="VAT (25%)"
                stackId="cost"
                fill={cc.costMoms}
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Source note */}
      <div className="bg-surface-primary rounded-xl p-4 space-y-2">
        <h3 className="text-xs font-medium text-content-secondary">
          What is included?
        </h3>
        <ul className="text-xs text-content-muted space-y-1">
          <li>
            <strong>Spot price</strong> — Nord Pool {area} monthly average
          </li>
          <li>
            <strong>Grid fee</strong> — Göteborg Energi Nät (GNM63, 2026). Fixed{" "}
            {ELNAT_FAST_SEK_YR} kr/yr ÷ {kwhYear.toLocaleString("sv-SE")} kWh +
            transfer {ELNAT_OVERF_ORE} öre/kWh
          </li>
          <li>
            <strong>Energy tax</strong> — {ENERGISKATT_ORE} öre/kWh (2026)
          </li>
          <li>
            <strong>VAT</strong> — 25% on all above
          </li>
        </ul>
        <p className="text-[10px] text-content-faint italic">
          Your retailer&apos;s markup (profit margin + procurement costs) is
          added on top of this. Grid fees vary by network operator — e.g.
          Ellevio (Stockholm), E.ON (Malmö) charge different rates than Göteborg
          Energi shown here.
        </p>
      </div>
    </div>
  );
}
