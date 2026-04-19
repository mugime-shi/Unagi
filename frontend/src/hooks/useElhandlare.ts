import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area, ElhandlareResponse } from "../types/index";

interface UseElhandlareReturn {
  data: ElhandlareResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useElhandlare(area: Area = "SE3"): UseElhandlareReturn {
  const [data, setData] = useState<ElhandlareResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/elhandlare?area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area, refreshKey]);

  return { data, loading, error };
}
