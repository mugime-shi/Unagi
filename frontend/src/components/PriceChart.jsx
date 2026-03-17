import { useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { currentCETHour, toLocalHour } from '../utils/formatters'

const NOW_HOUR = currentCETHour()

// Generation sources for overlay background
const GEN_SOURCES = [
  { key: 'gen_hydro',   color: '#3b82f6' },
  { key: 'gen_wind',    color: '#22d3ee' },
  { key: 'gen_nuclear', color: '#eab308' },
  { key: 'gen_solar',   color: '#f97316' },
  { key: 'gen_other',   color: '#6b7280' },
]

function toUtc(iso) {
  return iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
}

function priceColor(sek) {
  if (sek <= 0.40) return '#22c55e'   // green — cheap
  if (sek <= 0.70) return '#eab308'   // yellow — moderate
  return '#ef4444'                    // red — expensive
}

function CustomDot({ cx, cy, payload }) {
  const hour = parseInt(toLocalHour(payload.timestamp_utc).split(':')[0], 10)
  if (hour !== NOW_HOUR) return null
  return <circle cx={cx} cy={cy} r={6} fill="#60a5fa" stroke="#1e40af" strokeWidth={2} />
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm">
      <p className="text-gray-400">{label}</p>
      <p className="font-semibold" style={{ color: priceColor(p.price_sek_kwh) }}>
        {p.price_sek_kwh.toFixed(2)} <span className="text-gray-400 font-normal">SEK/kWh</span>
        <span className="text-gray-500 text-xs ml-2">Day-ahead</span>
      </p>
      <p className="text-gray-500 text-xs">{p.price_eur_mwh.toFixed(1)} EUR/MWh</p>
      {p.imb_short != null && (
        <p className="text-orange-400 text-xs mt-1">
          Imbalance Short: {p.imb_short.toFixed(2)} SEK/kWh
          {p.price_sek_kwh > 0 && (
            <span className="ml-1 text-orange-500">
              ({((p.imb_short / p.price_sek_kwh - 1) * 100).toFixed(0)}% vs DA)
            </span>
          )}
        </p>
      )}
      {p.imb_long != null && (
        <p className="text-green-400 text-xs">
          Imbalance Long:  {p.imb_long.toFixed(2)} SEK/kWh
        </p>
      )}
      {p.forecast_low != null && (
        <p className="text-indigo-400 text-xs mt-1">
          Weekday Avg {p.forecast_low.toFixed(2)}–{(p.forecast_low + p.forecast_band).toFixed(2)}
        </p>
      )}
      {p.lgbm_forecast != null && (
        <p className="text-emerald-400 text-xs">
          LGBM {p.lgbm_forecast.toFixed(2)}
        </p>
      )}
      {/* Retrospective predictions */}
      {(p.retro_weekday != null || p.retro_lgbm != null) && (
        <div className="mt-1 pt-1 border-t border-gray-700 text-xs">
          <p className="text-gray-500">Yesterday&apos;s prediction:</p>
          {p.retro_weekday != null && (
            <p className="text-violet-400">
              Weekday {p.retro_weekday.toFixed(2)}
              {p.price_sek_kwh > 0 && (
                <span className="ml-1 text-violet-500">
                  (err {((p.retro_weekday - p.price_sek_kwh) * 100).toFixed(1)} öre)
                </span>
              )}
            </p>
          )}
          {p.retro_lgbm != null && (
            <p className="text-rose-400">
              LGBM {p.retro_lgbm.toFixed(2)}
              {p.price_sek_kwh > 0 && (
                <span className="ml-1 text-rose-500">
                  (err {((p.retro_lgbm - p.price_sek_kwh) * 100).toFixed(1)} öre)
                </span>
              )}
            </p>
          )}
        </div>
      )}
      {/* Generation breakdown when overlay is active */}
      {p.gen_hydro != null && (
        <div className="mt-1 pt-1 border-t border-gray-700 text-xs">
          {p.gen_hydro > 0 && <p className="text-blue-400">Hydro {Math.round(p.gen_hydro)} MW</p>}
          {p.gen_wind > 0 && <p className="text-cyan-400">Wind {Math.round(p.gen_wind)} MW</p>}
          {p.gen_nuclear > 0 && <p className="text-yellow-400">Nuclear {Math.round(p.gen_nuclear)} MW</p>}
          {p.gen_other > 0 && <p className="text-gray-400">Other {Math.round(p.gen_other)} MW</p>}
        </div>
      )}
      {p.is_estimate && <p className="text-yellow-500 text-xs mt-1">Estimated</p>}
    </div>
  )
}

// Minute-precision UTC key for timestamp alignment between DA and balancing data
function tsKey(iso) {
  return iso.substring(0, 16)  // "2026-03-15T23:00"
}

export function PriceChart({ prices, isEstimate, forecast = null, lgbmForecast = null, retrospective = null, balancing = null, generationTimeSeries = null }) {
  const [showGen, setShowGen] = useState(false)

  // Forecast lookup: hour (0-23) → { low, band, avg }
  const forecastByHour = {}
  if (forecast?.slots) {
    forecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        forecastByHour[s.hour] = {
          low:  s.low_sek_kwh,
          band: s.high_sek_kwh - s.low_sek_kwh,
          avg:  s.avg_sek_kwh,
        }
      }
    })
  }

  // LightGBM forecast lookup: hour (0-23) → predicted avg
  const lgbmByHour = {}
  if (lgbmForecast?.slots) {
    lgbmForecast.slots.forEach((s) => {
      if (s.avg_sek_kwh != null) {
        lgbmByHour[s.hour] = s.avg_sek_kwh
      }
    })
  }

  // Retrospective lookups: hour (0-23) → predicted SEK/kWh per model
  const retroByModel = {}
  if (retrospective?.models) {
    for (const [model, entries] of Object.entries(retrospective.models)) {
      const byHour = {}
      for (const e of entries) {
        if (e.predicted_sek_kwh != null) byHour[e.hour] = e.predicted_sek_kwh
      }
      retroByModel[model] = byHour
    }
  }

  // Balancing lookup: tsKey → SEK/kWh for each category
  const imbShortByTs = {}
  const imbLongByTs  = {}
  if (balancing) {
    for (const p of balancing.short) imbShortByTs[tsKey(p.timestamp_utc)] = parseFloat(p.price_sek_kwh)
    for (const p of balancing.long)  imbLongByTs[tsKey(p.timestamp_utc)]  = parseFloat(p.price_sek_kwh)
  }

  // Generation lookup: "HH:00" → generation row
  const genByHour = {}
  if (generationTimeSeries) {
    for (const d of generationTimeSeries) {
      genByHour[toLocalHour(toUtc(d.timestamp_utc))] = d
    }
  }

  const chartData = prices.map((p) => {
    const localHour = toLocalHour(p.timestamp_utc)
    const hour = parseInt(localHour.split(':')[0], 10)
    const fc   = forecastByHour[hour]
    const key  = tsKey(p.timestamp_utc)
    const hourKey = localHour.split(':')[0] + ':00'
    const gen  = genByHour[hourKey]
    return {
      ...p,
      hour: localHour,
      price_sek_kwh: parseFloat(p.price_sek_kwh),
      price_eur_mwh: parseFloat(p.price_eur_mwh),
      forecast_low:  forecastByHour[hour]?.low  ?? null,
      forecast_band: forecastByHour[hour]?.band ?? null,
      forecast_avg:  forecastByHour[hour]?.avg  ?? null,
      lgbm_forecast: lgbmByHour[hour] ?? null,
      imb_short: imbShortByTs[key] ?? null,
      imb_long:  imbLongByTs[key]  ?? null,
      gen_hydro:   gen?.hydro   ?? null,
      gen_wind:    gen?.wind    ?? null,
      gen_nuclear: gen?.nuclear ?? null,
      gen_solar:   gen?.solar   ?? null,
      gen_other:   gen?.other   ?? null,
      retro_weekday: retroByModel['same_weekday_avg']?.[hour] ?? null,
      retro_lgbm:    retroByModel['lgbm']?.[hour] ?? null,
    }
  })

  const avg = chartData.reduce((s, d) => s + d.price_sek_kwh, 0) / chartData.length

  // Show only HH:00 labels (every full hour) to avoid overlap on 15-min data
  const tickFormatter = (value) => (value.endsWith(':00') ? value : '')

  const hasBalancing = balancing && (balancing.short.length > 0 || balancing.long.length > 0)
  const hasGen = generationTimeSeries?.length > 0
  const hasForecast = forecast || lgbmForecast
  const hasRetro = retrospective?.models && Object.keys(retrospective.models).length > 0

  return (
    <div className="w-full">
      {isEstimate && (
        <p className="text-xs text-yellow-400 mb-2 text-center">
          Showing estimated data — add ENTSOE_API_KEY to see real prices
        </p>
      )}

      {/* Legend row */}
      {(hasBalancing || hasGen || hasForecast || hasRetro) && (
        <div className="flex items-center justify-between mb-2">
          <div className="flex gap-4 text-xs text-gray-400 flex-wrap">
            {hasBalancing && (
              <>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t-2 border-blue-400" />
                  Day-ahead
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t-2 border-dashed border-orange-400" />
                  Imbalance Short
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t-2 border-dashed border-green-400" />
                  Imbalance Long
                </span>
              </>
            )}
            {hasForecast && (
              <>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-5 border-t-2 border-blue-400" />
                  Day-ahead
                </span>
                {forecast && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-5 border-t-2 border-dashed border-indigo-400" />
                    Weekday Avg
                  </span>
                )}
                {lgbmForecast && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-5 border-t-2 border-emerald-400" />
                    LGBM
                  </span>
                )}
              </>
            )}
            {hasRetro && (
              <>
                {retroByModel['same_weekday_avg'] && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-5 border-t-2 border-dashed border-violet-400" />
                    Pred: Weekday
                  </span>
                )}
                {retroByModel['lgbm'] && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-5 border-t-2 border-dashed border-rose-400" />
                    Pred: LGBM
                  </span>
                )}
              </>
            )}
          </div>
          {hasGen && (
            <button
              onClick={() => setShowGen((v) => !v)}
              className={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
                showGen
                  ? 'border-emerald-600 text-emerald-400 bg-emerald-900/20'
                  : 'border-gray-700 text-gray-500 hover:text-gray-400'
              }`}
            >
              {showGen ? '▪ Gen mix' : '◦ Gen mix'}
            </button>
          )}
        </div>
      )}

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
          <XAxis
            dataKey="hour"
            interval={0}
            tickFormatter={tickFormatter}
            tick={{ fill: '#9ca3af', fontSize: 11, dy: 4 }}
            angle={-45}
            textAnchor="end"
          />
          {/* Primary Y-axis: price (SEK/kWh) */}
          <YAxis
            yAxisId="price"
            tickFormatter={(v) => `${v.toFixed(2)}`}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            width={48}
          />
          {/* Hidden generation Y-axis — provides scale for background areas, no visual clutter */}
          {showGen && <YAxis yAxisId="gen" orientation="right" hide />}

          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine
            yAxisId="price"
            y={avg}
            stroke="#6b7280"
            strokeDasharray="4 4"
            label={{ value: 'avg', fill: '#6b7280', fontSize: 11 }}
          />

          {/* Generation background — rendered first so price line stays on top */}
          {showGen && GEN_SOURCES.map(({ key, color }) => (
            <Area
              key={key}
              yAxisId="gen"
              type="monotone"
              dataKey={key}
              stackId="gen"
              stroke="none"
              fill={color + '35'}
              dot={false}
              legendType="none"
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}

          {/* Weekday Avg forecast band: stacked areas — transparent base + shaded band */}
          {forecast && (
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
                fill="rgba(99,102,241,0.15)"
                stroke="rgba(99,102,241,0.4)"
                strokeWidth={1}
                strokeDasharray="4 4"
                legendType="none"
                connectNulls={false}
                isAnimationActive={false}
              />
            </>
          )}

          {/* Balancing overlay — rendered under DA line so DA stays readable */}
          {hasBalancing && (
            <>
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="imb_long"
                stroke="#4ade80"
                strokeWidth={1.5}
                strokeDasharray="3 3"
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
                strokeWidth={1.5}
                strokeDasharray="3 3"
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
            </>
          )}

          {/* LightGBM forecast line — emerald dashed */}
          {lgbmForecast && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="lgbm_forecast"
              stroke="#34d399"
              strokeWidth={1.5}
              strokeDasharray="6 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* Retrospective prediction lines — dashed, muted */}
          {hasRetro && retroByModel['same_weekday_avg'] && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="retro_weekday"
              stroke="#a78bfa"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}
          {hasRetro && retroByModel['lgbm'] && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="retro_lgbm"
              stroke="#fb7185"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}

          {/* Day-ahead line — rendered last so it stays on top */}
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="price_sek_kwh"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={<CustomDot />}
            activeDot={{ r: 4, fill: '#60a5fa' }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
