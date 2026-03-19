import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function useGeneration(area = "SE3") {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch(`${API_BASE}/generation/today?area=${area}`)
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
  }, [area]);

  return { data, loading, error };
}
