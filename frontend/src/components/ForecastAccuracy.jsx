import { useForecastAccuracy } from '../hooks/useForecastAccuracy'

/**
 * Mini card showing forecast accuracy (MAE) per model.
 * Shown in the Tomorrow tab so users can see prediction quality.
 */
export function ForecastAccuracy({ area }) {
  const { data, loading } = useForecastAccuracy(area, 30)

  if (loading || !data) return null

  const models = data.models
  const modelNames = Object.keys(models)
  if (modelNames.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl p-3 text-center">
        <p className="text-xs text-gray-500">
          No forecast accuracy data yet — predictions need to be recorded first
        </p>
      </div>
    )
  }

  // Sort: best MAE first
  const sorted = modelNames
    .map((name) => ({ name, ...models[name] }))
    .sort((a, b) => a.mae_sek_kwh - b.mae_sek_kwh)

  const best = sorted[0]

  return (
    <div className="bg-gray-900 rounded-xl p-4">
      <h3 className="text-xs text-gray-500 mb-3">
        Forecast accuracy (last {data.days} days)
      </h3>
      <div className="space-y-2">
        {sorted.map((m) => {
          const isBest = sorted.length > 1 && m.name === best.name
          const maeOre = (m.mae_sek_kwh * 100).toFixed(1)
          const improvement =
            sorted.length > 1 && m.name !== best.name
              ? ((1 - best.mae_sek_kwh / m.mae_sek_kwh) * 100).toFixed(0)
              : null

          return (
            <div
              key={m.name}
              className={`flex items-center justify-between px-3 py-2 rounded-lg ${
                isBest ? 'bg-emerald-900/20 border border-emerald-800' : 'bg-gray-800'
              }`}
            >
              <div>
                <span className="text-sm font-medium text-gray-200">
                  {m.name === 'same_weekday_avg' ? 'Weekday Avg' : m.name.toUpperCase()}
                </span>
                <span className="text-xs text-gray-500 ml-2">
                  {m.n_days}d · {m.n_samples} pts
                </span>
              </div>
              <div className="text-right">
                <span className={`text-sm font-semibold ${isBest ? 'text-emerald-400' : 'text-gray-300'}`}>
                  MAE {maeOre} ore/kWh
                </span>
                {improvement && (
                  <span className="text-xs text-gray-500 ml-2">
                    (best is {improvement}% better)
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
