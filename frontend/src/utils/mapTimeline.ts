import type { Area } from "../types/index";
import type { ZoneTimeline } from "../hooks/useZoneForecastFeed";
import { stockholmDateISO } from "./stockholmDate";

/** All user-facing copy of the map timeline, in one place for later translation. */
export const MAP_TIMELINE_TEXT = {
  play: "Play",
  pause: "Pause",
  now: "Now",
  sliderLabel: "Time for the price map",
  actualHeading: "Day-ahead price",
  actualBadge: "Actual",
  forecastHeading: (n: number) =>
    n > 0 ? `Forecast · d+${n}` : "Forecast · today",
  noData: "No data",
  forecastShort: "forecast",
  noDataZone: "no data",
  intervalTitle: "80% forecast interval",
  legendScale: "hourly price",
  plantsNote: "plant status is only known for now",
};

export const HOUR_MS = 3_600_000;

/** A zone's value at the selected hour. */
export interface MapTimelineZone {
  /** SEK/kWh */
  price: number;
  /** 80% interval in SEK/kWh; null for settled prices. */
  low: number | null;
  high: number | null;
  /** 0..1 fill strength: far-out forecasts are drawn fainter. */
  dim: number;
  forecast: boolean;
}

/** What SwedenMap needs to draw a non-"now" moment. */
export interface MapTimelineView {
  /** The current hour: the live map (plants, nuclear, spread) stays as it is; only the colours come from this view. */
  isNow: boolean;
  /** No zone has a value for this hour. */
  noData: boolean;
  forecast: boolean;
  /** e.g. "Forecast · d+3" or "Day-ahead price". */
  heading: string;
  /** e.g. "Mon 16 Nov · 14:00" */
  timeText: string;
  zones: Record<Area, MapTimelineZone | null>;
}

const ZONES: Area[] = ["SE1", "SE2", "SE3", "SE4"];

/** Each day further out loses this much fill strength, down to the floor. */
const DIM_PER_DAY = 0.08;
const DIM_FLOOR = 0.45;

const DAY_FMT = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Stockholm",
  weekday: "short",
  day: "numeric",
  month: "short",
});
const HOUR_FMT = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Stockholm",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Display only: the instant is converted to Stockholm wall time for the label. */
export function formatTimelineTime(ms: number): string {
  const d = new Date(ms);
  const day = DAY_FMT.formatToParts(d)
    .filter((p) => p.type !== "literal")
    .map((p) => p.value)
    .join(" ");
  return `${day} · ${HOUR_FMT.format(d)}`;
}

/** Short label for the one-line band, e.g. "Tue 14:00". */
export function formatTimelineShort(ms: number): string {
  const d = new Date(ms);
  const wd = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Stockholm",
    weekday: "short",
  }).format(d);
  return `${wd} ${HOUR_FMT.format(d)}`;
}

/** First instant of the current hour. Stockholm offsets are whole hours, so UTC hour == local hour. */
export function hourFloor(ms: number): number {
  return Math.floor(ms / HOUR_MS) * HOUR_MS;
}

/** Whole Stockholm calendar days from `nowMs` to `ms` (UTC-midnight difference of the two dates). */
function daysAhead(ms: number, nowMs: number): number {
  const a = Date.parse(stockholmDateISO(new Date(ms)));
  const b = Date.parse(stockholmDateISO(new Date(nowMs)));
  return Math.round((a - b) / 86_400_000);
}

/**
 * Slider span: from this hour to the last hour every zone has a value for.
 * Null when any zone is missing or the span is empty, so the slider stays hidden.
 */
export function timelineRange(
  feeds: Record<Area, ZoneTimeline>,
  nowMs: number,
): { start: number; end: number } | null {
  const start = hourFloor(nowMs);
  let end = Infinity;
  for (const z of ZONES) {
    const tl = feeds[z];
    if (!tl || !tl.has(start)) return null;
    let last = -Infinity;
    for (const t of tl.keys()) if (t > last) last = t;
    end = Math.min(end, last);
  }
  return end > start ? { start, end } : null;
}

/** Index (in hours from `start`) after which no hour is a settled price, or -1 if none is. */
export function lastActualIndex(
  feeds: Record<Area, ZoneTimeline>,
  start: number,
  end: number,
): number {
  let last = -1;
  for (let t = start; t <= end; t += HOUR_MS) {
    const allActual = ZONES.every((z) => feeds[z].get(t)?.kind === "actual");
    if (!allActual) break;
    last = (t - start) / HOUR_MS;
  }
  return last;
}

export function timelineView(
  feeds: Record<Area, ZoneTimeline>,
  ms: number,
  nowMs: number,
): MapTimelineView {
  const points = ZONES.map((z) => feeds[z].get(ms) ?? null);
  const forecast = points.some((p) => p?.kind === "forecast");
  // n = 0 only for a forecast standing in for the current hour (no settled price yet)
  const n = Math.max(0, daysAhead(ms, nowMs));
  const dim = forecast ? Math.max(DIM_FLOOR, 1 - DIM_PER_DAY * n) : 1;
  const zones = {} as Record<Area, MapTimelineZone | null>;
  ZONES.forEach((z, i) => {
    const p = points[i];
    zones[z] = p
      ? {
          price: p.price,
          low: p.kind === "forecast" ? p.low : null,
          high: p.kind === "forecast" ? p.high : null,
          dim: p.kind === "forecast" ? dim : 1,
          forecast: p.kind === "forecast",
        }
      : null;
  });
  return {
    isNow: ms <= hourFloor(nowMs),
    noData: points.every((p) => p == null),
    forecast,
    heading: forecast
      ? MAP_TIMELINE_TEXT.forecastHeading(n)
      : MAP_TIMELINE_TEXT.actualHeading,
    timeText: formatTimelineTime(ms),
    zones,
  };
}
