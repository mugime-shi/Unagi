import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type {
  Area,
  PricesResponse,
  PricePoint,
  PriceSummary,
} from "../types/index";

interface RangeDayData {
  date: string;
  count: number;
  summary: PriceSummary;
  prices: PricePoint[];
}

interface RangeApiResponse {
  area: string;
  currency?: string;
  dates: RangeDayData[];
}

interface UseDatePricesReturn {
  data: PricesResponse | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Fetch spot prices for a specific date via /api/v1/prices/range.
 * Returns the same shape as usePrices (data with .prices, .summary, .date, etc.)
 * so PriceChart can consume it directly.
 */
export function useDatePrices(
  date: string | null,
  area: Area = "SE3",
): UseDatePricesReturn {
  const [data, setData] = useState<PricesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/range?start=${date}&end=${date}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((res: RangeApiResponse) => {
        // /range returns { dates: [{ date, count, summary, prices }] }
        const dayData = res.dates?.[0];
        if (!dayData || dayData.count === 0) {
          setData(null);
          setError(new Error("No price data for this date"));
          return;
        }
        // Reshape to match the /today response format
        setData({
          area: res.area,
          date: dayData.date,
          currency: res.currency,
          is_estimate: false,
          count: dayData.count,
          summary: {
            ...dayData.summary,
            month_avg_sek_kwh: null,
          },
          prices: dayData.prices,
        });
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [date, area, refreshKey]);

  return { data, loading, error };
}
