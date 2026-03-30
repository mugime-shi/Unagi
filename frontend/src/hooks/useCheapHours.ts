import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, CheapestWindowResponse } from "../types/index";

interface UseCheapHoursReturn {
  data: CheapestWindowResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useCheapHours(
  date: string | null,
  duration: number | null,
  area: Area = "SE3",
): UseCheapHoursReturn {
  const [data, setData] = useState<CheapestWindowResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!date || !duration) return;
    setLoading(true);
    setData(null);
    apiFetch(
      `/api/v1/prices/cheapest-hours?date=${date}&duration=${duration}&area=${area}`,
    )
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: CheapestWindowResponse) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e);
        setLoading(false);
      });
  }, [date, duration, area]);

  return { data, loading, error };
}
