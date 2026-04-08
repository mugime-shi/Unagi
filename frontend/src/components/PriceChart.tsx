import { ReactElement, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
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
import {
  currentCETHour,
  formatPrice,
  PRICE_UNIT,
  toLocalHour,
} from "../utils/formatters";
import { computeClippedDomain } from "../utils/chartScale";
import { useChartColors, type ChartColors } from "../hooks/useChartColors";
import { useIsMobile } from "../hooks/useIsMobile";
import type {
  BalancingPrice,
  BalancingResponse,
  ChartDataPoint,
  ForecastResponse,
  LgbmForecastResponse,
  PricePoint,
  RetrospectiveResponse,
  ShapExplanations,
  ShapFeature,
} from "../types/index";

const NOW_HOUR: number = currentCETHour();

function priceColor(sek: number): string {
  if (sek <= 0.4) return "#22d3ee"; // cyan — bioluminescent (cheap)
  if (sek <= 0.7) return "#fbbf24"; // amber — eel belly (moderate)
  return "#fb923c"; // orange — electric shock (expensive)
}

interface NowPriceLabelProps {
  viewBox?: { x: number; y: number };
  value: number;
  cc: ChartColors;
}

function NowPriceLabel({
  viewBox,
  value,
  cc,
}: NowPriceLabelProps): ReactElement | null {
  if (!viewBox) return null;
  const { x, y } = viewBox;
  const text = formatPrice(value);
  const w = text.length * 7 + 8;
  const h = 18;
  const dotR = 5;
  const gap = 8;
  // Place label below the dot when there's not enough space above
  const placeBelow = y - dotR - gap < h;
  const rectY = placeBelow ? y + dotR + gap : y - dotR - gap - h;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={rectY}
        width={w}
        height={h}
        rx={4}
        fill={cc.tooltipBg}
        fillOpacity={0.9}
        stroke={cc.tooltipBorder}
        strokeWidth={0.5}
      />
      <text
        x={x}
        y={rectY + h / 2 + 1}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={cc.tooltipText}
        fontSize={11}
        fontWeight={600}
      >
        {text}
      </text>
    </g>
  );
}

function CustomDot(): null {
  return null;
}

interface PriceChartTooltipProps extends TooltipContentProps<
  ValueType,
  NameType
> {
  showWeekdayAvg: boolean;
  cc: ChartColors;
}

function CustomTooltip({
  active,
  payload,
  label,
  showWeekdayAvg,
  cc,
}: PriceChartTooltipProps): ReactElement | null {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as ChartDataPoint;
  const estimated = p.is_estimate;

  // Best LGBM value: forward forecast or retrospective
  const lgbmVal = p.lgbm_forecast ?? p.retro_lgbm ?? null;

  return (
    <div
      className="rounded-lg px-3 py-2 text-sm border"
      style={{
        background: cc.tooltipBg,
        borderColor: cc.tooltipBorder,
        color: cc.tooltipText,
      }}
    >
      <p style={{ color: cc.axis }}>{label}</p>

      {/* Day-ahead price — only when actually published */}
      {!estimated && (
        <>
          <p
            className="font-semibold"
            style={{ color: priceColor(p.price_sek_kwh) }}
          >
            {formatPrice(p.price_sek_kwh)}{" "}
            <span style={{ color: cc.axis }} className="font-normal">
              {PRICE_UNIT}
            </span>
            <span style={{ color: cc.axisDim }} className="text-xs ml-2">
              Day-ahead
            </span>
          </p>
          <p style={{ color: cc.axisDim }} className="text-xs">
            {p.price_eur_mwh.toFixed(1)} EUR/MWh
          </p>
        </>
      )}

      {/* Balancing prices — only with published DA */}
      {!estimated && p.imb_short != null && (
        <p style={{ color: cc.imbShort }} className="text-xs mt-1">
          Imbalance Short: {formatPrice(p.imb_short)} {PRICE_UNIT}
          {p.price_sek_kwh > 0 && (
            <span className="ml-1 opacity-80">
              ({((p.imb_short / p.price_sek_kwh - 1) * 100).toFixed(0)}% vs DA)
            </span>
          )}
        </p>
      )}
      {!estimated && p.imb_long != null && (
        <p style={{ color: cc.imbLong }} className="text-xs">
          Imbalance Long: {formatPrice(p.imb_long)} {PRICE_UNIT}
        </p>
      )}

      {/* Weekday Avg — forward forecast only */}
      {showWeekdayAvg && p.forecast_low != null && (
        <p style={{ color: cc.weekdayAvg }} className="text-xs mt-1">
          Weekday Avg {formatPrice(p.forecast_low)}–
          {formatPrice((p.forecast_low ?? 0) + (p.forecast_band ?? 0))}
        </p>
      )}

      {/* LGBM — single unified line (forecast or retro, never both) */}
      {lgbmVal != null && (
        <p
          style={{ color: cc.lgbm }}
          className={`text-xs mt-1 ${estimated ? "font-semibold text-sm" : ""}`}
        >
          LGBM {formatPrice(lgbmVal)}
          {p.lgbm_low != null && p.lgbm_band != null && (
            <span className="ml-1 opacity-70">
              [{formatPrice(p.lgbm_low)}–
              {formatPrice((p.lgbm_low ?? 0) + (p.lgbm_band ?? 0))}]
            </span>
          )}
          {estimated && (
            <span style={{ color: cc.axis }} className="font-normal ml-1">
              {PRICE_UNIT}
            </span>
          )}
        </p>
      )}

      {/* SHAP explanations */}
      {p.shap_top != null && p.shap_top.length > 0 && (
        <div className="text-xs mt-0.5 space-y-0.5">
          {p.shap_top.slice(0, 3).map((s: ShapFeature) => (
            <p
              key={s.group}
              style={{
                color: s.impact > 0 ? cc.lgbm : cc.imbLong,
                opacity: 0.8,
              }}
            >
              {s.impact > 0 ? "\u2191" : "\u2193"} {s.group} (
              {s.impact > 0 ? "+" : ""}
              {s.impact.toFixed(2)})
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// Minute-precision UTC key for timestamp alignment between DA and balancing data
function tsKey(iso: string): string {
  return iso.substring(0, 16); // "2026-03-15T23:00"
}

interface PriceChartProps {
  prices: PricePoint[];
  isEstimate: boolean;
  forecast?: Pick<ForecastResponse, "slots"> | null;
  lgbmForecast?: Pick<LgbmForecastResponse, "slots"> | null;
  retrospective?: Pick<RetrospectiveResponse, "models"> | null;
  shapExplanations?: Pick<ShapExplanations, "hours"> | null;
  balancing?: BalancingResponse | null;
  defaultShowLgbm?: boolean;
  defaultShowWeekdayAvg?: boolean;
  predictedAt?: string | null;
  showNowMarker?: boolean;
}

export function PriceChart({
  prices,
  isEstimate,
  forecast = null,
  lgbmForecast = null,
  retrospective = null,
  shapExplanations = null,
  balancing = null,
  defaultShowLgbm = true,
  defaultShowWeekdayAvg = true,
  predictedAt = null,
  showNowMarker = true,
}: PriceChartProps): ReactElement {
  const cc = useChartColors();
  const PRED_WEEKDAY_COLOR = cc.weekdayAvg;
  const PRED_LGBM_COLOR = cc.lgbm;

  const [showLgbm, setShowLgbm] = useState<boolean>(defaultShowLgbm);
  const [showWeekdayAvg, setShowWeekdayAvg] = useState<boolean>(
    defaultShowWeekdayAvg,
  );
  const [hoveredData, setHoveredData] = useState<ChartDataPoint | null>(null);
  const isMobile = useIsMobile();

  // Forecast lookup: hour (0-23) -> { low, band, avg }
  const forecastByHour: Record<
    number,
    { low: number | null; band: number; avg: number }
  > = {};
  if (forecast?.slots) {
    forecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        forecastByHour[s.hour] = {
          low: s.low_sek_kwh ?? null,
          band: (s.high_sek_kwh ?? 0) - (s.low_sek_kwh ?? 0),
          avg: s.avg_sek_kwh,
        };
      }
    });
  }

  // LightGBM forecast lookup: hour (0-23) -> predicted avg
  const lgbmByHour: Record<
    number,
    { avg: number; low: number | null; high: number | null }
  > = {};
  if (lgbmForecast?.slots) {
    lgbmForecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        lgbmByHour[s.hour] = {
          avg: s.avg_sek_kwh,
          low: s.low_sek_kwh ?? null,
          high: s.high_sek_kwh ?? null,
        };
      }
    });
  }

  // SHAP explanation lookup: hour (0-23) -> top contributing groups
  const shapByHour: Record<number, ShapFeature[]> = {};
  if (shapExplanations?.hours) {
    for (const h of shapExplanations.hours) {
      shapByHour[h.hour] = h.top;
    }
  }

  // Retrospective lookups: hour (0-23) -> predicted SEK/kWh per model
  const retroByModel: Record<string, Record<number, number>> = {};
  if (retrospective?.models) {
    for (const [model, entries] of Object.entries(retrospective.models)) {
      const byHour: Record<number, number> = {};
      for (const e of entries) {
        if (e.predicted_sek_kwh != null) byHour[e.hour] = e.predicted_sek_kwh;
      }
      retroByModel[model] = byHour;
    }
  }

  // Balancing lookup: tsKey -> SEK/kWh for each category
  const imbShortByTs: Record<string, number> = {};
  const imbLongByTs: Record<string, number> = {};
  if (balancing) {
    for (const p of balancing.short)
      imbShortByTs[tsKey(p.timestamp_utc)] = parseFloat(
        String(p.price_sek_kwh),
      );
    for (const p of balancing.long)
      imbLongByTs[tsKey(p.timestamp_utc)] = parseFloat(String(p.price_sek_kwh));
  }

  const chartData: ChartDataPoint[] = prices.map((p) => {
    const localHour = toLocalHour(p.timestamp_utc);
    const hour = parseInt(localHour.split(":")[0], 10);
    const key = tsKey(p.timestamp_utc);
    const fh = forecastByHour[hour];
    return {
      ...p,
      hour: localHour,
      price_sek_kwh: parseFloat(String(p.price_sek_kwh)),
      price_eur_mwh: parseFloat(String(p.price_eur_mwh)),
      forecast_low: fh?.low ?? null,
      forecast_band: fh?.band ?? null,
      forecast_avg: fh?.avg ?? null,
      forecast_top: fh ? (fh.low ?? 0) + fh.band : null,
      lgbm_forecast: lgbmByHour[hour]?.avg ?? null,
      lgbm_low: lgbmByHour[hour]?.low ?? null,
      lgbm_band:
        lgbmByHour[hour]?.low != null && lgbmByHour[hour]?.high != null
          ? (lgbmByHour[hour].high as number) - (lgbmByHour[hour].low as number)
          : null,
      lgbm_top: lgbmByHour[hour]?.high ?? null,
      imb_short: imbShortByTs[key] ?? null,
      imb_long: imbLongByTs[key] ?? null,
      retro_lgbm: retroByModel["lgbm"]?.[hour] ?? null,
      retro_weekday: retroByModel["same_weekday_avg"]?.[hour] ?? null,
      shap_top: shapByHour[hour] ?? null,
    };
  });

  // Average line — computed from the primary visible series so it matches the
  // Min/Avg/Max cards. DA when published, LGBM forecast (or its retrospective)
  // when the prices are still an estimate. The line picks up the main series
  // color so users can tell at a glance which average it refers to.
  const avgSource: number[] = chartData
    .map((d) => {
      if (!isEstimate) return d.price_sek_kwh;
      return d.lgbm_forecast ?? d.retro_lgbm ?? null;
    })
    .filter((v): v is number => v != null);
  const avgValid: boolean = avgSource.length > 0;
  const avg: number = avgValid
    ? avgSource.reduce((s, v) => s + v, 0) / avgSource.length
    : 0;
  const avgColor: string = isEstimate ? PRED_LGBM_COLOR : cc.daLine;

  // Build explicit tick values from :00 entries so labels survive irregular slot counts
  const hourlyTicks: string[] = chartData
    .map((d) => d.hour)
    .filter((h) => h.endsWith(":00"));
  const filteredTicks: string[] = isMobile
    ? hourlyTicks.filter((_, i) => i % 2 === 0)
    : hourlyTicks;

  const tickFormatter = (value: string): string => value;

  const hasBalancing =
    balancing != null &&
    (balancing.short.length > 0 || balancing.long.length > 0);
  const hasRetroLgbm =
    retrospective?.models != null &&
    retroByModel["lgbm"] != null &&
    Object.keys(retroByModel["lgbm"]).length > 0;
  const hasRetroWeekday =
    retrospective?.models != null &&
    retroByModel["same_weekday_avg"] != null &&
    Object.keys(retroByModel["same_weekday_avg"]).length > 0;

  const hasLgbmData = lgbmForecast != null || hasRetroLgbm;
  const hasWeekdayAvgData = forecast != null || hasRetroWeekday;

  // Y-axis domain: compute from all visible series
  // When estimated, exclude fallback price_sek_kwh — use LGBM forecast for scale
  const domainKeys: (keyof ChartDataPoint)[] = isEstimate
    ? []
    : ["price_sek_kwh"];
  if (showLgbm && lgbmForecast) domainKeys.push("lgbm_forecast", "lgbm_top");
  if (showLgbm && hasRetroLgbm) domainKeys.push("retro_lgbm");
  if (showWeekdayAvg && forecast) domainKeys.push("forecast_top");
  if (showWeekdayAvg && hasRetroWeekday) domainKeys.push("retro_weekday");
  if (hasBalancing) domainKeys.push("imb_short", "imb_long");
  // Ensure at least lgbm_forecast is included when estimated and no other keys
  if (isEstimate && domainKeys.length === 0)
    domainKeys.push("lgbm_forecast", "lgbm_top");
  const { domain } = computeClippedDomain(chartData, domainKeys);

  // Current hour data point for price annotation
  const nowEntry = chartData.find(
    (d) => parseInt(d.hour.split(":")[0], 10) === NOW_HOUR,
  );

  const chartHeight = isMobile ? 300 : 350;

  // Legend live values: hovered point or latest available per series
  // When showNowMarker is false (Tomorrow tab), only show values on hover
  const legendDA: ChartDataPoint | null =
    hoveredData ??
    (showNowMarker ? (nowEntry ?? chartData[chartData.length - 1]) : null);
  const legendImb: ChartDataPoint | null =
    hoveredData ??
    (showNowMarker
      ? (() => {
          for (let i = chartData.length - 1; i >= 0; i--) {
            if (chartData[i].imb_short != null) return chartData[i];
          }
          return null;
        })()
      : null);

  return (
    <div className="w-full">
      {isEstimate && (
        <div className="text-center mb-2">
          <p className="text-xs text-yellow-600 dark:text-yellow-400">
            Prices not yet published — showing ML predictions
          </p>
          {predictedAt && (
            <p className="text-[10px] text-content-muted mt-0.5">
              Predicted{" "}
              {new Date(predictedAt).toLocaleDateString("sv-SE", {
                timeZone: "Europe/Stockholm",
              })}{" "}
              (
              {new Date(predictedAt).toLocaleDateString("en-SE", {
                timeZone: "Europe/Stockholm",
                weekday: "short",
              })}
              ){" "}
              {new Date(predictedAt).toLocaleTimeString("sv-SE", {
                timeZone: "Europe/Stockholm",
                hour: "2-digit",
                minute: "2-digit",
              })}{" "}
              CET
            </p>
          )}
        </div>
      )}

      {/* Legend row */}
      <div className="flex items-center justify-end mb-2">
        <div className="flex items-center gap-3 text-xs text-content-secondary flex-wrap">
          {/* Day-ahead legend — only with published prices */}
          {!isEstimate && (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-5 border-t-[3px]"
                style={{ borderColor: cc.daLine }}
              />
              Day-ahead
              {legendDA?.price_sek_kwh != null && (
                <span style={{ color: cc.daLine }} className="font-medium">
                  {formatPrice(legendDA.price_sek_kwh)}
                </span>
              )}
            </span>
          )}

          {/* Balancing legends */}
          {hasBalancing && (
            <>
              <span className="flex items-center gap-1.5">
                <span
                  className="inline-block w-5 border-t"
                  style={{ borderColor: cc.imbShort }}
                />
                Imb Short
                {legendImb?.imb_short != null && (
                  <span style={{ color: cc.imbShort }} className="font-medium">
                    {formatPrice(legendImb.imb_short)}
                  </span>
                )}
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="inline-block w-5 border-t"
                  style={{ borderColor: cc.imbLong }}
                />
                Imb Long
                {legendImb?.imb_long != null && (
                  <span style={{ color: cc.imbLong }} className="font-medium">
                    {formatPrice(legendImb.imb_long)}
                  </span>
                )}
              </span>
            </>
          )}

          {/* Model toggles — serve as both legend and toggle */}
          {hasLgbmData && (
            <button
              onClick={() => setShowLgbm((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border transition-colors ${
                showLgbm
                  ? "border-amber-600 text-amber-600 dark:text-amber-400 bg-amber-100/40 dark:bg-amber-900/20"
                  : "border-surface-tertiary text-content-muted hover:text-content-secondary"
              }`}
            >
              <span className="inline-block w-4 border-t-2 border-dashed border-current" />
              LGBM
            </button>
          )}
          {hasWeekdayAvgData && (
            <button
              onClick={() => setShowWeekdayAvg((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border transition-colors ${
                showWeekdayAvg
                  ? "border-surface-tertiary text-content-primary bg-surface-tertiary/30"
                  : "border-surface-tertiary text-content-muted hover:text-content-secondary"
              }`}
            >
              <span className="inline-block w-4 border-t-2 border-dashed border-current" />
              Weekday Avg
            </button>
          )}

          {(legendDA || legendImb) && (
            <span className="text-content-muted">{PRICE_UNIT}</span>
          )}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart
          data={chartData}
          margin={{ top: 24, right: 16, left: 0, bottom: 24 }}
          onMouseMove={(e: Record<string, unknown> | null) => {
            const ap = (e as { activePayload?: { payload: ChartDataPoint }[] })
              ?.activePayload;
            if (ap?.[0]?.payload) {
              setHoveredData(ap[0].payload);
            }
          }}
          onMouseLeave={() => setHoveredData(null)}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={cc.grid}
            vertical={false}
          />
          <XAxis
            dataKey="hour"
            ticks={filteredTicks}
            tickFormatter={tickFormatter}
            tick={{ fill: cc.axis, fontSize: 11, dy: 4 }}
            angle={-45}
            textAnchor="end"
          />
          <YAxis
            yAxisId="price"
            domain={domain}
            tickFormatter={(v: number) => formatPrice(v)}
            tick={{ fill: cc.axis, fontSize: 11 }}
            width={isMobile ? 32 : 48}
            padding={{ top: 16 }}
          />
          <Tooltip
            content={(props) => (
              <CustomTooltip
                {...props}
                showWeekdayAvg={showWeekdayAvg}
                cc={cc}
              />
            )}
          />
          {avgValid && (
            <ReferenceLine
              yAxisId="price"
              y={avg}
              stroke={avgColor}
              strokeOpacity={0.55}
              strokeDasharray="4 4"
              label={{
                value: "avg",
                fill: avgColor,
                fontSize: 11,
                fillOpacity: 0.85,
              }}
            />
          )}

          {/* -- Balancing overlay — always visible -- */}
          {hasBalancing && (
            <>
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="imb_long"
                stroke={cc.imbLong}
                strokeWidth={1.5}
                strokeOpacity={0.6}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="imb_short"
                stroke={cc.imbShort}
                strokeWidth={1.5}
                strokeOpacity={0.6}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
            </>
          )}

          {/* -- WeekDay Avg forecast band (toggled) -- */}
          {showWeekdayAvg && forecast && (
            <>
              <Area
                yAxisId="price"
                type="monotone"
                dataKey="forecast_low"
                stackId="fc"
                fill="transparent"
                stroke="none"
                legendType="none"
                connectNulls={false}
                isAnimationActive={false}
              />
              <Area
                yAxisId="price"
                type="monotone"
                dataKey="forecast_band"
                stackId="fc"
                fill={PRED_WEEKDAY_COLOR + "26"}
                stroke={PRED_WEEKDAY_COLOR + "66"}
                strokeWidth={1}
                strokeDasharray="4 4"
                legendType="none"
                connectNulls={false}
                isAnimationActive={false}
              />
            </>
          )}

          {/* WeekDay Avg center line — forward forecast (toggled) */}
          {showWeekdayAvg && forecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="forecast_avg"
              stroke={PRED_WEEKDAY_COLOR}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* WeekDay Avg retrospective line (toggled) */}
          {showWeekdayAvg && hasRetroWeekday && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="retro_weekday"
              stroke={PRED_WEEKDAY_COLOR}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* -- LightGBM prediction band (80% CI) — toggled -- */}
          {showLgbm && lgbmForecast && (
            <>
              <Area
                yAxisId="price"
                type="monotone"
                dataKey="lgbm_low"
                stackId="lgbm"
                fill="transparent"
                stroke="none"
                legendType="none"
                connectNulls={false}
                isAnimationActive={false}
              />
              <Area
                yAxisId="price"
                type="monotone"
                dataKey="lgbm_band"
                stackId="lgbm"
                fill={PRED_LGBM_COLOR + "26"}
                stroke={PRED_LGBM_COLOR + "66"}
                strokeWidth={1}
                strokeDasharray="4 4"
                legendType="none"
                connectNulls={false}
                isAnimationActive={false}
              />
            </>
          )}

          {/* LightGBM forward forecast line — toggled */}
          {showLgbm && lgbmForecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="lgbm_forecast"
              stroke={PRED_LGBM_COLOR}
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* Retrospective LGBM line — only when lgbmForecast is absent (avoids duplicate) */}
          {showLgbm && hasRetroLgbm && !lgbmForecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="retro_lgbm"
              stroke={PRED_LGBM_COLOR}
              strokeWidth={1.5}
              strokeDasharray="5 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* Day-ahead line — rendered last so it stays on top */}
          {!isEstimate && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price_sek_kwh"
              stroke={cc.daLine}
              strokeWidth={3}
              dot={<CustomDot />}
              activeDot={{ r: 4, fill: cc.daLine }}
            />
          )}

          {/* Estimate line — fallback when no lgbmForecast is available */}
          {isEstimate && !lgbmForecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price_sek_kwh"
              stroke={PRED_LGBM_COLOR}
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={false}
              activeDot={{ r: 4, fill: PRED_LGBM_COLOR }}
              isAnimationActive={false}
            />
          )}

          {/* Vertical line at current hour */}
          {showNowMarker && nowEntry && (
            <ReferenceLine
              yAxisId="price"
              x={nowEntry.hour}
              stroke={cc.axis}
              strokeWidth={1}
              strokeDasharray="3 3"
              strokeOpacity={0.4}
            />
          )}

          {/* Current price dot + label — only with published prices */}
          {showNowMarker && nowEntry && !isEstimate && (
            <ReferenceDot
              x={nowEntry.hour}
              y={nowEntry.price_sek_kwh}
              yAxisId="price"
              r={5}
              fill={cc.daLine}
              stroke={cc.nowDotRing}
              strokeWidth={2}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              {...({ isFront: true } as Record<string, unknown>)}
              label={
                <NowPriceLabel
                  value={nowEntry.price_sek_kwh}
                  viewBox={undefined}
                  cc={cc}
                />
              }
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
