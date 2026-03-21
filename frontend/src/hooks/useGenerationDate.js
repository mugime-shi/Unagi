import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function useGenerationDate(date, area = "SE3") {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch(`${API_BASE}/generation/date?date=${date}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [date, area]);

  return { data, loading, error };
}
