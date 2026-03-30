import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, RetrospectiveResponse } from "../types/index";

interface UseRetrospectiveReturn {
  data: RetrospectiveResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useRetrospective(
  date: string | null,
  area: Area = "SE3",
): UseRetrospectiveReturn {
  const [data, setData] = useState<RetrospectiveResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast/retrospective?date=${date}&area=${area}`)
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
