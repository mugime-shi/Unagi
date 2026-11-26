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
import { GLASS_STYLE } from "../utils/mapGlass";
import {
  HOUR_MS,
  MAP_TIMELINE_TEXT as T,
  formatTimelineShort,
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
  view: MapTimelineView | null;
}

export function MapTimeline({
  feeds,
  selectedMs,
  onSelect,
  view,
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

  // Stockholm midnights and the actual/forecast split, as fractions of the track
  const marks = useMemo(() => {
    if (!range) return null;
    const hourFmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Stockholm",
      hour: "2-digit",
      hour12: false,
    });
    const days: number[] = [];
    for (let t = range.start + HOUR_MS; t <= range.end; t += HOUR_MS) {
      if (hourFmt.format(new Date(t)) === "00")
        days.push((t - range.start) / (range.end - range.start));
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

  const at = selectedMs ?? start;
  const when = formatTimelineTime(at);
  const heading = !view
    ? T.actualBadge
    : view.noData
      ? T.noData
      : view.forecast
        ? view.heading
        : T.actualBadge;
  const note = view?.noData
    ? T.noData
    : view?.forecast
      ? T.forecastShort
      : null;
  const pct = marks.actualFrac * 100;

  return (
    // One-line band at the map's foot; data-map-ui keeps drags on the slider from panning the map
    <div
      data-map-ui
      className="flex w-full items-center gap-1 rounded-xl px-1.5 pointer-events-auto"
      style={GLASS_STYLE}
    >
      {/* Visually small, 32px tap target */}
      <button
        type="button"
        onClick={togglePlay}
        aria-label={playing ? T.pause : T.play}
        title={playing ? T.pause : T.play}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-content-secondary hover:text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          {playing ? (
            <path d="M2 1h3v10H2zM7 1h3v10H7z" fill="currentColor" />
          ) : (
            <path d="M2 1l9 5-9 5z" fill="currentColor" />
          )}
        </svg>
      </button>

      <div className="relative min-w-0 flex-1">
        {/* Track: solid = settled prices, dashed = forecast, ticks = Stockholm midnights.
            Inset by the thumb radius so fractions line up with the thumb centre. */}
        <div
          className="pointer-events-none absolute inset-y-0 left-1.5 right-1.5"
          aria-hidden="true"
        >
          <div
            className="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full"
            style={{
              width: `${pct}%`,
              background:
                "color-mix(in srgb, var(--text-primary) 65%, transparent)",
            }}
          />
          <div
            className="absolute right-0 top-1/2 h-0.5 -translate-y-1/2"
            style={{
              left: `${pct}%`,
              background:
                "repeating-linear-gradient(to right, color-mix(in srgb, var(--text-primary) 40%, transparent) 0 4px, transparent 4px 7px)",
            }}
          />
          {marks.days.map((f) => (
            <span
              key={f}
              className="absolute top-1/2 h-2 w-px -translate-y-1/2"
              style={{
                left: `${f * 100}%`,
                background:
                  "color-mix(in srgb, var(--text-primary) 35%, transparent)",
              }}
            />
          ))}
        </div>
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
          className="map-range relative"
        />
      </div>

      <p className="shrink-0 whitespace-nowrap pl-1 text-xs tabular-nums text-content-primary">
        <span className="font-medium">{formatTimelineShort(at)}</span>
        {note && (
          <span className="ml-1 italic text-amber-600 dark:text-amber-400">
            {note}
          </span>
        )}
      </p>
      {selectedMs != null && idx > 0 && (
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            onSelect(null);
          }}
          className="shrink-0 rounded px-1 text-xs text-sky-600 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 dark:text-sky-400"
        >
          {T.now}
        </button>
      )}
    </div>
  );
}

/** Per-zone values at the shown hour, for layouts where the map carries no price card (narrow). */
export function ZoneReadout({ view }: { view: MapTimelineView }) {
  return (
    <div className="mt-2 grid grid-cols-4 gap-1 text-center text-[11px] tabular-nums">
      {ZONES.map((z) => {
        const v = view.zones[z];
        return (
          <div key={z} className="leading-tight">
            <span className="text-[10px] text-content-muted">{z} </span>
            <span className="font-semibold text-content-primary">
              {v ? formatPrice(v.price) : "—"}
            </span>
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
  );
}
