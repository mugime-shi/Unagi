import { useEffect, useState } from 'react'

/**
 * Fetch spot prices for a specific date via /api/v1/prices/range.
 * Returns the same shape as usePrices (data with .prices, .summary, .date, etc.)
 * so PriceChart can consume it directly.
 */
export function useDatePrices(date, area = 'SE3') {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!date) {
      setData(null)
      return
    }
    setLoading(true)
    setError(null)
    fetch(`/api/v1/prices/range?start=${date}&end=${date}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((res) => {
        // /range returns { dates: [{ date, count, summary, prices }] }
        const dayData = res.dates?.[0]
        if (!dayData || dayData.count === 0) {
          setData(null)
          setError(new Error('No price data for this date'))
          return
        }
        // Reshape to match the /today response format
        setData({
          area: res.area,
          date: dayData.date,
          currency: res.currency,
          is_estimate: false,
          count: dayData.count,
          summary: {
            ...dayData.summary,
            month_avg_sek_kwh: null,
          },
          prices: dayData.prices,
        })
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [date, area])

  return { data, loading, error }
}
