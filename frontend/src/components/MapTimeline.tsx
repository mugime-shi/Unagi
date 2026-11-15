"use client";

import {
  useEffect,
  useEffectEvent,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import type { Area } from "../types/index";
import type { ZoneTimeline } from "../hooks/useZoneForecastFeed";
import { formatPrice } from "../utils/formatters";
import {
  HOUR_MS,
  MAP_TIMELINE_TEXT as T,
  formatTimelineTime,
  hourFloor,
  lastActualIndex,
  timelineRange,
  type MapTimelineView,
} from "../utils/mapTimeline";
import { trackEvent } from "../utils/track";

const ZONES: Area[] = ["SE1", "SE2", "SE3", "SE4"];

// ~6.7 h of map time per second; reduced motion gets coarser frame steps instead.
const TICK_MS = 150;
const STEP_HOURS = 1;
const REDUCED_TICK_MS = 1000;
const REDUCED_STEP_HOURS = 6;

// Module-level so a remount cannot send the event twice per page load.
let playTracked = false;

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mql = window.matchMedia(REDUCED_QUERY);
      mql.addEventListener("change", cb);
      return () => mql.removeEventListener("change", cb);
    },
    () => window.matchMedia(REDUCED_QUERY).matches,
    () => false,
  );
}

interface MapTimelineProps {
  feeds: Record<Area, ZoneTimeline>;
  /** Selected hour start (epoch ms, UTC); null = Now. */
  selectedMs: number | null;
  onSelect: (ms: number | null) => void;
  /** View at the selected hour, for the per-zone readout shown on narrow layouts. */
  view: MapTimelineView | null;
  showZoneValues: boolean;
}

export function MapTimeline({
  feeds,
  selectedMs,
  onSelect,
  view,
  showZoneValues,
}: MapTimelineProps) {
  const reduced = useReducedMotion();
  const [playing, setPlaying] = useState(false);

  // Range follows the wall clock so the slider's left edge stays "this hour".
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const range = useMemo(() => timelineRange(feeds, nowMs), [feeds, nowMs]);
  const start = range ? range.start : hourFloor(nowMs);
  const end = range ? range.end : start;
  const lastIdx = Math.round((end - start) / HOUR_MS);
  const idx =
    selectedMs == null
      ? 0
      : Math.min(
          lastIdx,
          Math.max(0, Math.round((selectedMs - start) / HOUR_MS)),
        );

  const stepHours = reduced ? REDUCED_STEP_HOURS : STEP_HOURS;
  const tick = useEffectEvent(() => {
    const next = Math.min(lastIdx, idx + stepHours);
    onSelect(next === 0 ? null : start + next * HOUR_MS);
    if (next >= lastIdx) setPlaying(false);
  });
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(tick, reduced ? REDUCED_TICK_MS : TICK_MS);
    return () => clearInterval(id);
  }, [playing, reduced]);

  // Day boundaries (Stockholm midnight) and the actual/forecast split, as
  // fractions of the track, so the scale reads as "days from now".
  const marks = useMemo(() => {
    if (!range) return null;
    const dayFmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Stockholm",
      weekday: "short",
    });
    const hourFmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Stockholm",
      hour: "2-digit",
      hour12: false,
    });
    const days: { frac: number; label: string }[] = [];
    for (let t = range.start + HOUR_MS; t <= range.end; t += HOUR_MS) {
      if (hourFmt.format(new Date(t)) === "00")
        days.push({
          frac: (t - range.start) / (range.end - range.start),
          label: dayFmt.format(new Date(t)),
        });
    }
    const a = lastActualIndex(feeds, range.start, range.end);
    return { days, actualFrac: a < 0 ? 0 : a / lastIdx };
  }, [feeds, range, lastIdx]);

  if (!range || !marks) return null;

  const atEnd = idx >= lastIdx;
  const select = (i: number) => onSelect(i === 0 ? null : start + i * HOUR_MS);
  const togglePlay = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (!playTracked) {
      playTracked = true;
      trackEvent("action", "map_timeline_play");
    }
    if (atEnd) select(0);
    setPlaying(true);
  };

  const when = formatTimelineTime(selectedMs ?? start);
  const heading = view ? view.heading : T.actualBadge;
  const pct = Math.round(marks.actualFrac * 100);

  const btn =
    "shrink-0 rounded-lg border border-[color-mix(in_srgb,var(--text-primary)_15%,transparent)] px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 transition-colors disabled:opacity-40";

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={togglePlay}
          className={`${btn} min-w-[4.5rem]`}
        >
          {playing ? T.pause : T.play}
        </button>
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            onSelect(null);
          }}
          disabled={selectedMs == null}
          className={btn}
        >
          {T.now}
        </button>
        <p
          className="ml-auto text-right text-sm text-content-primary tabular-nums"
          aria-live="off"
        >
          <span className="font-medium">{when}</span>
          <span
            className={`ml-2 text-xs ${view?.forecast ? "text-amber-600 dark:text-amber-400" : "text-content-muted"}`}
          >
            {heading}
          </span>
        </p>
      </div>

      <div>
        <input
          type="range"
          min={0}
          max={lastIdx}
          step={1}
          value={idx}
          onChange={(e) => {
            setPlaying(false);
            select(Number(e.target.value));
          }}
          aria-label={T.sliderLabel}
          aria-valuetext={`${when}, ${heading}`}
          className="block w-full cursor-pointer accent-sky-500"
        />
        {/* Track scale: solid = settled prices, fading = forecast; day ticks in Stockholm time */}
        <div
          className="relative mx-2 mt-0.5 h-1 rounded-full"
          aria-hidden="true"
          style={{
            background: `linear-gradient(to right, var(--text-secondary) 0%, var(--text-secondary) ${pct}%, color-mix(in srgb, var(--text-secondary) 45%, transparent) ${pct}%, color-mix(in srgb, var(--text-secondary) 8%, transparent) 100%)`,
          }}
        />
        <div
          className="relative mx-2 mt-1 h-3 text-[10px] text-content-muted"
          aria-hidden="true"
        >
          {marks.days.map((d) => (
            <span
              key={d.frac}
              className="absolute -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${d.frac * 100}%` }}
            >
              {d.label}
            </span>
          ))}
        </div>
      </div>

      {showZoneValues && view && (
        <div className="grid grid-cols-4 gap-1 text-center text-[11px] tabular-nums">
          {ZONES.map((z) => {
            const v = view.zones[z];
            return (
              <div
                key={z}
                className="rounded-md bg-surface-secondary px-1 py-1"
              >
                <p className="text-[10px] text-content-muted">{z}</p>
                <p className="font-semibold text-content-primary">
                  {v ? formatPrice(v.price) : "—"}
                </p>
                {v?.low != null && v.high != null && (
                  <p
                    className="text-[10px] text-content-muted"
                    title={T.intervalTitle}
                  >
                    {formatPrice(v.low)}–{formatPrice(v.high)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
