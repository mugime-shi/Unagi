import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, PricesResponse } from "../types/index";

interface UsePricesReturn {
  data: PricesResponse | null;
  loading: boolean;
  error: Error | null;
}

export function usePrices(
  day: string = "today",
  area: Area = "SE3",
): UsePricesReturn {
  const [data, setData] = useState<PricesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

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
