"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { useGridOperators } from "../hooks/useGridOperators";
import { useMonthlyAverages } from "../hooks/useMonthlyAverages";
import { useIsMobile } from "../hooks/useIsMobile";
import { PRICE_UNIT } from "../utils/formatters";
import type { Area, GridOperatorEntry } from "../types/index";

const ENERGISKATT_ORE = 36.0; // öre/kWh exkl moms (2026, national)
const MOMS_RATE = 0.25;

type DwellingType = "lagenhet" | "villa_utan" | "villa_med";

const DWELLINGS: {
  id: DwellingType;
  label: string;
  kwhYear: number;
  gridType: "apartment" | "house";
}[] = [
  { id: "lagenhet", label: "Apartment", kwhYear: 2000, gridType: "apartment" },
  { id: "villa_utan", label: "House", kwhYear: 5000, gridType: "house" },
  {
    id: "villa_med",
    label: "House + heating",
    kwhYear: 20000,
    gridType: "house",
  },
];

const CUSTOM_SLUG = "__custom__";

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
  "05": "May",
  "06": "Jun",
  "07": "Jul",
  "08": "Aug",
  "09": "Sep",
  "10": "Oct",
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

// ── localStorage helpers ──
const LS_OPERATOR = "unagi-grid-operator";
const LS_CUSTOM_FAST = "unagi-grid-custom-fast";
const LS_CUSTOM_TRANSFER = "unagi-grid-custom-transfer";

function readLS(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return localStorage.getItem(key) ?? fallback;
}

export function CostFloor({ area }: CostFloorProps) {
  const [dwelling, setDwelling] = useState<DwellingType>("lagenhet");
  const [operatorSlug, setOperatorSlug] = useState<string>(() =>
    readLS(LS_OPERATOR, ""),
  );
  const [customFast, setCustomFast] = useState<string>(() =>
    readLS(LS_CUSTOM_FAST, "2000"),
  );
  const [customTransfer, setCustomTransfer] = useState<string>(() =>
    readLS(LS_CUSTOM_TRANSFER, "20"),
  );

  const {
    data: spotData,
    loading: spotLoading,
    error: spotError,
  } = useMonthlyAverages(12, area);
  const { data: gridData, loading: gridLoading } = useGridOperators(area);
  const cc = useChartColors();
  const isMobile = useIsMobile();

  const dwellingInfo = DWELLINGS.find((d) => d.id === dwelling)!;
  const kwhYear = dwellingInfo.kwhYear;
  const gridType = dwellingInfo.gridType;

  // Filter operators by dwelling type
  const operators: GridOperatorEntry[] = useMemo(() => {
    if (!gridData?.operators) return [];
    return gridData.operators.filter((o) => o.dwelling_type === gridType);
  }, [gridData, gridType]);

  // Auto-select first operator if none selected or current not available
  useEffect(() => {
    if (operators.length > 0 && operatorSlug !== CUSTOM_SLUG) {
      const found = operators.find((o) => o.slug === operatorSlug);
      if (!found) {
        setOperatorSlug(operators[0].slug);
      }
    }
  }, [operators, operatorSlug]);

  // Persist selections
  const selectOperator = useCallback((slug: string) => {
    setOperatorSlug(slug);
    localStorage.setItem(LS_OPERATOR, slug);
  }, []);

  const updateCustomFast = useCallback((v: string) => {
    setCustomFast(v);
    localStorage.setItem(LS_CUSTOM_FAST, v);
  }, []);

  const updateCustomTransfer = useCallback((v: string) => {
    setCustomTransfer(v);
    localStorage.setItem(LS_CUSTOM_TRANSFER, v);
  }, []);

  // Resolve active tariff
  const isCustom = operatorSlug === CUSTOM_SLUG;
  const activeOp = operators.find((o) => o.slug === operatorSlug);
  const fastFee = isCustom
    ? parseFloat(customFast) || 0
    : (activeOp?.fast_fee_sek_year ?? 0);
  const transferFee = isCustom
    ? parseFloat(customTransfer) || 0
    : (activeOp?.transfer_fee_ore ?? 0);
  const operatorName = isCustom ? "Custom" : (activeOp?.name ?? "—");

  // Amortize fixed fee into öre/kWh
  const elnatFastOre = (fastFee / kwhYear) * 100;
  const elnatTotalOre = elnatFastOre + transferFee;

  const chartData: ChartRow[] = useMemo(() => {
    if (!spotData?.months) return [];
    return spotData.months.map((m, i) => {
      const spotOre = m.avg_sek_kwh * 100;
      const base = spotOre + elnatTotalOre + ENERGISKATT_ORE;
      const momsOre = base * MOMS_RATE;
      const mm = m.month.slice(5);
      const yy = m.month.slice(2, 4);
      const label = MONTH_LABELS[mm] ?? mm;
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
  }, [spotData, elnatTotalOre]);

  const current = chartData.length > 0 ? chartData[chartData.length - 1] : null;
  const currentTotal = current
    ? current.spot + current.elnat + current.skatt + current.moms
    : null;

  const loading = spotLoading || gridLoading;

  return (
    <div className="space-y-4">
      <div className="bg-surface-primary rounded-2xl p-4">
        {/* Title row */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-3">
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

        {/* Grid operator selector */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <label className="text-[10px] text-content-muted uppercase tracking-wide">
            Grid operator
          </label>
          <select
            value={operatorSlug}
            onChange={(e) => selectOperator(e.target.value)}
            className="bg-surface-secondary border border-surface-tertiary rounded-lg px-2.5 py-1 text-xs text-content-primary focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {operators.map((o) => (
              <option key={o.slug} value={o.slug}>
                {o.name} — {o.city}
              </option>
            ))}
            <option value={CUSTOM_SLUG}>Other — enter your own</option>
          </select>
          {isCustom && (
            <div className="flex items-center gap-2">
              <label className="text-[10px] text-content-muted">Fixed</label>
              <input
                type="number"
                value={customFast}
                onChange={(e) => updateCustomFast(e.target.value)}
                className="w-20 bg-surface-secondary border border-surface-tertiary rounded px-2 py-0.5 text-xs text-content-primary"
                placeholder="SEK/yr"
              />
              <label className="text-[10px] text-content-muted">Transfer</label>
              <input
                type="number"
                value={customTransfer}
                onChange={(e) => updateCustomTransfer(e.target.value)}
                className="w-16 bg-surface-secondary border border-surface-tertiary rounded px-2 py-0.5 text-xs text-content-primary"
                placeholder="öre/kWh"
              />
            </div>
          )}
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

        {/* Loading / error */}
        {loading && !spotData && (
          <div className="animate-pulse">
            <div className="h-[280px] bg-surface-secondary rounded-xl" />
          </div>
        )}
        {spotError && (
          <p className="text-red-500 text-sm">
            Failed to load data: {spotError.message}
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
            <strong>Grid fee</strong> — {operatorName}
            {!isCustom && activeOp && (
              <>
                {" "}
                ({activeOp.valid_from.slice(0, 4)}). Fixed{" "}
                {fastFee.toLocaleString("sv-SE")} kr/yr ÷{" "}
                {kwhYear.toLocaleString("sv-SE")} kWh + transfer {transferFee}{" "}
                öre/kWh
              </>
            )}
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
          added on top of this.
          {!isCustom && activeOp?.source_url && (
            <>
              {" "}
              Source:{" "}
              <a
                href={activeOp.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-content-muted"
              >
                {new URL(activeOp.source_url).hostname}
              </a>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
