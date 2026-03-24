import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

export function useWeeklyForecast(area = "SE3") {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast/weekly?area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area]);

  return { data, loading, error };
}
