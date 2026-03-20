import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

export function useCoverage(area = "SE3", days = 30) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(
      `/api/v1/prices/forecast/accuracy/coverage?area=${area}&days=${days}`,
    )
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area, days]);

  return { data, loading, error };
}
