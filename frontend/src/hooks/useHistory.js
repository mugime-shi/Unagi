import { useEffect, useState } from 'react'

export function useHistory(days = 90) {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`/api/v1/prices/history?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [days])

  return { data, loading, error }
}
