import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

export function usePrices(day = "today", area = "SE3") {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!day) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/${day}?area=${area}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [day, area]);

  return { data, loading, error };
}
