import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, GridOperatorsResponse } from "../types/index";

interface UseGridOperatorsReturn {
  data: GridOperatorsResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGridOperators(area: Area = "SE3"): UseGridOperatorsReturn {
  const [data, setData] = useState<GridOperatorsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/grid-operators?area=${area}`)
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
