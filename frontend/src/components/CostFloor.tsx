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
import { ElhandlareRanking } from "./ElhandlareRanking";
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
  // Elnät bill (fixed — can't change)
  elnat: number;
  skatt: number;
  elnatVat: number;
  // Elhandel bill (spot + retailer markup in Phase 2)
  spot: number;
  elhandelVat: number;
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
  // Split into elnät and elhandel groups
  const elnatKeys = new Set(["Grid fee", "Energy tax", "VAT (elnät)"]);
  const elnatTotal = payload
    .filter((p) => elnatKeys.has(p.name))
    .reduce((s, p) => s + p.value, 0);
  const elhandelTotal = total - elnatTotal;
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
      {/* Elhandel group (top of chart → top of tooltip) */}
      <p className="text-[10px] text-content-faint mt-1 mb-0.5">
        Elhandel bill (min.)
      </p>
      {payload
        .filter((p) => !elnatKeys.has(p.name))
        .reverse()
        .map((p) => (
          <div key={p.name} className="flex items-center gap-2 text-xs">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: p.color }}
            />
            <span className="flex-1">{p.name}</span>
            <span className="tabular-nums font-mono">{p.value.toFixed(1)}</span>
          </div>
        ))}
      <div className="flex justify-between text-xs text-content-muted mt-0.5">
        <span>Subtotal</span>
        <span className="tabular-nums font-mono">
          {elhandelTotal.toFixed(1)}
        </span>
      </div>
      {/* Elnät group (bottom of chart → bottom of tooltip) */}
      <p className="text-[10px] text-content-faint mt-1.5 mb-0.5">
        Elnät bill (fixed)
      </p>
      {payload
        .filter((p) => elnatKeys.has(p.name))
        .reverse()
        .map((p) => (
          <div key={p.name} className="flex items-center gap-2 text-xs">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: p.color }}
            />
            <span className="flex-1">{p.name}</span>
            <span className="tabular-nums font-mono">{p.value.toFixed(1)}</span>
          </div>
        ))}
      <div className="flex justify-between text-xs text-content-muted mt-0.5">
        <span>Subtotal</span>
        <span className="tabular-nums font-mono">{elnatTotal.toFixed(1)}</span>
      </div>
      {/* Total */}
      <div
        className="border-t mt-1.5 pt-1 text-xs font-medium flex justify-between"
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
      // Elnät bill VAT: 25% on (grid fee + energy tax)
      const elnatBase = elnatTotalOre + ENERGISKATT_ORE;
      const elnatVat = elnatBase * MOMS_RATE;
      // Elhandel bill VAT: 25% on spot (+ retailer markup in Phase 2)
      const elhandelVat = spotOre * MOMS_RATE;
      const mm = m.month.slice(5);
      const yy = m.month.slice(2, 4);
      const label = MONTH_LABELS[mm] ?? mm;
      const showYear = mm === "01" || i === 0;
      return {
        month: m.month,
        monthLabel: showYear ? `${label} '${yy}` : label,
        elnat: Math.round(elnatTotalOre * 10) / 10,
        skatt: Math.round(ENERGISKATT_ORE * 10) / 10,
        elnatVat: Math.round(elnatVat * 10) / 10,
        spot: Math.round(spotOre * 10) / 10,
        elhandelVat: Math.round(elhandelVat * 10) / 10,
      };
    });
  }, [spotData, elnatTotalOre]);

  const current = chartData.length > 0 ? chartData[chartData.length - 1] : null;
  const currentElnat = current
    ? current.elnat + current.skatt + current.elnatVat
    : null;
  const currentElhandel = current ? current.spot + current.elhandelVat : null;
  const currentTotal =
    currentElnat != null && currentElhandel != null
      ? currentElnat + currentElhandel
      : null;

  const loading = spotLoading || gridLoading;

  return (
    <div className="space-y-4">
      <div className="bg-surface-primary rounded-2xl p-4">
        {/* Title row */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-3">
          <div className="flex-1">
            <h2 className="text-base font-medium text-content-primary">
              Monthly floor cost
            </h2>
            <p className="text-xs text-content-muted mt-0.5">
              What you pay regardless of retailer — spot + grid + tax + VAT
            </p>
            {chartData.length > 0 && (
              <p className="text-[10px] text-content-faint mt-0.5">
                {chartData[0].month} – {chartData[chartData.length - 1].month}
              </p>
            )}
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

        {/* Summary box — grouped by bill, 50/50 */}
        {currentTotal != null && current && (
          <div className="grid grid-cols-2 gap-2 mb-4">
            {/* Left: Total */}
            <div className="bg-surface-secondary rounded-xl py-3 px-4 text-center flex flex-col justify-center">
              <p className="text-[10px] text-content-muted mb-0.5">Total</p>
              <p className="text-2xl font-bold text-content-primary tabular-nums">
                {currentTotal.toFixed(0)}
              </p>
              <p className="text-[10px] text-content-faint">{PRICE_UNIT}</p>
            </div>
            {/* Right: Two bills stacked */}
            <div className="grid grid-rows-2 gap-2">
              <div className="bg-surface-secondary rounded-xl py-2.5 px-3 flex items-center justify-between">
                <p className="text-xs text-content-muted">
                  Elnät bill
                  <span className="text-content-faint ml-1">(fixed)</span>
                </p>
                <div className="text-right">
                  <span className="text-lg font-semibold text-content-primary tabular-nums">
                    {currentElnat!.toFixed(0)}
                  </span>
                  <span className="text-[10px] text-content-faint ml-1">
                    {PRICE_UNIT}
                  </span>
                </div>
              </div>
              <div className="bg-surface-secondary rounded-xl py-2.5 px-3 flex items-center justify-between">
                <p className="text-xs text-content-muted">
                  Elhandel bill
                  <span className="text-content-faint ml-1">(min.)</span>
                </p>
                <div className="text-right">
                  <span className="text-lg font-semibold text-content-primary tabular-nums">
                    {currentElhandel!.toFixed(0)}
                  </span>
                  <span className="text-[10px] text-content-faint ml-1">
                    {PRICE_UNIT}
                  </span>
                </div>
              </div>
            </div>
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
          <ResponsiveContainer width="100%" height={isMobile ? 300 : 380}>
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
                domain={[0, 400]}
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
              {/* ── Elnät bill (bottom, fixed) ── */}
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
                dataKey="elnatVat"
                name="VAT (elnät)"
                stackId="cost"
                fill={cc.costMoms}
              />
              {/* ── Elhandel bill (top, your choice) ── */}
              <Bar
                dataKey="spot"
                name="Spot price"
                stackId="cost"
                fill={cc.costSpot}
              />
              <Bar
                dataKey="elhandelVat"
                name="VAT (elhandel)"
                stackId="cost"
                fill={cc.costMoms}
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Source note */}
      <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
        <h3 className="text-base font-medium text-content-primary">
          Two separate bills
        </h3>
        <div className="text-xs text-content-muted space-y-3">
          <div>
            <p className="font-medium text-content-secondary mb-1">
              Elnät bill — fixed, based on your address
            </p>
            <ul className="space-y-1 pl-4 list-disc marker:text-content-faint">
              <li>
                <strong>Grid fee</strong> — {operatorName}
                {!isCustom && activeOp && (
                  <> ({activeOp.valid_from.slice(0, 4)})</>
                )}
              </li>
              <li>
                <strong>Energy tax</strong> — {ENERGISKATT_ORE} öre/kWh (2026)
              </li>
            </ul>
          </div>
          <div>
            <p className="font-medium text-content-secondary mb-1">
              Elhandel bill — your retailer choice matters
            </p>
            <ul className="space-y-1 pl-4 list-disc marker:text-content-faint">
              <li>
                <strong>Spot price</strong> — Nord Pool {area} monthly avg (same
                for all retailers)
              </li>
              <li>
                <strong>Retailer markup</strong> — company markup + monthly fee
                (varies by retailer, see Retailer comparison below)
              </li>
            </ul>
          </div>
        </div>
        {!isCustom && activeOp?.source_url && (
          <p className="text-xs text-content-faint mt-2">
            Grid fee source:{" "}
            <a
              href={activeOp.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-muted"
            >
              {new URL(activeOp.source_url).hostname}
            </a>
          </p>
        )}
      </div>

      <ElhandlareRanking area={area} dwelling={dwelling} kwhYear={kwhYear} />

      {/* Data sources & market notes — transparency block */}
      <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
        <div>
          <h2 className="text-base font-medium text-content-primary">
            Data sources & market notes
          </h2>
          <p className="text-xs text-content-muted mt-0.5">
            Where the numbers come from, and two market shifts worth knowing.
          </p>
        </div>

        <ul className="text-xs text-content-muted space-y-1.5 pl-4 list-disc marker:text-content-faint">
          <li>
            <strong>Spot price</strong> — day-ahead auction on{" "}
            <a
              href="https://www.nordpoolgroup.com/en/Market-data1/Dayahead/Area-Prices/SE/Hourly/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              Nord Pool
            </a>{" "}
            for SE1–SE4, collected via{" "}
            <a
              href="https://transparency.entsoe.eu/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              ENTSO-E Transparency Platform
            </a>
          </li>
          <li>
            <strong>Grid fees</strong> — each operator&apos;s published tariff,
            cross-checked against{" "}
            <a
              href="https://ei.se/om-oss/statistik-och-oppna-data/oppna-data"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              Ei öppna data
            </a>
          </li>
          <li>
            <strong>Energy tax</strong> — 36 öre/kWh (2026), billed via the grid
            company since 2018 per{" "}
            <a
              href="https://www.skatteverket.se/privat/skatter/fastigheterochbostad/skattpaenergi.4.18e1b10334ebe8bc80003395.html"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              Skatteverket
            </a>
          </li>
          <li>
            <strong>VAT</strong> — 25% applied on both bills (grid side: fee +
            tax; retail side: spot + markup + monthly fee)
          </li>
          <li>
            <strong>Retailer figures</strong> — each company&apos;s
            avtalsvillkor plus{" "}
            <a
              href="https://elpriskollen.se"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              Elpriskollen
            </a>{" "}
            (2025–2026)
          </li>
        </ul>

        <div className="pt-2 border-t border-surface-tertiary/40 space-y-2">
          <p className="text-xs text-content-muted leading-relaxed">
            <span className="font-medium text-content-secondary">
              Moving toward 15-minute pricing (kvartspris):
            </span>{" "}
            Sweden began rolling out 15-minute imbalance settlement in May 2025
            under the{" "}
            <a
              href="https://energy.ec.europa.eu/topics/markets-and-consumers/clean-energy-all-europeans-package_en"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              EU Clean Energy Package (2019/944)
            </a>
            . Most variable-price contracts are expected to be priced in
            15-minute slots rather than monthly averages going forward — see{" "}
            <a
              href="https://www.svk.se/aktorsportalen/elmarknad/kvartsvis-avrakning/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary"
            >
              Svenska kraftnät
            </a>
            .
          </p>
          <p className="text-[11px] text-content-faint leading-relaxed">
            Unagi is a personal project — verify figures against each
            provider&apos;s official site before signing anything.
          </p>
        </div>
      </div>
    </div>
  );
}
