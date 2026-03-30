import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, GenerationResponse } from "../types/index";

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

interface UseGenerationReturn {
  data: GenerationResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGeneration(area: Area = "SE3"): UseGenerationReturn {
  const [data, setData] = useState<GenerationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch(`${API_BASE}/generation/today?area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((json: GenerationResponse) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [area]);

  return { data, loading, error };
}
