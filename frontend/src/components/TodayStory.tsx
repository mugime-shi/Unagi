"use client";

import type { ReactNode } from "react";
import { useStory } from "../hooks/useStory";
import { FuelBadgeIcon } from "./FuelBadge";
import type { Area, StoryItem } from "../types/index";
import type { FuelCat } from "../utils/fuel";

const ZONES: readonly string[] = ["SE1", "SE2", "SE3", "SE4"];

/** Story kinds about supply rather than a zone's price: no price page to jump to. */
const NON_PRICE_KINDS = new Set(["nuclear", "wind", "coupled"]);

/** Kind -> the map's fuel glyph, so the lede and the map speak the same visual language (no new colours). */
const KIND_ICON: Partial<Record<string, FuelCat>> = {
  nuclear: "nuclear",
  wind: "wind",
};

/** A story item links to its zone's hourly prices when it is about one zone's price. */
const zoneOf = (item: StoryItem): Area | null =>
  ZONES.includes(item.area) && !NON_PRICE_KINDS.has(item.kind)
    ? (item.area as Area)
    : null;

/** "14 Nov 2026" for the story's Stockholm date (a plain YYYY-MM-DD, so no timezone shift). */
function dateline(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Linked text when there is somewhere to go; plain text otherwise (no button look without an action). */
function ZoneLink({
  zone,
  onZoneClick,
  children,
  label,
}: {
  zone: Area | null;
  onZoneClick?: (zone: Area) => void;
  children: ReactNode;
  label: string;
}) {
  if (!zone || !onZoneClick) return <>{children}</>;
  return (
    <button
      type="button"
      onClick={() => onZoneClick(zone)}
      aria-label={label}
      className="group inline text-left rounded outline-none hover:text-content-primary focus-visible:ring-2 focus-visible:ring-sky-500"
    >
      {children}
      <span
        aria-hidden="true"
        className="ml-1 inline-block text-content-muted transition-[color,transform] group-hover:translate-x-0.5 group-hover:text-sky-500"
      >
        ›
      </span>
    </button>
  );
}

/**
 * The page's lede: what is notable in Swedish power today. Deliberately not a card — it sits on the page
 * background above the map card, so "summary" and "detail" read as different levels.
 */
export function TodayStory({
  onZoneClick,
}: {
  onZoneClick?: (zone: Area) => void;
}) {
  const { data, loading, error } = useStory();

  // A missing story must never break the page.
  if (error) return null;

  if (!data) {
    return loading ? (
      <div className="px-1 animate-pulse space-y-2">
        <div className="h-3 w-24 bg-surface-secondary rounded" />
        <div className="h-6 w-3/4 bg-surface-secondary rounded" />
        <div className="h-4 w-1/2 bg-surface-secondary rounded" />
      </div>
    ) : null;
  }

  const { headline, facts, context } = data;
  const icon = KIND_ICON[headline.kind];
  const headZone = zoneOf(headline);
  return (
    <section className="px-1 space-y-1.5" aria-label="Today">
      <p className="text-[11px] uppercase tracking-wide text-content-muted">
        Today · {dateline(data.date)}
      </p>
      <h2 className="flex items-center gap-2 text-lg sm:text-xl text-content-primary leading-snug">
        {icon && (
          <span className="shrink-0 text-content-secondary" aria-hidden="true">
            <FuelBadgeIcon cat={icon} r={9} />
          </span>
        )}
        <ZoneLink
          zone={headZone}
          onZoneClick={onZoneClick}
          label={`${headline.text} — ${headZone} hourly prices`}
        >
          {headline.text}
        </ZoneLink>
      </h2>
      {headline.sub && (
        <p className="text-sm text-content-secondary">{headline.sub}</p>
      )}
      {context && <p className="text-xs text-content-muted">{context}</p>}
      {facts.length > 0 && (
        <p className="text-xs sm:text-sm text-content-secondary leading-relaxed">
          {facts.map((f, i) => {
            const zone = zoneOf(f);
            return (
              // Mobile: one fact per line (a wrapped "·" would start a line); sm+: one line with separators
              <span
                key={f.kind}
                className="block sm:inline sm:whitespace-nowrap"
              >
                {i > 0 && (
                  <span
                    className="hidden sm:inline mx-2 text-content-faint"
                    aria-hidden="true"
                  >
                    ·
                  </span>
                )}
                <ZoneLink
                  zone={zone}
                  onZoneClick={onZoneClick}
                  label={`${f.text} — ${zone} hourly prices`}
                >
                  {f.text}
                </ZoneLink>
              </span>
            );
          })}
        </p>
      )}
    </section>
  );
}
