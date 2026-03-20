import { useState, useEffect } from "react";
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
import { currentCETHour, toLocalHour } from "../utils/formatters";
import { computeClippedDomain } from "../utils/chartScale";
import { useIsMobile } from "../hooks/useIsMobile";

const NOW_HOUR = currentCETHour();

// Unified prediction colors
const PRED_WEEKDAY_COLOR = "#9ca3af"; // gray-400
const PRED_LGBM_COLOR = "#fbbf24"; // amber-400 — complementary to blue DA

function priceColor(sek) {
  if (sek <= 0.4) return "#22c55e"; // green — cheap
  if (sek <= 0.7) return "#eab308"; // yellow — moderate
  return "#ef4444"; // red — expensive
}

function NowPriceLabel({ viewBox, value }) {
  if (!viewBox) return null;
  const { x, y } = viewBox;
  const text = value.toFixed(2);
  const w = text.length * 7 + 8;
  const h = 18;
  const offsetY = 14;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={y - h - offsetY}
        width={w}
        height={h}
        rx={4}
        fill="#1e293b"
        fillOpacity={0.9}
        stroke="#475569"
        strokeWidth={0.5}
      />
      <text
        x={x}
        y={y - h - offsetY + h / 2 + 1}
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#cbd5e1"
        fontSize={11}
        fontWeight={600}
      >
        {text}
      </text>
    </g>
  );
}

function CustomDot() {
  return null;
}

function CustomTooltip({ active, payload, label, showDetail }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm">
      <p className="text-gray-400">{label}</p>
      <p
        className="font-semibold"
        style={{ color: priceColor(p.price_sek_kwh) }}
      >
        {p.price_sek_kwh.toFixed(2)}{" "}
        <span className="text-gray-400 font-normal">SEK/kWh</span>
        <span className="text-gray-500 text-xs ml-2">Day-ahead</span>
      </p>
      <p className="text-gray-500 text-xs">
        {p.price_eur_mwh.toFixed(1)} EUR/MWh
      </p>
      {showDetail && p.imb_short != null && (
        <p className="text-orange-400 text-xs mt-1">
          Imbalance Short: {p.imb_short.toFixed(2)} SEK/kWh
          {p.price_sek_kwh > 0 && (
            <span className="ml-1 text-orange-500">
              ({((p.imb_short / p.price_sek_kwh - 1) * 100).toFixed(0)}% vs DA)
            </span>
          )}
        </p>
      )}
      {showDetail && p.imb_long != null && (
        <p className="text-teal-400 text-xs">
          Imbalance Long: {p.imb_long.toFixed(2)} SEK/kWh
        </p>
      )}
      {showDetail && p.forecast_low != null && (
        <p className="text-gray-400 text-xs mt-1">
          Weekday Avg {p.forecast_low.toFixed(2)}–
          {(p.forecast_low + p.forecast_band).toFixed(2)}
        </p>
      )}
      {p.lgbm_forecast != null && (
        <p className="text-amber-400 text-xs mt-1">
          LGBM {p.lgbm_forecast.toFixed(2)}
        </p>
      )}
      {/* Retrospective LGBM + forecast avg error */}
      {(p.retro_lgbm != null || (showDetail && p.forecast_avg != null)) && (
        <div className="mt-1 pt-1 border-t border-gray-700 text-xs">
          <p className="text-gray-500">Prediction:</p>
          {showDetail && p.forecast_avg != null && p.price_sek_kwh > 0 && (
            <p className="text-gray-400">
              Weekday Avg {p.forecast_avg.toFixed(2)}
              <span className="ml-1 text-gray-500">
                (err {((p.forecast_avg - p.price_sek_kwh) * 100).toFixed(1)}{" "}
                öre)
              </span>
            </p>
          )}
          {p.retro_lgbm != null && (
            <p className="text-amber-400">
              LGBM {p.retro_lgbm.toFixed(2)}
              {p.price_sek_kwh > 0 && (
                <span className="ml-1 text-amber-500">
                  (err {((p.retro_lgbm - p.price_sek_kwh) * 100).toFixed(1)}{" "}
                  öre)
                </span>
              )}
            </p>
          )}
        </div>
      )}
      {p.is_estimate && (
        <p className="text-yellow-500 text-xs mt-1">Estimated</p>
      )}
    </div>
  );
}

// Minute-precision UTC key for timestamp alignment between DA and balancing data
function tsKey(iso) {
  return iso.substring(0, 16); // "2026-03-15T23:00"
}

export function PriceChart({
  prices,
  isEstimate,
  forecast = null,
  lgbmForecast = null,
  retrospective = null,
  balancing = null,
  detailDefaultOpen = false,
  predictedAt = null,
}) {
  const [showDetail, setShowDetail] = useState(detailDefaultOpen);
  const isMobile = useIsMobile();

  useEffect(() => {
    setShowDetail(detailDefaultOpen);
  }, [detailDefaultOpen]);

  // Forecast lookup: hour (0-23) → { low, band, avg }
  const forecastByHour = {};
  if (forecast?.slots) {
    forecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        forecastByHour[s.hour] = {
          low: s.low_sek_kwh,
          band: s.high_sek_kwh - s.low_sek_kwh,
          avg: s.avg_sek_kwh,
        };
      }
    });
  }

  // LightGBM forecast lookup: hour (0-23) → predicted avg
  const lgbmByHour = {};
  if (lgbmForecast?.slots) {
    lgbmForecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        lgbmByHour[s.hour] = s.avg_sek_kwh;
      }
    });
  }

  // Retrospective lookups: hour (0-23) → predicted SEK/kWh per model
  const retroByModel = {};
  if (retrospective?.models) {
    for (const [model, entries] of Object.entries(retrospective.models)) {
      const byHour = {};
      for (const e of entries) {
        if (e.predicted_sek_kwh != null) byHour[e.hour] = e.predicted_sek_kwh;
      }
      retroByModel[model] = byHour;
    }
  }

  // Balancing lookup: tsKey → SEK/kWh for each category
  const imbShortByTs = {};
  const imbLongByTs = {};
  if (balancing) {
    for (const p of balancing.short)
      imbShortByTs[tsKey(p.timestamp_utc)] = parseFloat(p.price_sek_kwh);
    for (const p of balancing.long)
      imbLongByTs[tsKey(p.timestamp_utc)] = parseFloat(p.price_sek_kwh);
  }

  const chartData = prices.map((p) => {
    const localHour = toLocalHour(p.timestamp_utc);
    const hour = parseInt(localHour.split(":")[0], 10);
    const key = tsKey(p.timestamp_utc);
    const fh = forecastByHour[hour];
    return {
      ...p,
      hour: localHour,
      price_sek_kwh: parseFloat(p.price_sek_kwh),
      price_eur_mwh: parseFloat(p.price_eur_mwh),
      forecast_low: fh?.low ?? null,
      forecast_band: fh?.band ?? null,
      forecast_avg: fh?.avg ?? null,
      forecast_top: fh ? fh.low + fh.band : null,
      lgbm_forecast: lgbmByHour[hour] ?? null,
      imb_short: imbShortByTs[key] ?? null,
      imb_long: imbLongByTs[key] ?? null,
      retro_lgbm: retroByModel["lgbm"]?.[hour] ?? null,
    };
  });

  const avg =
    chartData.reduce((s, d) => s + d.price_sek_kwh, 0) / chartData.length;

  // Show only HH:00 labels on desktop, and every 2 hours on mobile to avoid overlap
  const tickFormatter = (value) => {
    if (!value.endsWith(":00")) return "";
    if (!isMobile) return value;
    const h = parseInt(value.slice(0, 2), 10);
    return h % 2 === 0 ? value : "";
  };

  const hasBalancing =
    balancing && (balancing.short.length > 0 || balancing.long.length > 0);
  const hasRetro =
    retrospective?.models && Object.keys(retrospective.models).length > 0;
  const hasRetroLgbm = hasRetro && retroByModel["lgbm"];
  const hasDetailData = hasBalancing || forecast != null;

  // Y-axis domain: compute from all visible series
  const domainKeys = ["price_sek_kwh"];
  if (lgbmForecast) domainKeys.push("lgbm_forecast");
  if (hasRetroLgbm) domainKeys.push("retro_lgbm");
  if (showDetail) {
    if (hasBalancing) domainKeys.push("imb_short", "imb_long");
    if (forecast) domainKeys.push("forecast_top");
  }
  const { domain } = computeClippedDomain(chartData, domainKeys);

  // Current hour data point for price annotation
  const nowEntry = chartData.find(
    (d) => parseInt(d.hour.split(":")[0], 10) === NOW_HOUR,
  );

  const chartHeight = isMobile ? 300 : 350;

  return (
    <div className="w-full">
      {isEstimate && (
        <div className="text-center mb-2">
          <p className="text-xs text-yellow-400">
            Prices not yet published — showing ML predictions
          </p>
          {predictedAt && (
            <p className="text-[10px] text-gray-500 mt-0.5">
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
      {(hasDetailData || lgbmForecast || hasRetroLgbm) && (
        <div className="flex items-center justify-between mb-2">
          <div className="flex gap-4 text-xs text-gray-400 flex-wrap">
            {!isEstimate && (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-5 border-t-[3px] border-blue-400" />
                Day-ahead
              </span>
            )}
            {(lgbmForecast || hasRetroLgbm) && (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-5 border-t-2 border-dashed border-amber-400" />
                LGBM
              </span>
            )}
            {showDetail && hasBalancing && (
              <>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t border-orange-400 opacity-50" />
                  Imbalance Short
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t border-teal-400 opacity-50" />
                  Imbalance Long
                </span>
              </>
            )}
            {showDetail && forecast && (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-5 border-t-2 border-dashed border-gray-400" />
                Weekday Avg
              </span>
            )}
          </div>
          {hasDetailData && (
            <button
              onClick={() => setShowDetail((v) => !v)}
              className={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
                showDetail
                  ? "border-sky-600 text-sky-400 bg-sky-900/20"
                  : "border-gray-700 text-gray-500 hover:text-gray-400"
              }`}
            >
              {showDetail ? "▪ Detail" : "◦ Detail"}
            </button>
          )}
        </div>
      )}

      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart
          data={chartData}
          margin={{ top: 20, right: 16, left: 0, bottom: 24 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#374151"
            vertical={false}
          />
          <XAxis
            dataKey="hour"
            interval={0}
            tickFormatter={tickFormatter}
            tick={{ fill: "#9ca3af", fontSize: 11, dy: 4 }}
            angle={-45}
            textAnchor="end"
          />
          <YAxis
            yAxisId="price"
            domain={domain}
            tickFormatter={(v) => `${v.toFixed(2)}`}
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            width={48}
          />
          <Tooltip content={<CustomTooltip showDetail={showDetail} />} />
          {!isEstimate && (
            <ReferenceLine
              yAxisId="price"
              y={avg}
              stroke="#6b7280"
              strokeDasharray="4 4"
              label={{ value: "avg", fill: "#6b7280", fontSize: 11 }}
            />
          )}

          {/* ── Detail series (toggled) ── */}

          {/* Weekday Avg forecast band */}
          {showDetail && forecast && (
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

          {/* Balancing overlay */}
          {showDetail && hasBalancing && (
            <>
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="imb_long"
                stroke="#2dd4bf"
                strokeWidth={0.8}
                strokeOpacity={0.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="imb_short"
                stroke="#f97316"
                strokeWidth={0.8}
                strokeOpacity={0.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
            </>
          )}

          {/* ── Always-visible series ── */}

          {/* LightGBM forward forecast (tomorrow) */}
          {lgbmForecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="lgbm_forecast"
              stroke={PRED_LGBM_COLOR}
              strokeWidth={2}
              strokeDasharray="8 4"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* Retrospective LGBM (today/review) */}
          {hasRetroLgbm && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="retro_lgbm"
              stroke={PRED_LGBM_COLOR}
              strokeWidth={1.5}
              strokeDasharray="4 4"
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
              stroke="#60a5fa"
              strokeWidth={3}
              dot={<CustomDot />}
              activeDot={{ r: 4, fill: "#60a5fa" }}
            />
          )}

          {/* Current price annotation with background for readability */}
          {nowEntry && (
            <ReferenceDot
              x={nowEntry.hour}
              y={nowEntry.price_sek_kwh}
              yAxisId="price"
              r={0}
              isFront
              label={
                <NowPriceLabel
                  value={nowEntry.price_sek_kwh}
                  viewBox={undefined}
                />
              }
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
