import type { GenHistoryDay } from "../hooks/useGenerationHistory";
import type { National24hEntry } from "../hooks/useNational24h";
import { bucketLabel, chunkByRange, meanOf } from "./bucket";

export interface GenChartRow {
  label: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  other: number;
}

export function national24hToRows(hourly: National24hEntry[]): GenChartRow[] {
  return hourly.map((h) => ({
    label: h.hour_label,
    hydro: h.hydro,
    nuclear: h.nuclear,
    wind: h.wind,
    solar: h.solar,
    other: h.other + h.fossil,
  }));
}

/** Daily national generation → chart rows, bucketed by range (see bucket.ts). */
export function historyToRows(
  daily: GenHistoryDay[],
  rangeDays: number,
): GenChartRow[] {
  const avg = (vals: number[]) => Math.round(meanOf(vals) ?? 0);
  return chunkByRange(daily, rangeDays).map((chunk) => ({
    label: bucketLabel(chunk[0].date, rangeDays),
    hydro: avg(chunk.map((d) => d.hydro)),
    nuclear: avg(chunk.map((d) => d.nuclear)),
    wind: avg(chunk.map((d) => d.wind)),
    solar: avg(chunk.map((d) => d.solar)),
    other: avg(chunk.map((d) => d.other + d.fossil)),
  }));
}
