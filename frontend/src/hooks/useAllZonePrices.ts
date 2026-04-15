import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, PricesResponse } from "../types/index";

const ZONES: Area[] = ["SE1", "SE2", "SE3", "SE4"];

export interface ZonePriceSummary {
  zone: Area;
  current_sek_kwh: number | null;
  today_avg_sek_kwh: number | null;
  today_min_sek_kwh: number | null;
  today_max_sek_kwh: number | null;
  slots: { hour: number; price: number }[];
}

interface UseAllZonePricesReturn {
  data: Record<Area, ZonePriceSummary> | null;
  loading: boolean;
  error: Error | null;
}

function currentStockholmHour(): number {
  const s = new Date().toLocaleString("sv-SE", {
    timeZone: "Europe/Stockholm",
    hour: "2-digit",
    hour12: false,
  });
  return parseInt(s, 10);
}

function summarizeZone(
  zone: Area,
  resp: PricesResponse | null,
): ZonePriceSummary {
  if (!resp?.prices?.length) {
    return {
      zone,
      current_sek_kwh: null,
      today_avg_sek_kwh: null,
      today_min_sek_kwh: null,
      today_max_sek_kwh: null,
      slots: [],
    };
  }
  // Group 15-min slots into hourly averages
  const byHour = new Map<number, number[]>();
  for (const p of resp.prices) {
    const d = new Date(p.timestamp_utc);
    const hour = parseInt(
      d.toLocaleTimeString("sv-SE", {
        timeZone: "Europe/Stockholm",
        hour: "2-digit",
        hour12: false,
      }),
      10,
    );
    const list = byHour.get(hour) ?? [];
    list.push(p.price_sek_kwh);
    byHour.set(hour, list);
  }
  const slots: { hour: number; price: number }[] = Array.from(byHour.entries())
    .map(([hour, prices]) => ({
      hour,
      price: prices.reduce((s, v) => s + v, 0) / prices.length,
    }))
    .sort((a, b) => a.hour - b.hour);

  const nowHour = currentStockholmHour();
  const currentSlot =
    slots.find((s) => s.hour === nowHour) ?? slots[slots.length - 1];
  return {
    zone,
    current_sek_kwh: currentSlot?.price ?? null,
    today_avg_sek_kwh: resp.summary?.avg_sek_kwh ?? null,
    today_min_sek_kwh: resp.summary?.min_sek_kwh ?? null,
    today_max_sek_kwh: resp.summary?.max_sek_kwh ?? null,
    slots,
  };
}

export function useAllZonePrices(): UseAllZonePricesReturn {
  const [data, setData] = useState<Record<Area, ZonePriceSummary> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all(
      ZONES.map((zone) =>
        apiFetch(`/api/v1/prices/today?area=${zone}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((json) => ({ zone, resp: json as PricesResponse | null }))
          .catch(() => ({ zone, resp: null as PricesResponse | null })),
      ),
    )
      .then((results) => {
        if (cancelled) return;
        const record: Partial<Record<Area, ZonePriceSummary>> = {};
        for (const { zone, resp } of results) {
          record[zone] = summarizeZone(zone, resp);
        }
        setData(record as Record<Area, ZonePriceSummary>);
        setLoading(false);
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
  }, []);

  return { data, loading, error };
}
