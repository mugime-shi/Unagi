import { useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area } from "../types/index";

// The public v1 feed, not /prices/forecast/weekly: it carries exact instants
// (ISO with offset, so DST days need no hour arithmetic), includes today, and
// serves actual and forecast hours in one shape. It is CORS-open and takes no
// API key, so it is fetched with plain fetch (a custom header would force a
// preflight).
const FEED_BASE: string =
  process.env.NEXT_PUBLIC_FEED_BASE ?? "https://catch.unagieel.net/v1/forecast";

const ZONES: Area[] = ["SE1", "SE2", "SE3", "SE4"];

interface FeedHour {
  start: string;
  value: number;
  low: number;
  high: number;
}

interface FeedDay {
  kind: "actual" | "forecast";
  hours: FeedHour[];
}

interface FeedResponse {
  days: FeedDay[];
}

/** One zone-hour of the timeline. Prices are SEK/kWh. */
export interface TimelinePoint {
  price: number;
  low: number;
  high: number;
  /** "actual" = settled day-ahead price; "forecast" = model output. */
  kind: "actual" | "forecast";
}

/** Hour-start epoch ms (UTC) -> point, per zone. */
export type ZoneTimeline = Map<number, TimelinePoint>;

function parseFeed(json: FeedResponse): ZoneTimeline {
  const m: ZoneTimeline = new Map();
  for (const day of json.days) {
    for (const h of day.hours) {
      const t = Date.parse(h.start);
      if (Number.isNaN(t) || typeof h.value !== "number") continue;
      m.set(t, {
        price: h.value,
        low: h.low,
        high: h.high,
        kind: day.kind,
      });
    }
  }
  return m;
}

async function fetchFeeds(): Promise<Record<Area, ZoneTimeline>> {
  const entries = await Promise.all(
    ZONES.map(async (zone) => {
      const r = await fetch(`${FEED_BASE}/${zone}.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return [zone, parseFeed((await r.json()) as FeedResponse)] as const;
    }),
  );
  return Object.fromEntries(entries) as Record<Area, ZoneTimeline>;
}

/** Hourly actual + 7-day forecast (with 80% interval) for all four zones. */
export function useZoneForecastFeed() {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource(`${refreshKey}`, fetchFeeds);
}
