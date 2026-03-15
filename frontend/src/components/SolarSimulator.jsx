import { useState } from 'react'
import { useSolar } from '../hooks/useSolar'

function currentMonthISO() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function Chip({ label, value, unit }) {
  return (
    <div className="bg-gray-800 rounded-xl p-3 text-center">
      <p className="text-xs text-gray-400 mb-0.5 leading-tight">{label}</p>
      <p className="text-base font-semibold">{value}</p>
      <p className="text-xs text-gray-500">{unit}</p>
    </div>
  )
}

function FieldInput({ label, value, onChange, min, max, step, unit, width = 'w-32', pr = 'pr-12' }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-gray-400">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm ${width} ${pr}`}
          min={min} max={max} step={step}
        />
        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500">{unit}</span>
      </div>
    </div>
  )
}

export function SolarSimulator() {
  const [panelKwp, setPanelKwp]     = useState('6.0')
  const [batteryKwh, setBatteryKwh] = useState('0')
  const [annualKwh, setAnnualKwh]   = useState('15000')
  const [month, setMonth]           = useState(currentMonthISO)
  const { result, loading, error, run } = useSolar()

  const handleSubmit = (e) => {
    e.preventDefault()
    run({
      panel_kwp:              parseFloat(panelKwp),
      battery_kwh:            parseFloat(batteryKwh),
      annual_consumption_kwh: parseFloat(annualKwh),
      month,
    })
  }

  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-1">Solar PV simulator</h2>
      <p className="text-xs text-gray-600 mb-3">
        Estimate monthly generation, revenue &amp; self-consumption savings under current rules,
        and compare against the old 2025 tax credit.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-wrap gap-3 mb-4 items-end">
        <FieldInput
          label="Panel capacity" value={panelKwp} onChange={setPanelKwp}
          min="1" max="100" step="0.5" unit="kWp"
        />
        <FieldInput
          label="Battery" value={batteryKwh} onChange={setBatteryKwh}
          min="0" max="200" step="1" unit="kWh"
        />
        <FieldInput
          label="Annual usage" value={annualKwh} onChange={setAnnualKwh}
          min="0" max="100000" step="1000" unit="kWh/y" width="w-36" pr="pr-14"
        />

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-400">Month</label>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm w-36 text-gray-100"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-sm transition-colors"
        >
          {loading ? 'Simulating…' : 'Simulate'}
        </button>
      </form>

      {error && (
        <p className="text-red-400 text-xs mb-3">
          {error.message.includes('503') || error.message.toLowerCase().includes('no spot price')
            ? `No spot price data for ${month}. Run backfill for that month first.`
            : error.message}
        </p>
      )}

      {result && (
        <div className="space-y-4">

          {/* Header: data source + month */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              result.data_source === 'smhi'
                ? 'bg-blue-500/20 text-blue-400'
                : 'bg-gray-700 text-gray-400'
            }`}>
              {result.data_source === 'smhi' ? 'SMHI real data' : 'Reference table'}
            </span>
            <span className="text-xs text-gray-600">
              {result.month} · {result.panel_kwp} kWp
              {result.battery_kwh > 0 && ` · ${result.battery_kwh} kWh battery`}
              {' · '}avg spot {result.avg_spot_sek_kwh.toFixed(2)} SEK/kWh
            </span>
          </div>

          {/* Energy balance */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Energy balance</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Chip label="Generated"        value={result.solar_generation_kwh.toFixed(0)}  unit="kWh" />
              <Chip label="Self-consumed"    value={result.self_consumed_kwh.toFixed(0)}      unit="kWh" />
              <Chip label="Sold to grid"     value={result.sold_to_grid_kwh.toFixed(0)}       unit="kWh" />
              <Chip label="Bought from grid" value={result.bought_from_grid_kwh.toFixed(0)}   unit="kWh" />
            </div>
          </div>

          {/* Revenue & savings */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Revenue &amp; savings</p>
            <div className={`grid gap-2 ${result.battery_kwh > 0 ? 'grid-cols-3' : 'grid-cols-2'}`}>
              <Chip
                label="Revenue (sold)"
                value={result.revenue_sek.toFixed(0)}
                unit="SEK/mo"
              />
              <Chip
                label="Savings (self-use)"
                value={result.savings_from_self_consumption_sek.toFixed(0)}
                unit="SEK/mo"
              />
              {result.battery_kwh > 0 && (
                <Chip
                  label="Battery effect"
                  value={(result.battery_effect_sek >= 0 ? '+' : '') + result.battery_effect_sek.toFixed(0)}
                  unit="SEK/mo"
                />
              )}
            </div>
          </div>

          {/* Battery comparison — only when battery > 0 */}
          {result.battery_kwh > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">
                Battery impact — {result.battery_kwh} kWh battery vs no battery
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-blue-900/25 border border-blue-800/40 rounded-xl p-3 text-center">
                  <p className="text-xs text-blue-400/70 mb-1">with battery</p>
                  <p className="text-2xl font-bold text-blue-400">
                    {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                  <p className="text-xs text-gray-600">
                    sold {result.sold_to_grid_kwh.toFixed(0)} kWh
                    · bought {result.bought_from_grid_kwh.toFixed(0)} kWh
                  </p>
                </div>
                <div className="bg-gray-800/40 border border-gray-700/40 rounded-xl p-3 text-center">
                  <p className="text-xs text-gray-400/70 mb-1">without battery</p>
                  <p className="text-2xl font-bold text-gray-300">
                    {result.baseline.total_benefit_sek.toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                  <p className="text-xs text-gray-600">
                    sold {result.baseline.sold_to_grid_kwh.toFixed(0)} kWh
                    · bought {result.baseline.bought_from_grid_kwh.toFixed(0)} kWh
                  </p>
                </div>
              </div>
              <p className="text-xs text-center mt-2 font-medium" style={{
                color: result.battery_effect_sek >= 0 ? '#4ade80' : '#f87171'
              }}>
                Battery adds {result.battery_effect_sek >= 0 ? '+' : ''}{result.battery_effect_sek.toFixed(0)} SEK/month
              </p>
            </div>
          )}

          {/* Total benefit — context-aware display */}
          <div>
            {result.tax_credit.applies ? (
              /* ── 2025 and earlier: show with-credit vs without-credit comparison ── */
              <>
                <p className="text-xs text-gray-500 mb-2">
                  Total benefit — skattereduktion impact ({result.month})
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-green-900/25 border border-green-800/40 rounded-xl p-3 text-center">
                    <p className="text-xs text-green-400/70 mb-1">with tax credit</p>
                    <p className="text-2xl font-bold text-green-400">
                      {result.total_benefit_with_tax_credit_sek.toFixed(0)}
                    </p>
                    <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                    <p className="text-xs text-green-400/60">
                      ~{(result.total_benefit_with_tax_credit_sek * 12).toFixed(0)} SEK / year
                    </p>
                    <p className="text-xs text-green-400/50 mt-1">
                      incl. {result.tax_credit.monthly_credit_sek.toFixed(0)} SEK credit
                    </p>
                  </div>
                  <div className="bg-gray-800/40 border border-gray-700/40 rounded-xl p-3 text-center">
                    <p className="text-xs text-gray-400/70 mb-1">without tax credit</p>
                    <p className="text-2xl font-bold text-gray-300">
                      {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                    </p>
                    <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                    <p className="text-xs text-gray-500">
                      ~{(result.total_benefit_without_tax_credit_sek * 12).toFixed(0)} SEK / year
                    </p>
                  </div>
                </div>
                <p className="text-xs text-gray-600 text-center mt-2">
                  Skattereduktion: {result.tax_credit.rate_sek_kwh} SEK/kWh
                  {' · '}{result.tax_credit.eligible_kwh.toFixed(0)} kWh eligible
                  {' · '}annual cap {result.tax_credit.annual_cap_sek.toLocaleString()} SEK
                </p>
              </>
            ) : (
              /* ── 2026 onwards: single benefit card, credit abolished ── */
              <>
                <p className="text-xs text-gray-500 mb-2">Total benefit ({result.month})</p>
                <div className="bg-gray-800/40 border border-gray-700/40 rounded-xl p-4 text-center">
                  <p className="text-3xl font-bold text-gray-100">
                    {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                  </p>
                  <p className="text-sm text-gray-500 mb-2">SEK / month</p>
                  <p className="text-base text-gray-400">
                    ~{(result.total_benefit_without_tax_credit_sek * 12).toFixed(0)} SEK / year
                  </p>
                </div>
                <p className="text-xs text-gray-600 text-center mt-2">
                  Skattereduktion abolished from 2026-01-01
                </p>
              </>
            )}
            <p className="text-xs text-gray-700 text-center mt-1">
              Annual estimate = this month × 12 (seasonal variation not included)
            </p>
          </div>

        </div>
      )}
    </div>
  )
}
