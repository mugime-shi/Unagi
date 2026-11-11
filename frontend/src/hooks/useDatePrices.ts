import {
  ClearDataError,
  fetchJson,
  useAsyncResource,
} from "./useAsyncResource";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<PricesResponse>(
    date ? `${date}|${area}|${refreshKey}` : null,
    async () => {
      const res = await fetchJson<RangeApiResponse>(
        `/api/v1/prices/range?start=${date}&end=${date}&area=${area}`,
      );
      // /range returns { dates: [{ date, count, summary, prices }] }
      const dayData = res.dates?.[0];
      if (!dayData || dayData.count === 0) {
        throw new ClearDataError("No price data for this date");
      }
      // Reshape to match the /today response format
      return {
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
      };
    },
  );
}
