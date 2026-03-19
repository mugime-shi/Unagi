import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

export function useLgbmForecast(date, area = "SE3") {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast?date=${date}&area=${area}&model=lgbm`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [date, area]);

  return { data, loading, error };
}
