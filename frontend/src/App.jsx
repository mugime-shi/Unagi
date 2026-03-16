import { useState } from 'react'
import { CheapHoursWidget } from './components/CheapHoursWidget'
import { ConsumptionSimulator } from './components/ConsumptionSimulator'
import { NotificationBell } from './components/NotificationBell'
import { PriceChart } from './components/PriceChart'
import { PriceHistory } from './components/PriceHistory'
import { PriceIndicator } from './components/PriceIndicator'
import { SolarSimulator } from './components/SolarSimulator'
import { useBalancing } from './hooks/useBalancing'
import { useForecast } from './hooks/useForecast'
import { useGeneration } from './hooks/useGeneration'
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

export default function App() {
  const [layer, setLayer] = useState('prices')
  const [day, setDay]     = useState('today')
  const [area, setArea]   = useState('SE3')
  const { data, loading, error } = usePrices(day, area)
  const { data: forecast } = useForecast(day === 'tomorrow' ? tomorrowISO() : null, area)
  // Balancing prices: try today, fall back to yesterday if not yet published
  const { data: balancing, dataDate: balancingDate } = useBalancing(
    day === 'today' ? todayISO() : null, area,
  )
  const { data: generation } = useGeneration(area)

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
            { id: 'solar',   label: 'Solar'   },
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
            <div className="flex gap-2">
              {['today', 'tomorrow'].map((d) => (
                <button
                  key={d}
                  onClick={() => setDay(d)}
                  className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                    day === d
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {d === 'today' ? 'Today' : 'Tomorrow'}
                </button>
              ))}
            </div>

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

                {/* Generation mix badge — today only */}
                {day === 'today' && generation && generation.renewable_pct != null && (
                  <div className="space-y-1.5">
                    <p className="text-[11px] text-gray-500">
                      {(() => {
                        const d = new Date(generation.latest_slot)
                        const time = d.toLocaleTimeString('sv-SE', {
                          hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Stockholm',
                        })
                        const tz = d.toLocaleTimeString('en-SE', {
                          timeZone: 'Europe/Stockholm', timeZoneName: 'short',
                        }).split(' ').at(-1)
                        return `Generation mix · as of ${time} ${tz}`
                      })()}
                      <span className="ml-1 text-gray-600">(~15 min lag)</span>
                    </p>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="bg-green-900/40 border border-green-700 text-green-300 rounded-full px-3 py-1">
                      Renewable {generation.renewable_pct}%
                    </span>
                    <span className="bg-gray-800 border border-gray-700 text-gray-400 rounded-full px-3 py-1">
                      Carbon-free {generation.carbon_free_pct}%
                    </span>
                    {generation.breakdown?.hydro != null && (
                      <span className="bg-blue-900/30 border border-blue-800 text-blue-400 rounded-full px-3 py-1">
                        Hydro {Math.round(generation.breakdown.hydro)} MW
                      </span>
                    )}
                    {generation.breakdown?.wind != null && (
                      <span className="bg-cyan-900/30 border border-cyan-800 text-cyan-400 rounded-full px-3 py-1">
                        Wind {Math.round(generation.breakdown.wind)} MW
                      </span>
                    )}
                    {generation.breakdown?.nuclear != null && (
                      <span className="bg-yellow-900/30 border border-yellow-800 text-yellow-500 rounded-full px-3 py-1">
                        Nuclear {Math.round(generation.breakdown.nuclear)} MW
                      </span>
                    )}
                  </div>
                  </div>
                )}

                {/* Tomorrow not published yet */}
                {day === 'tomorrow' && data.is_mock && data.published === false && (
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
                    isMock={data.is_mock}
                    forecast={day === 'tomorrow' ? forecast : null}
                    balancing={day === 'today' ? balancing : null}
                  />
                </div>

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

            {/* Appliance scheduler — today only */}
            {day === 'today' && <CheapHoursWidget date={todayISO()} area={area} />}

            {/* Consumption simulator */}
            <ConsumptionSimulator />
          </>
        )}

        {/* ── History ── */}
        {layer === 'history' && <PriceHistory area={area} />}

        {/* ── Layer 2: Solar ── */}
        {layer === 'solar' && <SolarSimulator />}

      </main>
    </div>
  )
}
