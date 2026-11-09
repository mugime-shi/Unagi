import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";

export interface GenHistoryDay {
  date: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  fossil: number;
  other: number;
  total_mw: number;
  renewable_pct: number | null;
}

export interface GenHistoryResponse {
  days: number;
  start: string;
  end: string;
  daily: GenHistoryDay[];
}

interface UseGenerationHistoryReturn {
  data: GenHistoryResponse | null;
  loading: boolean;
  error: Error | null;
}

interface GenHistoryState {
  key: number | null;
  data: GenHistoryResponse | null;
  error: Error | null;
}

/**
 * Fetch daily generation history. Results are tagged with the range they were
 * fetched for, so switching range never shows another range's data and a slow
 * stale response can't overwrite a newer one. Auto-refresh keeps current data.
 */
export function useGenerationHistory(
  days: number = 7,
): UseGenerationHistoryReturn {
  const [state, setState] = useState<GenHistoryState>({
    key: null,
    data: null,
    error: null,
  });
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    if (days < 1) return;
    let cancelled = false;
    apiFetch(`/api/v1/generation/history?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: GenHistoryResponse) => {
        if (!cancelled) setState({ key: days, data, error: null });
      })
      .catch((error: Error) => {
        if (cancelled) return;
        // A failed refresh keeps the data already shown for this range.
        setState((s) => ({
          key: days,
          data: s.key === days ? s.data : null,
          error,
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [days, refreshKey]);

  const current = days >= 1 && state.key === days;
  return {
    data: current ? state.data : null,
    loading: days >= 1 && !current,
    error: current ? state.error : null,
  };
}
