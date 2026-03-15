import { useState } from 'react'
import { CheapHoursWidget } from './components/CheapHoursWidget'
import { ConsumptionSimulator } from './components/ConsumptionSimulator'
import { PriceChart } from './components/PriceChart'
import { PriceHistory } from './components/PriceHistory'
import { PriceIndicator } from './components/PriceIndicator'
import { SolarSimulator } from './components/SolarSimulator'
import { usePrices } from './hooks/usePrices'

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

export default function App() {
  const [layer, setLayer] = useState('prices')
  const [day, setDay] = useState('today')
  const { data, loading, error } = usePrices(day)

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 sm:px-6 py-4 flex items-center gap-3">
        <span className="text-xl font-bold tracking-tight">Namazu</span>
        <span className="text-gray-500 text-sm">SE3 · Göteborg</span>

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

            {loading && <p className="text-gray-500 text-sm">Loading prices…</p>}
            {error && (
              <p className="text-red-400 text-sm">Failed to load prices: {error.message}</p>
            )}

            {data && (
              <>
                {day === 'today' && <PriceIndicator prices={data.prices} />}

                {/* Tomorrow not published yet */}
                {day === 'tomorrow' && data.is_mock && data.published === false && (
                  <p className="text-yellow-400 text-xs text-center bg-yellow-400/10 rounded-lg py-2 px-3">
                    Tomorrow&apos;s prices are typically published after 13:00 CET
                  </p>
                )}

                {/* Price chart */}
                <div className="bg-gray-900 rounded-2xl p-4">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-medium text-gray-300">
                      Spot price — {data.date} · {data.count} slots
                    </h2>
                    <span className="text-xs text-gray-500">SEK/kWh</span>
                  </div>
                  <PriceChart prices={data.prices} isMock={data.is_mock} />
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
            {day === 'today' && <CheapHoursWidget date={todayISO()} />}

            {/* Consumption simulator */}
            <ConsumptionSimulator />
          </>
        )}

        {/* ── History ── */}
        {layer === 'history' && <PriceHistory />}

        {/* ── Layer 2: Solar ── */}
        {layer === 'solar' && <SolarSimulator />}

      </main>
    </div>
  )
}
