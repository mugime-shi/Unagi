import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area, PricesResponse } from "../types/index";

interface UsePricesReturn {
  data: PricesResponse | null;
  loading: boolean;
  error: Error | null;
}

interface PricesState {
  key: string | null;
  data: PricesResponse | null;
  error: Error | null;
}

/**
 * Fetch today's or tomorrow's prices. Pass `null` to skip fetching.
 *
 * Results are tagged with the day+area they were fetched for and only returned
 * while that request is still current: switching to tomorrow shows the loading
 * state instead of the previous day's data (before ~13:00 tomorrow takes seconds:
 * the API tries a live ENTSO-E fetch before falling back), and a slow stale response can't
 * overwrite a newer one. Auto-refresh keeps the current data on screen.
 */
export function usePrices(
  day: "today" | "tomorrow" | null,
  area: Area = "SE3",
): UsePricesReturn {
  const key = day ? `${day}|${area}` : null;
  const [state, setState] = useState<PricesState>({
    key: null,
    data: null,
    error: null,
  });
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    apiFetch(`/api/v1/prices/${day}?area=${area}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: PricesResponse) => {
        if (!cancelled) setState({ key, data, error: null });
      })
      .catch((error: Error) => {
        if (cancelled) return;
        // A failed refresh keeps the data already shown for this key.
        setState((s) => ({
          key,
          data: s.key === key ? s.data : null,
          error,
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [key, day, area, refreshKey]);

  const current = key !== null && state.key === key;
  return {
    data: current ? state.data : null,
    loading: key !== null && !current,
    error: current ? state.error : null,
  };
}
