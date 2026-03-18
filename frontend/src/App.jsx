import { useState } from 'react'
import { CheapHoursWidget } from './components/CheapHoursWidget'
import { ConsumptionSimulator } from './components/ConsumptionSimulator'
import { ForecastAccuracy } from './components/ForecastAccuracy'
import { GenerationChart } from './components/GenerationChart'
import { NotificationBell } from './components/NotificationBell'
import { PriceChart } from './components/PriceChart'
import { PriceHistory } from './components/PriceHistory'
import { PriceIndicator } from './components/PriceIndicator'
import { SolarSimulator } from './components/SolarSimulator'
import { useBalancing } from './hooks/useBalancing'
import { useDatePrices } from './hooks/useDatePrices'
import { useForecast } from './hooks/useForecast'
import { useGeneration } from './hooks/useGeneration'
import { useRetrospective } from './hooks/useRetrospective'
import { usePrices } from './hooks/usePrices'

const AREAS = [
  { id: 'SE1', label: 'SE1', city: 'Luleå'      },
  { id: 'SE2', label: 'SE2', city: 'Sundsvall'   },
  { id: 'SE3', label: 'SE3', city: 'Göteborg'    },
  { id: 'SE4', label: 'SE4', city: 'Malmö'       },
]

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

function tomorrowISO() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().split('T')[0]
}

function yesterdayISO() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d.toISOString().split('T')[0]
}

export default function App() {
  const [layer, setLayer] = useState('prices')
  const [day, setDay]     = useState('today')
  const [area, setArea]   = useState('SE3')
  const [reviewDate, setReviewDate] = useState(yesterdayISO)
  const { data, loading, error } = usePrices(day !== 'review' ? day : 'today', area)
  const { data: forecast } = useForecast(day === 'tomorrow' ? tomorrowISO() : null, area)
  // Balancing prices: try today, fall back to yesterday if not yet published
  const { data: balancing, dataDate: balancingDate } = useBalancing(
    day === 'today' ? todayISO() : null, area,
  )
  const { data: generation } = useGeneration(area)
  // Retrospective predictions (pre-recorded in forecast_accuracy table).
  // Used for: Today (yesterday's predictions), Tomorrow (morning cron predictions), Review (past date).
  const retroDate = day === 'today' ? todayISO() : day === 'tomorrow' ? tomorrowISO() : day === 'review' ? reviewDate : null
  const { data: retrospective } = useRetrospective(retroDate, area)
  // Extract LGBM forecast from pre-recorded predictions for Tomorrow tab
  const lgbmForecast = day === 'tomorrow' && retrospective?.models?.lgbm
    ? { slots: retrospective.models.lgbm.map(p => ({ hour: p.hour, avg_sek_kwh: p.predicted_sek_kwh })) }
    : null
  // Review mode: fetch prices for an arbitrary past date
  const { data: reviewData, loading: reviewLoading, error: reviewError } = useDatePrices(
    day === 'review' ? reviewDate : null, area,
  )

  const areaCity = AREAS.find((a) => a.id === area)?.city ?? area

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 sm:px-6 py-4 flex items-center gap-3 flex-wrap">
        <span className="text-xl font-bold tracking-tight">Namazu</span>
        <span className="text-gray-500 text-sm">{area} · {areaCity}</span>

        {/* Area selector */}
        <div className="flex gap-1">
          {AREAS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setArea(id)}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                area === id
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-500 hover:text-gray-300 border border-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <NotificationBell area={area} />

        {/* Layer selector */}
        <nav className="ml-auto flex gap-1">
          {[
            { id: 'prices',  label: 'Prices'  },
            { id: 'history', label: 'History' },
            { id: 'simulators', label: 'Simulators' },
          ].map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setLayer(id)}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                layer === id
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-4">

        {/* ── Layer 1: Prices ── */}
        {layer === 'prices' && (
          <>
            {/* Day selector */}
            <div className="flex gap-2 items-center">
              {['today', 'tomorrow', 'review'].map((d) => (
                <button
                  key={d}
                  onClick={() => setDay(d)}
                  className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                    day === d
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {d === 'today' ? 'Today' : d === 'tomorrow' ? 'Tomorrow' : 'Review'}
                </button>
              ))}
              {day === 'review' && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      const d = new Date(reviewDate)
                      d.setDate(d.getDate() - 1)
                      setReviewDate(d.toISOString().split('T')[0])
                    }}
                    className="px-2 py-1 rounded-lg bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm"
                  >
                    &larr;
                  </button>
                  <input
                    type="date"
                    value={reviewDate}
                    max={todayISO()}
                    onChange={(e) => setReviewDate(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm text-gray-300 focus:outline-none focus:border-blue-500"
                  />
                  <button
                    onClick={() => {
                      const d = new Date(reviewDate)
                      d.setDate(d.getDate() + 1)
                      const next = d.toISOString().split('T')[0]
                      if (next <= todayISO()) setReviewDate(next)
                    }}
                    disabled={reviewDate >= todayISO()}
                    className="px-2 py-1 rounded-lg bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm disabled:opacity-30 disabled:pointer-events-none"
                  >
                    &rarr;
                  </button>
                </div>
              )}
            </div>

            {/* ── Review mode ── */}
            {day === 'review' && (
              <>
                {reviewLoading && (
                  <div className="animate-pulse bg-gray-900 rounded-2xl p-4">
                    <div className="h-[300px] bg-gray-800 rounded-xl" />
                  </div>
                )}
                {reviewError && (
                  <p className="text-red-400 text-sm">Failed to load prices: {reviewError.message}</p>
                )}
                {reviewData && (
                  <>
                    <div className="bg-gray-900 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <div>
                          <h2 className="text-sm font-medium text-gray-300">
                            Spot price — {reviewData.date} · {reviewData.count} slots
                          </h2>
                          {retrospective?.models && Object.keys(retrospective.models).length > 0 && (
                            <p className="text-xs text-gray-500 mt-0.5">
                              + Forecast predictions overlay
                            </p>
                          )}
                        </div>
                        <span className="text-xs text-gray-500">SEK/kWh</span>
                      </div>
                      <PriceChart
                        prices={reviewData.prices}
                        isEstimate={false}
                        retrospective={retrospective}
                      />
                    </div>

                    {/* Summary cards */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-center">
                      {[
                        { label: 'Min', value: reviewData.summary.min_sek_kwh },
                        { label: 'Avg', value: reviewData.summary.avg_sek_kwh },
                        { label: 'Max', value: reviewData.summary.max_sek_kwh },
                      ].map(({ label, value }) => (
                        <div key={label} className="bg-gray-900 rounded-xl py-3">
                          <p className="text-xs text-gray-500 mb-1">{label}</p>
                          <p className="text-lg font-semibold">
                            {value != null ? value.toFixed(2) : '—'}
                          </p>
                          <p className="text-xs text-gray-500">SEK/kWh</p>
                        </div>
                      ))}
                    </div>

                    {/* Per-model accuracy for this specific date */}
                    {retrospective?.models && Object.keys(retrospective.models).length > 0 && (
                      <div className="bg-gray-900 rounded-xl p-4">
                        <h3 className="text-xs text-gray-500 mb-3">
                          Prediction accuracy — {reviewData.date}
                        </h3>
                        <div className="space-y-2">
                          {Object.entries(retrospective.models)
                            .map(([model, entries]) => {
                              const pairs = entries.filter((e) => e.predicted_sek_kwh != null && e.actual_sek_kwh != null)
                              const mae = pairs.length > 0
                                ? pairs.reduce((s, e) => s + Math.abs(e.predicted_sek_kwh - e.actual_sek_kwh), 0) / pairs.length
                                : Infinity
                              return { model, pairs, mae }
                            })
                            .filter(({ pairs }) => pairs.length > 0)
                            .sort((a, b) => a.mae - b.mae)
                            .map(({ model, pairs, mae }) => (
                              <div key={model} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800">
                                <span className="text-sm font-medium text-gray-200">
                                  {model === 'same_weekday_avg' ? 'Weekday Avg' : model.toUpperCase()}
                                </span>
                                <span className="text-sm text-gray-300">
                                  MAE {mae.toFixed(2)} SEK/kWh · {pairs.length} hrs
                                </span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
                {!reviewLoading && !reviewError && !reviewData && (
                  <p className="text-gray-500 text-sm text-center py-8">
                    Select a date to review past prices and forecast accuracy
                  </p>
                )}
              </>
            )}

            {/* ── Today / Tomorrow mode ── */}
            {day !== 'review' && (
              <>
                {loading && (
                  <div className="animate-pulse space-y-4">
                    {/* Chart placeholder */}
                    <div className="bg-gray-900 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <div className="h-4 bg-gray-700 rounded w-40" />
                        <div className="h-3 bg-gray-700 rounded w-12" />
                      </div>
                      <div className="h-[300px] bg-gray-800 rounded-xl" />
                    </div>
                    {/* Summary cards placeholder */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      {[0, 1, 2, 3].map((i) => (
                        <div key={i} className="bg-gray-900 rounded-xl py-3 px-4 space-y-2">
                          <div className="h-3 bg-gray-700 rounded w-16 mx-auto" />
                          <div className="h-6 bg-gray-700 rounded w-12 mx-auto" />
                          <div className="h-3 bg-gray-700 rounded w-10 mx-auto" />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {error && (
                  <p className="text-red-400 text-sm">Failed to load prices: {error.message}</p>
                )}

                {data && (
                  <>
                    {day === 'today' && <PriceIndicator prices={data.prices} />}


                    {/* Tomorrow not published yet */}
                    {day === 'tomorrow' && data.is_estimate && data.published === false && (
                      <p className="text-yellow-400 text-xs text-center bg-yellow-400/10 rounded-lg py-2 px-3">
                        Tomorrow&apos;s prices are typically published after 13:00 CET
                      </p>
                    )}

                    {/* Price chart */}
                    <div className="bg-gray-900 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <div>
                          <h2 className="text-sm font-medium text-gray-300">
                            Spot price — {data.date} · {data.count} slots
                          </h2>
                          {day === 'today' && balancing && (
                            <p className="text-xs text-gray-500 mt-0.5">
                              + Imbalance prices (eSett EXP14) · {balancing.count} pts
                              {balancingDate && balancingDate !== data.date && (
                                <span className="text-gray-600 ml-1">· {balancingDate}</span>
                              )}
                            </p>
                          )}
                        </div>
                        <span className="text-xs text-gray-500">SEK/kWh</span>
                      </div>
                      <PriceChart
                        prices={data.prices}
                        isEstimate={data.is_estimate}
                        forecast={day === 'tomorrow' ? forecast : null}
                        lgbmForecast={day === 'tomorrow' ? lgbmForecast : null}
                        retrospective={day === 'today' ? retrospective : null}
                        balancing={day === 'today' ? balancing : null}
                        predToggle={day === 'today'}
                      />
                    </div>

                    {/* Generation mix stacked area chart — today only, directly below price for X-axis alignment */}
                    {day === 'today' && generation?.time_series?.length > 0 && (
                      <GenerationChart generation={generation} prices={data.prices} />
                    )}

                    {/* Min / Avg (date) / Avg (month) / Max */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                      {[
                        { label: 'Min', value: data.summary.min_sek_kwh },
                        {
                          label: `Avg (${new Date(data.date).toISOString().split('T')[0]})`,
                          value: data.summary.avg_sek_kwh,
                        },
                        { label: 'Avg (month)', value: data.summary.month_avg_sek_kwh },
                        { label: 'Max', value: data.summary.max_sek_kwh },
                      ].map(({ label, value }) => (
                        <div key={label} className="bg-gray-900 rounded-xl py-3">
                          <p className="text-xs text-gray-500 mb-1">{label}</p>
                          <p className="text-lg font-semibold">
                            {value != null ? value.toFixed(2) : '—'}
                          </p>
                          <p className="text-xs text-gray-500">SEK/kWh</p>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {/* Forecast accuracy card — today & tomorrow */}
                {(day === 'today' || day === 'tomorrow') && <ForecastAccuracy area={area} />}

                {/* Appliance scheduler — today only */}
                {day === 'today' && <CheapHoursWidget date={todayISO()} area={area} />}

              </>
            )}

            {/* CTA → Simulators */}
            <button
              onClick={() => setLayer('simulators')}
              className="w-full bg-gray-900 rounded-xl p-4 text-left hover:bg-gray-800 transition-colors group"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-300">Cost & Solar Simulator</p>
                  <p className="text-xs text-gray-500">Compare contracts, simulate solar PV revenue</p>
                </div>
                <span className="text-gray-600 group-hover:text-gray-400 transition-colors text-lg">&rarr;</span>
              </div>
            </button>
          </>
        )}

        {/* ── History ── */}
        {layer === 'history' && <PriceHistory area={area} />}

        {/* ── Simulators ── */}
        {layer === 'simulators' && (
          <div className="space-y-6">
            <ConsumptionSimulator />
            <SolarSimulator />
          </div>
        )}

      </main>
    </div>
  )
}
