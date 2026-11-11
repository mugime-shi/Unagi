import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, BalancingResponse } from "../types/index";

function prevDay(iso: string): string {
  const d = new Date(iso);
  d.setDate(d.getDate() - 1);
  return d.toISOString().split("T")[0];
}

interface UseBalancingReturn {
  data: BalancingResponse | null;
  dataDate: string | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Fetch balancing (imbalance) prices for a given date.
 * Falls back to the previous day if today's data is not yet published
 * (ENTSO-E A85 data lags ~1-2 hours per interval; yesterday is always complete).
 *
 * Returns { data, dataDate, loading, error }
 * dataDate may differ from dateISO if a fallback was used.
 */
export function useBalancing(
  dateISO: string | null,
  area: Area = "SE3",
): UseBalancingReturn {
  const { key: refreshKey } = useRefresh();
  const { data, loading, error } = useAsyncResource<{
    data: BalancingResponse;
    dataDate: string;
  }>(dateISO ? `${dateISO}|${area}|${refreshKey}` : null, async () => {
    const tryFetch = (d: string) =>
      fetchJson<BalancingResponse>(
        `/api/v1/prices/balancing?date=${d}&area=${area}`,
      );
    const fallback = async () => {
      const yd = prevDay(dateISO!);
      return { data: await tryFetch(yd), dataDate: yd };
    };

    let today: BalancingResponse;
    try {
      today = await tryFetch(dateISO!);
    } catch {
      // Network / server error -- try yesterday
      return fallback();
    }
    // eSett lags ~5-6 h -- if today's data is empty, fall back to yesterday
    if (today.count === 0) return fallback();
    return { data: today, dataDate: dateISO! };
  });

  return {
    data: data?.data ?? null,
    dataDate: data?.dataDate ?? null,
    loading,
    error,
  };
}
