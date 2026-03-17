import { useEffect, useState } from 'react'

export function useRetrospective(date, area = 'SE3') {
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
    fetch(`/api/v1/prices/forecast/retrospective?date=${date}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [date, area])

  return { data, loading, error }
}
