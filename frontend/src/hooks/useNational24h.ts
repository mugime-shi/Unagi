import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";

export interface National24hEntry {
  timestamp_utc: string;
  hour_label: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  fossil: number;
  other: number;
  total_mw: number;
  renewable_pct: number | null;
}

export interface National24hResponse {
  count: number;
  latest_slot: string | null;
  renewable_pct: number | null;
  carbon_free_pct: number | null;
  zone_latest?: Partial<Record<"SE1" | "SE2" | "SE3" | "SE4", string>>;
  hourly: National24hEntry[];
}

interface UseNational24hReturn {
  data: National24hResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useNational24h(): UseNational24hReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<National24hResponse>(`${refreshKey}`, () =>
    fetchJson<National24hResponse>("/api/v1/generation/national-24h"),
  );
}
