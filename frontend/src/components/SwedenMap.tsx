"use client";

import { useTheme } from "next-themes";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { GLASS_STYLE } from "../utils/mapGlass";
import { FuelBadgeIcon } from "./FuelBadge";
import { TrendArrow } from "./TrendArrow";
import { FUEL_CAT_LABEL, fuelCat, fuelName, type FuelCat } from "../utils/fuel";
import { formatPrice, PRICE_UNIT } from "../utils/formatters";
import {
  PLANT_CATS,
  PLANT_EICS,
  PLANT_GROUPS,
  outagesByEic,
  plantState,
  groupStatus,
  type PlantState,
  type PlantStatus,
  type PlantUnit,
} from "../utils/plants";
import { MAX_ZOOM, useMapZoom } from "../hooks/useMapZoom";
import { clusterMarkers, type Cluster } from "../utils/mapCluster";
import zoneMap from "../data/swedenZones.json";
import type { ZonePriceSummary } from "../hooks/useAllZonePrices";
import type {
  Area,
  NuclearUnit,
  OtherOutage,
  OutageInfo,
  OutagesResponse,
} from "../types/index";

const ZONES: Area[] = ["SE1", "SE2", "SE3", "SE4"];

// Status colors: emerald / amber / rose (500 shade)
const STATUS_COLOR: Record<PlantStatus, string> = {
  running: "#10b981",
  reduced: "#f59e0b",
  offline: "#f43f5e",
  unknown: "#94a3b8",
};

/**
 * The reactors are fixed, so their sites are drawn even without the outage feed (status "unknown").
 * Mirrors NUCLEAR_UNITS in backend/app/services/outage_service.py.
 */
const NUCLEAR_UNITS: { name: string; area: string; mw: number }[] = [
  { name: "Forsmark 1", area: "SE3", mw: 1100 },
  { name: "Forsmark 2", area: "SE3", mw: 1121 },
  { name: "Forsmark 3", area: "SE3", mw: 1172 },
  { name: "Ringhals 3", area: "SE3", mw: 1063 },
  { name: "Ringhals 4", area: "SE3", mw: 1134 },
  { name: "Oskarshamn 3", area: "SE3", mw: 1400 },
];

/** A reactor as drawn: the feed's record, or a placeholder with status "unknown". */
type SiteUnit = Omit<NuclearUnit, "status"> & { status: PlantStatus };

// Luminous price scale, öre/kWh → cyan glow (cheap) · mint · amber · coral · magenta (expensive).
// The mint and coral stops keep the RGB interpolation vivid (cyan→amber direct would pass through a pale grey-green).
const SCALE_STOPS = [0, 70, 150, 220, 300];
const SCALE_COLORS: Record<"dark" | "light", string[]> = {
  dark: ["#2de2e6", "#7df0b0", "#ffc233", "#ff7a2e", "#ff4f86"],
  light: ["#0ea5c6", "#10b981", "#f59e0b", "#ef4444", "#db2777"],
};

// Stage colors: sea (map background) and the receding neighbouring land
const STAGE: Record<
  "dark" | "light",
  {
    sea: string;
    land: string;
    landStroke: string;
    countryLabel: string;
    river: string;
  }
> = {
  dark: {
    sea: "#091321",
    land: "#0e1a2c",
    landStroke: "#22395c",
    countryLabel: "#35507a",
    river: "#3b6ea8",
  },
  light: {
    sea: "#d6e4f1",
    land: "#e7ecf1",
    landStroke: "#c3cfdb",
    countryLabel: "#a3b1c1",
    river: "#7fa8d4",
  },
};

/** Zone fill: the vivid price colour as a translucent layer (map detail shows through); hover adds opacity. */
// Opacity is per stop: warm hues need more of it (dark theme) or they composite into a muddy brown over the navy sea.
const ZONE_FILL: Record<
  "dark" | "light",
  { alpha: number[]; hoverBoost: number }
> = {
  dark: { alpha: [0.42, 0.42, 0.6, 0.62, 0.58], hoverBoost: 0.14 },
  light: { alpha: [0.42, 0.42, 0.42, 0.42, 0.42], hoverBoost: 0.14 },
};
/** Zone outline: brighter (dark) / deeper (light) than the fill hue. Glow is dark-only. */
const ZONE_STROKE_MIX: Record<"dark" | "light", { to: string; t: number }> = {
  dark: { to: "#ffffff", t: 0.15 },
  light: { to: "#000000", t: 0.3 },
};
/** Glow blur radius in CSS px (scaled by the zoom factor so it stays constant on screen). */
const GLOW_PX = 2.6;
/** Glow opacity (dark only): the blurred halo is dimmed so the outline reads luminous but not harsh. */
const GLOW_OPACITY = 0.65;

/**
 * The ONE place where price colours are derived: the zone fills (at ZONE_FILL opacity), outlines, the legend
 * gradient and the summary swatches all start from these vivid colours, so they cannot drift.
 */
function pricePalette(theme: "dark" | "light"): string[] {
  return SCALE_COLORS[theme];
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function scaleRgb(ore: number, colors: string[]): [number, number, number] {
  const last = SCALE_STOPS.length - 1;
  const v = Math.max(SCALE_STOPS[0], Math.min(SCALE_STOPS[last], ore));
  let i = 0;
  while (i < last - 1 && v > SCALE_STOPS[i + 1]) i++;
  const t = (v - SCALE_STOPS[i]) / (SCALE_STOPS[i + 1] - SCALE_STOPS[i]);
  const a = hexToRgb(colors[i]);
  const b = hexToRgb(colors[i + 1]);
  return a.map((x, k) => Math.round(x + (b[k] - x) * t)) as [
    number,
    number,
    number,
  ];
}

function scaleAlpha(ore: number, alphas: number[]): number {
  const last = SCALE_STOPS.length - 1;
  const v = Math.max(SCALE_STOPS[0], Math.min(SCALE_STOPS[last], ore));
  let i = 0;
  while (i < last - 1 && v > SCALE_STOPS[i + 1]) i++;
  const t = (v - SCALE_STOPS[i]) / (SCALE_STOPS[i + 1] - SCALE_STOPS[i]);
  return alphas[i] + (alphas[i + 1] - alphas[i]) * t;
}

const rgbCss = (c: number[]) => `rgb(${c[0]},${c[1]},${c[2]})`;
const scaleColor = (ore: number, colors: string[]) =>
  rgbCss(scaleRgb(ore, colors));

type Pt = [number, number];
const SITES = zoneMap.sites as unknown as Record<string, Pt>;
const UNITS = zoneMap.units as unknown as Record<string, Pt>;
const LABELS = zoneMap.labelPoints as unknown as Record<string, Pt>;
const COUNTRY_LABELS = zoneMap.countryLabels as unknown as Record<string, Pt>;
const PATHS = zoneMap.zones as Record<string, string>;
const MOBILE_VB = zoneMap.mobileViewBox as unknown as [
  number,
  number,
  number,
  number,
];
// Cropped to Sweden (+ margin for the cards) so the country fills a taller figure: 940x1000 vs the full 1170x1000
const WIDE_VB: [number, number, number, number] = [70, 0, 940, zoneMap.height];

// ── Overlay layout (percent of the map box; y = vertical centre of the card) ──
const ZONE_CITY: Record<Area, string> = {
  SE1: "Luleå",
  SE2: "Sundsvall",
  SE3: "Stockholm",
  SE4: "Malmö",
};
/** Outages at least this big (MW) are listed/placed even when the plant list does not know the unit. */
const LARGE_MW = 300;
/** From this zoom plants switch from status dots to fuel glyphs. */
const ICON_ZOOM = 2;
/** Marker size by capacity: sqrt scale between these MW values (below/above clamps). */
const SIZE_MW_MIN = 100;
const SIZE_MW_MAX = 3500;
const sizeFactor = (mw: number) => {
  const lo = Math.sqrt(SIZE_MW_MIN);
  const t = (Math.sqrt(mw) - lo) / (Math.sqrt(SIZE_MW_MAX) - lo);
  return 0.9 + 0.6 * Math.max(0, Math.min(1, t));
};
/** Cluster on a quantised log-zoom so the grouping does not recompute (or flicker) on every animation frame. */
const ZOOM_STEPS_PER_E = 24;
/** Smallest height a popover is squeezed to when neither side of its marker has room. */
const MIN_POP_H = 120;
interface SwedenMapProps {
  prices: Record<Area, ZonePriceSummary> | null;
  outages: OutagesResponse | null;
  onZoneClick?: (zone: Area) => void;
  /** "wide": glass cards over the map (needs ~800 px). "compact": in-map labels + chips for phones. */
  layout: "wide" | "compact";
  /** Price direction per zone (computed by the Overview from the day-ahead curve). */
  trends?: Record<Area, "up" | "down" | null> | null;
  hoverZone?: Area | null;
  onHoverZone?: (zone: Area | null) => void;
  /** True when the outages request failed (shown as a small note instead of nuclear info). */
  outagesError?: boolean;
}

function siteOf(unit: { name: string }): string {
  return unit.name.replace(/\s+\d+$/, "");
}

/** "Forsmark 1" -> "F1" */
function shortName(unit: { name: string }): string {
  return unit.name.replace(/^(\S)\S*\s+(\d+)$/, "$1$2");
}

/** "12 Dec" in Stockholm time (display only). */
function backDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    timeZone: "Europe/Stockholm",
    day: "numeric",
    month: "short",
  });
}

function earliestReturn(units: SiteUnit[]): string | null {
  const ends = units
    .filter((u) => u.status === "offline" && u.outage)
    .map((u) => u.outage!.end)
    .sort();
  return ends.length ? backDate(ends[0]) : null;
}

function useElementWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

// ── Outage detail (popover anchored inside the map) ──
interface Detail {
  id: string;
  title: string;
  sub?: string;
  status: PlantStatus;
  availableMw: number;
  nominalMw: number;
  outage: OutageInfo | null;
  /** Fuel in words (non-nuclear outages only). */
  fuel?: string;
  /** Plant-layer unit: status is "available" rather than "running" and wind gets a note. */
  plant?: boolean;
  wind?: boolean;
  /** Nuclear site: its reactors (rendered as chips + summary). */
  units?: SiteUnit[];
}

const STATUS_LABEL: Record<PlantStatus, string> = {
  running: "Running",
  reduced: "Reduced",
  offline: "Offline",
  unknown: "Unknown",
};

const siteDetail = (site: string, units: SiteUnit[]): Detail => ({
  id: `nuclear:${site}`,
  title: site,
  sub: units[0]?.area,
  status: groupStatus(units.map((u) => u.status)),
  availableMw: units.reduce((t, u) => t + u.available_mw, 0),
  nominalMw: units.reduce((t, u) => t + u.nominal_mw, 0),
  outage: null,
  plant: true,
  units,
});
const otherId = (o: OtherOutage) =>
  `other-${o.area}-${o.resource_eic ?? o.name}`;
const otherDetail = (o: OtherOutage): Detail => ({
  id: otherId(o),
  title: o.name,
  sub: o.area,
  status: o.available_mw <= 0 ? "offline" : "reduced",
  availableMw: o.available_mw,
  nominalMw: o.nominal_mw,
  outage: o.outage,
  fuel: fuelName(o.psr_type),
});
const plantDetail = (s: PlantState): Detail => ({
  id: `plant-${s.unit.eic}`,
  title: s.unit.name,
  sub: s.unit.area,
  status: s.status,
  availableMw: s.availableMw,
  nominalMw: s.nominalMw,
  outage: s.outage,
  fuel: fuelName(s.unit.psr),
  plant: true,
  wind: fuelCat(s.unit.psr) === "wind",
});
const lostMw = (o: OtherOutage) => Math.round(o.nominal_mw - o.available_mw);
const gw = (mw: number) => (mw / 1000).toFixed(1);

/** Generic placeholders the feed uses instead of a real reason. */
const isPlaceholderReason = (r: string) =>
  ["", "outage", "unavailability"].includes(r.trim().toLowerCase());

/** Reason + dates of an outage (shared by reactors, unmapped outages and plants). */
function OutageLines({ d }: { d: Detail }) {
  if (!d.outage) return null;
  return (
    <>
      {d.outage.reason && !(d.fuel && isPlaceholderReason(d.outage.reason)) && (
        <p className="text-[11px] text-content-secondary break-words">
          {d.outage.reason}
        </p>
      )}
      <p className="text-[10px] text-content-muted">
        {d.outage.type === "forced" ? "Forced outage" : "Planned outage"} ·
        {d.fuel &&
          ` ${new Date(d.outage.start) > new Date() ? "from" : "out since"} ${backDate(d.outage.start)} ·`}{" "}
        back {backDate(d.outage.end)}
      </p>
    </>
  );
}

const PLANT_STATUS_LABEL: Record<PlantStatus, string> = {
  running: "Available",
  reduced: "Reduced",
  offline: "Offline",
  unknown: "Unknown",
};

function PlantBody({ d }: { d: Detail }) {
  const c = STATUS_COLOR[d.status];
  const line =
    d.status === "unknown"
      ? "Status unavailable right now"
      : d.status === "offline"
        ? "Offline"
        : d.status === "reduced"
          ? `Reduced: ${Math.round(d.availableMw)} of ${Math.round(d.nominalMw)} MW available`
          : d.outage
            ? "Available"
            : "Available — no outage reported";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-content-primary">{d.title}</p>
        <span
          className="shrink-0 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
          style={{ background: `color-mix(in srgb, ${c} 18%, transparent)` }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: c }}
          />
          {PLANT_STATUS_LABEL[d.status]}
        </span>
      </div>
      <p className="text-[11px] text-content-secondary">
        {d.fuel} · {d.sub} · {Math.round(d.nominalMw)} MW
      </p>
      <p className="text-[11px] text-content-secondary tabular-nums">{line}</p>
      <OutageLines d={d} />
      {d.wind && !d.outage && d.status !== "unknown" && (
        <p className="text-[10px] text-content-muted">
          Output depends on wind; ENTSO-E publishes no per-plant output for
          Sweden.
        </p>
      )}
    </div>
  );
}

function DetailBody({ d }: { d: Detail }) {
  if (d.units) return <SiteBody d={d} units={d.units} />;
  if (d.plant) return <PlantBody d={d} />;
  const c = STATUS_COLOR[d.status];
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-content-primary">
          {d.title}
          {d.sub && (
            <span className="font-normal text-content-muted"> · {d.sub}</span>
          )}
        </p>
        <span
          className="shrink-0 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
          style={{ background: `color-mix(in srgb, ${c} 18%, transparent)` }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: c }}
          />
          {STATUS_LABEL[d.status]}
        </span>
      </div>
      <p className="text-[11px] text-content-secondary tabular-nums">
        {Math.round(d.availableMw)} / {Math.round(d.nominalMw)} MW available
      </p>
      {d.fuel && <p className="text-[11px] text-content-secondary">{d.fuel}</p>}
      {d.outage ? (
        <OutageLines d={d} />
      ) : (
        <p className="text-[10px] text-content-muted">No outage reported</p>
      )}
    </div>
  );
}

interface PopCtl {
  openId: string | null;
  enter: (id: string, el: HTMLElement) => void;
  leave: () => void;
  toggle: (id: string, el: HTMLElement) => void;
}

/** Reactor chip: unit name tinted by its status. */
function ReactorChip({ unit }: { unit: SiteUnit }) {
  const c = STATUS_COLOR[unit.status];
  return (
    <span
      title={`${unit.name}: ${STATUS_LABEL[unit.status]}`}
      className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-content-secondary"
      style={{ background: `color-mix(in srgb, ${c} 18%, transparent)` }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: c }}
      />
      {shortName(unit)}
    </span>
  );
}

/** Nuclear site popover body: per-reactor chips, offline summary and expected return. */
function SiteBody({ d, units }: { d: Detail; units: SiteUnit[] }) {
  const back = earliestReturn(units);
  const off = units.filter((u) => u.status === "offline").length;
  const lost = units.reduce(
    (sum, u) => sum + (u.nominal_mw - u.available_mw),
    0,
  );
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-content-primary">
          {d.title}
          {d.sub && (
            <span className="font-normal text-content-muted"> · {d.sub}</span>
          )}
        </p>
        <p
          className="text-[10px] tabular-nums"
          style={{ color: lost > 0 ? STATUS_COLOR.offline : undefined }}
        >
          {d.status === "unknown" ? (
            <span className="text-content-muted">status unavailable</span>
          ) : lost > 0 ? (
            `${off}/${units.length} offline · ${gw(lost)} GW`
          ) : (
            <span className="text-content-muted">all running</span>
          )}
        </p>
      </div>
      <p className="text-[10px] text-content-muted">Nuclear</p>
      <div className="flex flex-wrap gap-1">
        {units.map((u) => (
          <ReactorChip key={u.name} unit={u} />
        ))}
      </div>
      {back && <p className="text-[10px] text-content-muted">back {back}</p>}
    </div>
  );
}

/** Top-left summary: current spot price per zone, north-south spread and nuclear capacity offline. */
function SummaryCard({
  prices,
  trends,
  palette,
  hoverZone,
  onZoneClick,
  onHoverZone,
  spread,
  outages,
  outagesError,
}: {
  prices: Record<Area, ZonePriceSummary> | null;
  trends?: Record<Area, "up" | "down" | null> | null;
  palette: string[];
  hoverZone?: Area | null;
  onZoneClick?: (zone: Area) => void;
  onHoverZone?: (zone: Area | null) => void;
  spread: number | null;
  outages: OutagesResponse | null;
  outagesError?: boolean;
}) {
  const total = outages?.nuclear.reduce((sum, u) => sum + u.nominal_mw, 0) ?? 0;
  const offline = outages?.nuclear_offline_mw ?? 0;
  const down = new Map<string, { n: number; off: number; red: number }>();
  for (const u of outages?.nuclear ?? []) {
    const e = down.get(siteOf(u)) ?? { n: 0, off: 0, red: 0 };
    e.n++;
    if (u.status === "offline") e.off++;
    if (u.status === "reduced") e.red++;
    down.set(siteOf(u), e);
  }
  const sitesDown = [...down.entries()].filter(([, e]) => e.off + e.red > 0);
  const offSites = sitesDown
    .filter(([, e]) => e.off > 0)
    .sort((a, b) => b[1].off - a[1].off)
    .map(([s, e]) => `${s} ${e.off}/${e.n}`);
  const redSites = sitesDown
    .filter(([, e]) => e.off === 0)
    .map(([s, e]) => `${s} ${e.red}/${e.n}`);
  const siteLine = [
    offSites.length ? `${offSites.join(" · ")} offline` : "",
    redSites.length ? `${redSites.join(" · ")} reduced` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const divider =
    "pt-2 border-t border-[color-mix(in_srgb,var(--text-primary)_10%,transparent)]";
  return (
    <div className="rounded-xl px-3 py-2 space-y-2" style={GLASS_STYLE}>
      <div>
        <p className="flex items-baseline gap-2 whitespace-nowrap text-[10px] uppercase tracking-wide text-content-muted">
          <span>
            Spot price now{" "}
            <span className="normal-case tracking-normal text-content-faint">
              · {PRICE_UNIT}
            </span>
          </span>
          {onZoneClick && (
            <span className="ml-auto normal-case tracking-normal text-content-faint">
              hourly ›
            </span>
          )}
        </p>
        <div className="mt-1 -mx-1.5">
          {ZONES.map((z) => {
            const cur = prices?.[z]?.current_sek_kwh ?? null;
            const avg = prices?.[z]?.today_avg_sek_kwh ?? null;
            return (
              <button
                key={z}
                type="button"
                onClick={onZoneClick ? () => onZoneClick(z) : undefined}
                title={`${z} hourly prices`}
                onMouseEnter={onHoverZone ? () => onHoverZone(z) : undefined}
                onMouseLeave={onHoverZone ? () => onHoverZone(null) : undefined}
                onFocus={onHoverZone ? () => onHoverZone(z) : undefined}
                onBlur={onHoverZone ? () => onHoverZone(null) : undefined}
                className="group w-full flex items-center gap-1.5 rounded-md px-1.5 py-[3px] text-left outline-none transition-colors hover:bg-[color-mix(in_srgb,var(--text-primary)_8%,transparent)] focus-visible:ring-2 focus-visible:ring-sky-500"
                style={{
                  background:
                    hoverZone === z
                      ? "color-mix(in srgb, var(--text-primary) 8%, transparent)"
                      : undefined,
                }}
              >
                <span
                  className="inline-block w-2.5 h-2.5 rounded-[3px] shrink-0"
                  style={{
                    backgroundColor:
                      cur == null
                        ? "var(--surface-secondary)"
                        : scaleColor(Math.round(cur * 100), palette),
                  }}
                />
                <span className="text-xs font-semibold text-content-primary">
                  {z}
                </span>
                <span className="text-[10px] text-content-muted truncate flex-1 min-w-0">
                  {ZONE_CITY[z]}
                </span>
                <span className="w-3 text-center shrink-0">
                  <TrendArrow trend={trends?.[z] ?? null} />
                </span>
                <span className="text-sm font-semibold text-content-primary tabular-nums w-9 text-right">
                  {cur == null ? "—" : formatPrice(cur)}
                </span>
                <span className="text-[10px] text-content-muted tabular-nums w-14 text-right">
                  avg {avg == null ? "—" : formatPrice(avg)}
                </span>
                <span
                  aria-hidden="true"
                  className="w-2 shrink-0 text-center text-sm leading-none text-content-muted transition-[color,transform] group-hover:translate-x-0.5 group-hover:text-sky-500 group-focus-visible:translate-x-0.5 group-focus-visible:text-sky-500"
                >
                  ›
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {spread != null && (
        <div className={divider}>
          <p className="text-[10px] uppercase tracking-wide text-content-muted">
            North–south spread
          </p>
          <p className="text-sm font-semibold text-content-primary tabular-nums leading-tight">
            South pays {spread} öre more than north
          </p>
          <p className="text-[10px] text-content-muted">
            today avg, SE4 vs SE1
          </p>
        </div>
      )}
      {!outages && outagesError && (
        <div className={divider}>
          <p className="text-[10px] uppercase tracking-wide text-content-muted">
            Nuclear
          </p>
          <p className="text-[11px] text-content-muted">
            Reactor status unavailable right now
          </p>
        </div>
      )}
      {outages && (
        <div className={divider}>
          <p className="text-[10px] uppercase tracking-wide text-content-muted">
            Nuclear
          </p>
          <p className="text-sm font-semibold text-content-primary tabular-nums leading-tight">
            {offline > 0
              ? `${gw(offline)} GW of ${gw(total)} GW offline`
              : `All ${outages.nuclear.length} reactors running`}
          </p>
          {offline > 0 && (
            <div className="h-1 rounded-full bg-surface-tertiary mt-1.5 overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, (offline / (total || 1)) * 100)}%`,
                  backgroundColor: STATUS_COLOR.offline,
                }}
              />
            </div>
          )}
          {siteLine && (
            <p className="text-[10px] text-content-muted mt-1.5 leading-snug">
              {siteLine}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** A plant-layer marker: one unit, or several units sharing a position. */
interface MapPlant {
  key: string;
  xy: Pt;
  states: PlantState[];
  status: PlantStatus;
  cat: FuelCat;
  /** Total nominal capacity (MW): drives marker size and cluster priority. */
  mw: number;
  /** Unit names, for the accessible label. */
  names: string;
  details: Detail[];
}

const worstStatus = (list: PlantStatus[]): PlantStatus =>
  list.length > 0 && list.every((s) => s === "unknown")
    ? "unknown"
    : list.includes("offline")
      ? "offline"
      : list.includes("reduced")
        ? "reduced"
        : "running";
/** A cluster of one is the marker itself and keeps its plain key. */
const clusterId = (c: Cluster<MapPlant>) =>
  c.members.length > 1 ? `cluster:${c.seed.key}` : c.seed.key;

function mapPlant(key: string, xy: Pt, states: PlantState[]): MapPlant {
  const top = states.reduce((a, b) =>
    b.lostMw > a.lostMw || (b.lostMw === a.lostMw && b.unit.mw > a.unit.mw)
      ? b
      : a,
  );
  return {
    key,
    xy,
    states,
    status: groupStatus(states.map((s) => s.status)),
    cat: fuelCat(top.unit.psr),
    mw: states.reduce((t, s) => t + s.nominalMw, 0),
    names: states.map((s) => s.unit.name).join(", "),
    details: states.map(plantDetail),
  };
}

export function SwedenMap({
  prices,
  outages,
  onZoneClick,
  layout,
  trends,
  hoverZone,
  onHoverZone,
  outagesError,
}: SwedenMapProps) {
  const { resolvedTheme } = useTheme();
  // The server renders before the theme is known: stay on the dark palette until mounted
  // so the first client render matches the server HTML (no hydration mismatch).
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const themeKey = mounted && resolvedTheme === "light" ? "light" : "dark";
  const palette = useMemo(() => pricePalette(themeKey), [themeKey]);
  const stage = STAGE[themeKey];
  const zoneFill = (ore: number) => scaleColor(ore, palette);
  const zoneStroke = (ore: number) => {
    const { to, t } = ZONE_STROKE_MIX[themeKey];
    const target = hexToRgb(to);
    return rgbCss(
      scaleRgb(ore, palette).map((x, k) => Math.round(x + (target[k] - x) * t)),
    );
  };

  // Zone code tint: the zone's own hue, lightened (dark) / deepened (light) so it sits inside the area.
  const zoneLabel = (ore: number) => {
    const to = themeKey === "dark" ? [255, 255, 255] : [0, 0, 0];
    const t = themeKey === "dark" ? 0.6 : 0.45;
    return rgbCss(
      scaleRgb(ore, palette).map((x, k) => Math.round(x + (to[k] - x) * t)),
    );
  };

  // `?plants=dots` keeps the old dots-until-zoomed rendering for comparison. Read through an external store so SSR
  // and the first client render agree (null), then the real value arrives without a hydration warning.
  const dotsMode =
    useSyncExternalStore(
      (cb) => {
        window.addEventListener("popstate", cb);
        return () => window.removeEventListener("popstate", cb);
      },
      () => new URLSearchParams(window.location.search).get("plants"),
      () => null,
    ) === "dots";
  const modKey = useSyncExternalStore(
    () => () => {},
    () => (/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"),
    () => "Ctrl",
  );

  const wide = layout === "wide";
  const base = wide ? WIDE_VB : MOBILE_VB;
  const [, , bw, bh] = base;
  const boxRef = useRef<HTMLDivElement>(null);
  const measured = useElementWidth(boxRef);
  const boxWidth = measured || (wide ? 832 : 340);
  const boxHeight = (boxWidth * bh) / bw;
  // Marker hit areas (and the cluster radius) in CSS px; hit = radius - 2 so neighbours never touch
  const radiusPx = wide ? 30 : 32;

  const {
    view,
    zoom,
    dragging,
    wheelActive,
    wheelHint,
    canIn,
    canOut,
    zoomIn,
    zoomOut,
    reset,
    zoomTo,
    touchAction,
  } = useMapZoom({ boxRef, base });
  // Everything below is positioned from the *current* view, never the static frame
  const { x: vx, y: vy, w: vw, h: vh } = view;
  const k = vw / boxWidth; // viewBox units per CSS px
  const pctX = (x: number) => ((x - vx) / vw) * 100;
  const pctY = (y: number) => ((y - vy) / vh) * 100;
  /** True when a map point is within `margin` CSS px of the visible box. */
  const inBox = (p: Pt, margin = 24) => {
    const x = (pctX(p[0]) / 100) * boxWidth;
    const y = (pctY(p[1]) / 100) * boxHeight;
    return (
      x > -margin &&
      x < boxWidth + margin &&
      y > -margin &&
      y < boxHeight + margin
    );
  };

  const avgOre = (zone: Area): number | null => {
    const v = prices?.[zone]?.today_avg_sek_kwh;
    return v == null ? null : Math.round(v * 100);
  };

  // Group reactors by site, keeping API order
  // Every reactor is always drawn; the feed only supplies status (placeholder "unknown" until it loads)
  const bySite = useMemo(() => {
    const feed = new Map((outages?.nuclear ?? []).map((u) => [u.name, u]));
    const m = new Map<string, SiteUnit[]>();
    for (const r of NUCLEAR_UNITS) {
      const u: SiteUnit = feed.get(r.name) ?? {
        name: r.name,
        area: r.area,
        nominal_mw: r.mw,
        available_mw: r.mw,
        status: "unknown",
        outage: null,
      };
      const s = siteOf(u);
      m.set(s, [...(m.get(s) ?? []), u]);
    }
    return m;
  }, [outages]);
  const offlineCount = (outages?.nuclear ?? []).filter(
    (u) => u.status === "offline",
  ).length;
  const reducedCount = (outages?.nuclear ?? []).filter(
    (u) => u.status === "reduced",
  ).length;

  const se1 = avgOre("SE1");
  const se4 = avgOre("SE4");
  const spread = se1 != null && se4 != null ? se4 - se1 : null;
  const showSpread = spread != null && spread >= 50;

  // ── Plant layer: every plant in the map data, status from the outage feed (matched by EIC) ──
  const plants = useMemo(() => {
    const other = outages?.other ?? [];
    const byEic = outagesByEic(other);
    const known = outages != null;
    const list = PLANT_GROUPS.map((g) =>
      mapPlant(
        `plant:${g.key}`,
        g.xy,
        g.units.map((u) => plantState(u, byEic.get(u.eic), known)),
      ),
    );
    // Big outages the plant list does not know (feed names units differently): fall back to the name table
    for (const o of other) {
      if (lostMw(o) < LARGE_MW || !UNITS[o.name]) continue;
      if (o.resource_eic && PLANT_EICS.has(o.resource_eic)) continue;
      const unit: PlantUnit = {
        eic: o.resource_eic ?? o.name,
        name: o.name,
        psr: o.psr_type ?? "B20",
        area: o.area,
        mw: o.nominal_mw,
      };
      list.push(
        mapPlant(`unit:${o.area}:${o.resource_eic ?? o.name}`, UNITS[o.name], [
          plantState(unit, o),
        ]),
      );
    }
    // Nuclear sites are ordinary markers too (position from the site table, status from the reactors)
    for (const [site, units] of bySite) {
      const xy = SITES[site];
      if (!xy) continue;
      list.push({
        key: `nuclear:${site}`,
        xy,
        states: [],
        status: groupStatus(units.map((u) => u.status)),
        cat: "nuclear",
        mw: units.reduce((t, u) => t + u.nominal_mw, 0),
        names: site,
        details: [siteDetail(site, units)],
      });
    }
    // Cluster priority: biggest first, key as tie-break (independent of outage status, so nothing jumps on refresh)
    return list.sort(
      (a, b) => b.mw - a.mw || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0),
    );
  }, [outages, bySite]);

  // Clustering depends on zoom only (not pan), evaluated at the quantised zoom. floor, not round: the quantised
  // zoom must never exceed the real one, or on-screen spacing shrinks below radiusPx and hit areas overlap.
  const zoomStep = Math.floor(Math.log(zoom) * ZOOM_STEPS_PER_E);
  const clusters = useMemo(() => {
    const z = Math.min(MAX_ZOOM, Math.exp(zoomStep / ZOOM_STEPS_PER_E));
    return clusterMarkers(plants, bw / z / boxWidth, radiusPx);
  }, [plants, zoomStep, bw, boxWidth, radiusPx]);
  const markerDetails = useMemo(
    () =>
      new Map(
        clusters.map((c) => [
          clusterId(c),
          c.members.flatMap((m) => m.details),
        ]),
      ),
    [clusters],
  );
  /** A cluster is worth zooming into only while the members would actually separate at max zoom. */
  const canSplit = (c: Cluster<MapPlant>) =>
    c.members.length > 1 &&
    zoom < MAX_ZOOM - 0.01 &&
    clusterMarkers(c.members, bw / MAX_ZOOM / boxWidth, radiusPx).length > 1;
  const zoomToCluster = (c: Cluster<MapPlant>) => {
    const xs = c.members.map((m) => m.xy[0]);
    const ys = c.members.map((m) => m.xy[1]);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    // fit both extents in the view's aspect ratio, padded; always a real step in, never past max zoom
    const fit = 1.8 * Math.max(x1 - x0, ((y1 - y0) * bw) / bh);
    zoomTo(
      (x0 + x1) / 2,
      (y0 + y1) / 2,
      Math.max(bw / MAX_ZOOM, Math.min(fit, vw / 1.6)),
    );
  };

  // Outages the map cannot place (no plant match, no known position): still reachable from a list
  const unmappedOther = (outages?.other ?? []).filter(
    (o) =>
      lostMw(o) >= LARGE_MW &&
      !(o.resource_eic && PLANT_EICS.has(o.resource_eic)) &&
      !UNITS[o.name],
  );

  // ── Outage details: one popover, anchored inside the map on both layouts ──
  const details: Record<string, Detail> = {};
  for (const o of unmappedOther) details[otherId(o)] = otherDetail(o);
  // A cluster id that vanished after a zoom change resolves to nothing: the popover just renders empty
  const itemsOf = (id: string | null): Detail[] =>
    !id ? [] : details[id] ? [details[id]] : (markerDetails.get(id) ?? []);

  interface PopState {
    id: string;
    x: number;
    y: number;
    w: number;
    h: number;
    /** Map-unit centre of a marker trigger: the popover follows it through zoom/pan. */
    mx?: number;
    my?: number;
    pinned: boolean;
  }
  const [pop, setPop] = useState<PopState | null>(null);
  const closeTimer = useRef<number | undefined>(undefined);

  const anchorOf = (el: HTMLElement) => {
    const b = boxRef.current?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const a = {
      x: r.left - (b?.left ?? 0),
      y: r.top - (b?.top ?? 0),
      w: r.width,
      h: r.height,
    };
    if (!el.closest("[data-map-marker]")) return a;
    return {
      ...a,
      mx: vx + ((a.x + a.w / 2) / boxWidth) * vw,
      my: vy + ((a.y + a.h / 2) / boxHeight) * vh,
    };
  };
  const cancelClose = () => window.clearTimeout(closeTimer.current);
  const ctl: PopCtl = {
    openId: pop?.id ?? null,
    enter: (id, el) => {
      cancelClose();
      setPop((p) => ({
        id,
        ...anchorOf(el),
        pinned: p?.id === id ? p.pinned : false,
      }));
    },
    leave: () => {
      cancelClose();
      closeTimer.current = window.setTimeout(
        () => setPop((p) => (p && !p.pinned ? null : p)),
        150,
      );
    },
    toggle: (id, el) => {
      cancelClose();
      setPop((p) =>
        p?.id === id && p.pinned ? null : { id, ...anchorOf(el), pinned: true },
      );
    },
  };

  const anyOpen = pop != null;
  useEffect(() => {
    if (!anyOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPop(null);
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t?.closest("[data-map-popover],[data-popover-trigger]")) return;
      setPop(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [anyOpen]);

  // Hover/focus opens the popover (inert on touch), click pins it
  const popTrigger = (id: string) => ({
    "aria-expanded": pop?.id === id,
    "aria-controls": "map-popover",
    onMouseEnter: (e: { currentTarget: HTMLElement }) =>
      ctl.enter(id, e.currentTarget),
    onMouseLeave: () => ctl.leave(),
    onFocus: (e: { currentTarget: HTMLElement }) =>
      ctl.enter(id, e.currentTarget),
    onBlur: () => ctl.leave(),
    onClick: (e: { currentTarget: HTMLElement }) =>
      ctl.toggle(id, e.currentTarget),
  });

  // Popover placement inside the map box (follows its marker), flipped near the edges
  const popW = Math.min(250, boxWidth - 16);
  const popRect = (p: PopState) =>
    p.mx == null || p.my == null
      ? { x: p.x, y: p.y, w: p.w, h: p.h }
      : {
          x: ((p.mx - vx) / vw) * boxWidth - p.w / 2,
          y: ((p.my - vy) / vh) * boxHeight - p.h / 2,
          w: p.w,
          h: p.h,
        };
  const popStyle = (
    r: { x: number; y: number; w: number; h: number },
    n: number,
  ): CSSProperties => {
    const left = Math.max(
      8,
      Math.min(r.x + r.w / 2 - popW / 2, boxWidth - popW - 8),
    );
    const estH = 70 + 105 * n;
    const spaceBelow = boxHeight - (r.y + r.h) - 14;
    const spaceAbove = r.y - 14;
    // Below if it fits, else above if it fits, else the roomier side (the list then scrolls). A trigger outside the
    // box (the compact "Other outages" list sits under it) has no room below, so the popover hugs the bottom edge.
    const below =
      spaceBelow >= estH || (spaceAbove < estH && spaceBelow >= spaceAbove);
    const room = below ? spaceBelow : spaceAbove;
    const edge = (v: number) =>
      Math.max(8, Math.min(v, boxHeight - 8 - MIN_POP_H));
    return {
      left,
      ...(below
        ? { top: edge(r.y + r.h + 6) }
        : { bottom: edge(boxHeight - r.y + 6) }),
      maxHeight: Math.min(boxHeight - 16, Math.max(MIN_POP_H, room)),
      overflowY: "auto",
      overscrollBehavior: "contain",
    };
  };
  const popItems = itemsOf(pop?.id ?? null);
  const popAt = pop ? popRect(pop) : null;
  // A marker panned out of view takes its popover with it
  const popVisible =
    popAt != null &&
    (pop?.mx == null ||
      (popAt.x + popAt.w / 2 > 0 &&
        popAt.x + popAt.w / 2 < boxWidth &&
        popAt.y + popAt.h / 2 > 0 &&
        popAt.y + popAt.h / 2 < boxHeight));

  const ariaLabel = [
    "Map of Sweden's four electricity price zones, colored by today's average price.",
    ...ZONES.map((z) => {
      const o = avgOre(z);
      return `${z}: ${o == null ? "no data" : `${o} öre/kWh`}.`;
    }),
    showSpread ? `South pays ${spread} öre more than north.` : "",
    outages
      ? `Nuclear reactors: ${offlineCount} offline, ${reducedCount} reduced of ${outages.nuclear.length}.`
      : "",
  ]
    .filter(Boolean)
    .join(" ");

  const gradient = `linear-gradient(to right, ${palette
    .map(
      (c, k) =>
        `${c} ${Math.round((SCALE_STOPS[k] / SCALE_STOPS[SCALE_STOPS.length - 1]) * 100)}%`,
    )
    .join(", ")})`;
  // Badge radius in CSS px (glyph size is passed explicitly; r only seeds the default)
  const badgeR = wide ? 9 : 8;
  const legendCats: FuelCat[] = (
    Object.keys(FUEL_CAT_LABEL) as FuelCat[]
  ).filter(
    (c) =>
      c === "nuclear" ||
      PLANT_CATS.includes(c) ||
      plants.some((p) => p.cat === c),
  );
  // Markers sit on whole pixels (no half-pixel blur)
  const markerPos = (pos: Pt): CSSProperties => ({
    left: Math.round((pctX(pos[0]) / 100) * boxWidth),
    top: Math.round((pctY(pos[1]) / 100) * boxHeight),
  });
  // tolerance: animated zoom lands on 1.9999999 instead of 2
  const iconZoom = zoom >= ICON_ZOOM - 0.01;
  const line = { vectorEffect: "non-scaling-stroke" as const };

  // Cards sit above the plant layer: a marker panned under a card must not poke through it
  const glassPos = (style: CSSProperties): CSSProperties => ({
    position: "absolute",
    zIndex: 10,
    ...style,
  });

  return (
    <>
      <figure className={`m-0 ${wide ? "" : "max-w-[340px] mx-auto"}`}>
        <div
          ref={boxRef}
          className="relative w-full overflow-hidden rounded-xl select-none"
          style={{
            aspectRatio: `${bw} / ${bh}`,
            background: stage.sea,
            touchAction,
            cursor: zoom > 1.01 ? (dragging ? "grabbing" : "grab") : undefined,
          }}
        >
          <svg
            role="img"
            aria-label={ariaLabel}
            viewBox={`${vx} ${vy} ${vw} ${vh}`}
            className="absolute inset-0 w-full h-full"
            preserveAspectRatio="xMidYMid slice"
          >
            {/* Neighbouring land (+ Sweden's base outline under the zones) */}
            <path
              d={zoneMap.land}
              fill={stage.land}
              stroke={stage.landStroke}
              strokeWidth={1}
              strokeLinejoin="round"
              {...line}
            />
            <g
              fill={stage.countryLabel}
              fontSize={9 * k}
              letterSpacing={1.6 * k}
              textAnchor="middle"
              opacity={0.85}
              style={{ pointerEvents: "none" }}
            >
              {Object.entries(COUNTRY_LABELS)
                .filter(
                  ([name, [x, y]]) =>
                    (name === "NORWAY" ||
                      name === "FINLAND" ||
                      name === "RUSSIA") &&
                    x > vx + 30 * k &&
                    x < vx + vw - 30 * k &&
                    y > vy &&
                    y < vy + vh,
                )
                .map(([name, [x, y]]) => (
                  <text key={name} x={x} y={y}>
                    {name}
                  </text>
                ))}
            </g>

            {/* Zones: translucent vivid fill (detail shows through), then a glowing outline on top */}
            <defs>
              <filter
                id="zone-glow"
                x="-5%"
                y="-5%"
                width="110%"
                height="110%"
                colorInterpolationFilters="sRGB"
              >
                <feGaussianBlur stdDeviation={GLOW_PX * k} result="blur" />
                <feComponentTransfer in="blur" result="dim">
                  <feFuncA type="linear" slope={GLOW_OPACITY} />
                </feComponentTransfer>
                <feMerge>
                  <feMergeNode in="dim" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <g strokeLinejoin="round" fillRule="evenodd">
              {ZONES.map((z) => {
                const o = avgOre(z);
                const hot = hoverZone === z;
                return (
                  <path
                    key={z}
                    d={PATHS[z]}
                    fill={o == null ? "var(--surface-secondary)" : zoneFill(o)}
                    fillOpacity={
                      o == null
                        ? 0.6
                        : Math.min(
                            0.9,
                            scaleAlpha(o, ZONE_FILL[themeKey].alpha) +
                              (hot ? ZONE_FILL[themeKey].hoverBoost : 0),
                          )
                    }
                    {...line}
                    className="transition-[fill-opacity]"
                    onMouseEnter={
                      onHoverZone ? () => onHoverZone(z) : undefined
                    }
                    onMouseLeave={
                      onHoverZone ? () => onHoverZone(null) : undefined
                    }
                  >
                    <title>{`${z}${o == null ? "" : `: ${o} öre/kWh today (avg)`}`}</title>
                  </path>
                );
              })}
            </g>
            {/* Water above the zone fills: lakes cut back to the sea colour, the hydro rivers as hairlines */}
            <g style={{ pointerEvents: "none" }}>
              <path d={zoneMap.lakes} fill={stage.sea} fillRule="evenodd" />
              <path
                d={zoneMap.rivers}
                fill="none"
                stroke={stage.river}
                strokeWidth={1}
                strokeOpacity={0.75}
                strokeLinejoin="round"
                strokeLinecap="round"
                {...line}
              />
            </g>
            <g
              fill="none"
              strokeLinejoin="round"
              filter={themeKey === "dark" ? "url(#zone-glow)" : undefined}
              style={{ pointerEvents: "none" }}
            >
              {ZONES.map((z) => {
                const o = avgOre(z);
                const hot = hoverZone === z;
                return (
                  <path
                    key={z}
                    d={PATHS[z]}
                    stroke={o == null ? stage.landStroke : zoneStroke(o)}
                    strokeWidth={hot ? 2.4 : 1.4}
                    {...line}
                  />
                );
              })}
            </g>
          </svg>

          {/* ── Wide: glass cards over the map ── */}
          {wide && (
            <>
              <div
                data-map-ui
                style={glassPos({
                  left: "1.5%",
                  width: "34%",
                  maxWidth: 280,
                  top: "2.5%",
                })}
              >
                <SummaryCard
                  prices={prices}
                  trends={trends}
                  palette={palette}
                  hoverZone={hoverZone}
                  onZoneClick={onZoneClick}
                  onHoverZone={onHoverZone}
                  spread={showSpread ? spread : null}
                  outages={outages}
                  outagesError={outagesError}
                />
              </div>

              <div
                data-map-ui
                className="rounded-xl px-3 py-2 space-y-1.5"
                style={glassPos({
                  ...GLASS_STYLE,
                  right: "1.5%",
                  width: "25%",
                  minWidth: 176,
                  maxWidth: 210,
                  bottom: "2%",
                })}
              >
                <Legend
                  gradient={gradient}
                  cats={legendCats}
                  stacked
                  unknown={!outages}
                />
                <UnmappedOutages
                  items={unmappedOther}
                  error={outagesError}
                  onPick={(o, el) => ctl.toggle(otherId(o), el)}
                />
              </div>
            </>
          )}

          {/* ── Zoom controls ── */}
          <div
            data-map-ui
            className="absolute flex flex-col gap-1"
            style={{ right: 8, top: 8, zIndex: 20 }}
          >
            <ZoomButton label="Zoom in" disabled={!canIn} onClick={zoomIn}>
              +
            </ZoomButton>
            <ZoomButton label="Zoom out" disabled={!canOut} onClick={zoomOut}>
              −
            </ZoomButton>
            <ZoomButton label="Reset zoom" disabled={!canOut} onClick={reset}>
              <span className="text-[10px]">1×</span>
            </ZoomButton>
          </div>

          {/* ── Compact: spread + nuclear total badges ── */}
          {!wide && (showSpread || outages) && (
            <div
              data-map-ui
              className="flex flex-col items-start gap-1"
              style={glassPos({ left: "3%", top: "2%" })}
            >
              {showSpread && (
                <div
                  className="rounded-full px-2.5 py-1 text-[11px] font-medium text-content-primary tabular-nums whitespace-nowrap"
                  style={GLASS_STYLE}
                >
                  SE4 pays +{spread} öre vs SE1
                </div>
              )}
              {outages && (
                <div
                  className="rounded-full px-2.5 py-1 text-[11px] font-medium text-content-primary tabular-nums whitespace-nowrap"
                  style={GLASS_STYLE}
                >
                  {outages.nuclear_offline_mw > 0
                    ? `Nuclear ${gw(outages.nuclear_offline_mw)}/${gw(
                        outages.nuclear.reduce((t, u) => t + u.nominal_mw, 0),
                      )} GW off`
                    : `All ${outages.nuclear.length} reactors running`}
                </div>
              )}
            </div>
          )}
          {/* ── Plant layer: fuel glyph + status dot at every zoom (`?plants=dots`: dots until ICON_ZOOM) ── */}
          {clusters.map((c) => {
            const m = c.seed;
            if (!inBox(m.xy)) return null;
            const count = c.members.length;
            const id = clusterId(c);
            const split = canSplit(c);
            const status = worstStatus(c.members.map((x) => x.status));
            const glyph = !dotsMode || iconZoom;
            const showStatus = !dotsMode || iconZoom;
            const dotPx = wide ? 6 : 5;
            // Glyph px: base x gentle zoom growth x capacity of the seed (a cluster is drawn as its seed)
            const glyphPx = dotsMode
              ? 18
              : Math.round(
                  (wide ? 16 : 15) *
                    Math.min(1.25, 1 + (zoom - 1) * 0.05) *
                    sizeFactor(m.mw),
                );
            const statusPx = Math.max(5, Math.round(glyphPx * 0.38));
            const hit = radiusPx - 2;
            const off = c.members.filter((x) => x.status === "offline").length;
            const red = c.members.filter((x) => x.status === "reduced").length;
            const label =
              count > 1
                ? `${count} plants near ${m.names.split(", ")[0]}: ${
                    [off && `${off} offline`, red && `${red} reduced`]
                      .filter(Boolean)
                      .join(", ") ||
                    (status === "unknown" ? "status unknown" : "all available")
                  }, ${split ? "zoom in" : "details"}`
                : `${m.names}: ${status === "running" ? "available" : status === "unknown" ? "status unknown" : status}, details`;
            // Splittable clusters zoom in on click (no popover); everything else is an ordinary popover trigger
            const trigger = split
              ? {
                  onClick: () => {
                    cancelClose();
                    setPop(null);
                    zoomToCluster(c);
                  },
                }
              : popTrigger(id);
            return (
              <button
                key={id}
                type="button"
                data-popover-trigger
                data-map-marker
                {...trigger}
                aria-label={label}
                className="absolute flex items-center justify-center outline-none rounded-full focus-visible:ring-2 focus-visible:ring-sky-500"
                style={{
                  ...markerPos(m.xy),
                  width: hit,
                  height: hit,
                  transform: "translate(-50%, -50%)",
                }}
              >
                {glyph ? (
                  <span className="relative block">
                    <FuelBadgeIcon cat={m.cat} r={badgeR} size={glyphPx} />
                    {showStatus && (
                      <span
                        className="absolute block rounded-full"
                        style={{
                          width: dotsMode ? 6 : statusPx,
                          height: dotsMode ? 6 : statusPx,
                          right: dotsMode ? 0 : 1,
                          bottom: dotsMode ? 0 : 1,
                          backgroundColor: STATUS_COLOR[status],
                          boxShadow: "0 0 0 1px var(--surface-primary)",
                        }}
                      />
                    )}
                    {count > 1 && (
                      <span
                        className="absolute flex items-center justify-center rounded-full px-[3px] text-[9px] font-semibold leading-none tabular-nums text-content-primary"
                        style={{
                          top: -7,
                          right: -10,
                          minWidth: 13,
                          height: 13,
                          background: "var(--surface-primary)",
                          border:
                            "1px solid color-mix(in srgb, var(--text-primary) 25%, transparent)",
                        }}
                      >
                        {count}
                      </span>
                    )}
                  </span>
                ) : (
                  <span
                    className="block rounded-full"
                    style={{
                      width: dotPx,
                      height: dotPx,
                      backgroundColor: STATUS_COLOR[status],
                      boxShadow: "0 0 0 1px var(--surface-primary)",
                    }}
                  />
                )}
              </button>
            );
          })}

          {/* ── Zone code, above the plant layer (prices live in the summary card). Tinted with the zone hue, faint halo only ── */}
          <svg
            aria-hidden="true"
            viewBox={`${vx} ${vy} ${vw} ${vh}`}
            className="absolute inset-0 w-full h-full pointer-events-none"
            preserveAspectRatio="xMidYMid slice"
          >
            <g textAnchor="middle">
              {ZONES.map((z) => {
                const [x, y] = LABELS[z];
                const o = avgOre(z);
                return (
                  <text
                    key={z}
                    x={x}
                    y={y}
                    fontSize={14 * k}
                    fontWeight={600}
                    fill={o == null ? "var(--text-secondary)" : zoneLabel(o)}
                    fillOpacity={themeKey === "dark" ? 0.8 : 0.9}
                    stroke="var(--surface-primary)"
                    strokeWidth={1.5 * k}
                    strokeOpacity={0.25}
                    strokeLinejoin="round"
                    paintOrder="stroke"
                  >
                    {z}
                  </text>
                );
              })}
            </g>
          </svg>

          {/* ── Detail popover (one at a time, flips near edges, always inside the box) ── */}
          {pop && popAt && popVisible && popItems.length > 0 && (
            <div
              id="map-popover"
              data-map-popover
              data-map-ui
              role="dialog"
              aria-label={`${popItems[0].title}${popItems.length > 1 ? " and others" : ""} details`}
              onMouseEnter={() => cancelClose()}
              onMouseLeave={() => ctl.leave()}
              className="rounded-xl px-3 py-2.5"
              style={{
                ...GLASS_STYLE,
                background:
                  "color-mix(in srgb, var(--surface-primary) 94%, transparent)",
                position: "absolute",
                zIndex: 30,
                width: popW,
                ...popStyle(popAt, popItems.length),
              }}
            >
              {popItems.map((d, i) => (
                <div
                  key={d.id}
                  className={
                    i > 0
                      ? "mt-2 pt-2 border-t border-[color-mix(in_srgb,var(--text-primary)_10%,transparent)]"
                      : ""
                  }
                >
                  <DetailBody d={d} />
                </div>
              ))}
            </div>
          )}

          {/* Plain wheel scrolls the page until the map is clicked: say so when someone tries */}
          <div
            aria-hidden="true"
            className={`absolute left-1/2 -translate-x-1/2 rounded-full px-2.5 py-1 text-[10px] whitespace-nowrap text-content-muted pointer-events-none transition-opacity duration-200 ${wide ? "top-2" : "bottom-2"} ${wheelHint ? "opacity-100" : "opacity-0"}`}
            style={{ ...GLASS_STYLE, zIndex: 40 }}
          >
            Click map to zoom with scroll · {modKey}+scroll
          </div>
          <div
            aria-hidden="true"
            className="absolute inset-0 rounded-xl pointer-events-none transition-shadow"
            style={{
              zIndex: 40,
              boxShadow: wheelActive
                ? "inset 0 0 0 1px color-mix(in srgb, var(--text-primary) 22%, transparent)"
                : "none",
            }}
          />
        </div>

        {!wide && (
          <div className="mt-2 space-y-1">
            <Legend gradient={gradient} cats={legendCats} unknown={!outages} />
            <UnmappedOutages
              items={unmappedOther}
              error={outagesError}
              onPick={(o, el) => ctl.toggle(otherId(o), el)}
            />
          </div>
        )}
      </figure>
    </>
  );
}

function ZoomButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="w-8 h-8 rounded-lg flex items-center justify-center text-base leading-none font-medium text-content-primary outline-none focus-visible:ring-2 focus-visible:ring-sky-500 enabled:hover:bg-surface-tertiary disabled:opacity-40 disabled:cursor-default"
      style={GLASS_STYLE}
    >
      {children}
    </button>
  );
}

const LEGEND_STATUS: [PlantStatus, string][] = [
  ["running", "available"],
  ["reduced", "reduced"],
  ["offline", "offline"],
];

function Legend({
  gradient,
  cats,
  stacked,
  unknown,
}: {
  gradient: string;
  cats: FuelCat[];
  /** Status feed missing: the dots are grey, so the legend explains grey instead of the three states. */
  unknown?: boolean;
  /** Wide layout: gradient on top, then status and fuel lists side by side, one item per row. */
  stacked?: boolean;
}) {
  const bar = (
    <>
      <div
        className="h-1.5 rounded-full"
        style={{ background: gradient }}
        aria-hidden="true"
      />
      <div className="flex justify-between text-[10px] text-content-muted tabular-nums">
        <span>0 öre</span>
        <span>today avg</span>
        <span>300+</span>
      </div>
    </>
  );
  const statusItems = (
    unknown ? ([["unknown", "status unknown"]] as const) : LEGEND_STATUS
  ).map(([s, label]) => (
    <span key={s} className="inline-flex items-center gap-1">
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ backgroundColor: STATUS_COLOR[s] }}
      />
      {label}
    </span>
  ));
  const fuelItems = cats.map((c) => (
    <span key={c} className="inline-flex items-center gap-1">
      <FuelBadgeIcon cat={c} r={6} />
      {FUEL_CAT_LABEL[c]}
    </span>
  ));
  const markerNote = (
    <p
      className={`text-[10px] leading-snug text-content-muted ${stacked ? "" : "text-center"}`}
    >
      icon size = capacity · number = plants grouped
    </p>
  );
  if (stacked)
    return (
      <div className="space-y-1.5">
        <div className="space-y-1">{bar}</div>
        <div className="grid grid-cols-2 gap-x-3 pt-1 text-[10px] leading-4 text-content-muted">
          <div className="flex flex-col gap-1.5">{statusItems}</div>
          <div className="flex flex-col gap-1.5">{fuelItems}</div>
        </div>
        {markerNote}
      </div>
    );
  return (
    <div className="space-y-1">
      {bar}
      <div className="flex flex-wrap justify-center gap-x-2.5 gap-y-0.5 text-[10px] text-content-muted">
        {statusItems}
      </div>
      <div className="flex flex-wrap justify-center gap-x-2.5 gap-y-0.5 text-[10px] text-content-muted">
        {fuelItems}
      </div>
      {markerNote}
    </div>
  );
}

const ATTRIBUTION =
  "Zone borders approximate · Boundaries: SCB (CC0) · Natural Earth · Outages: ENTSO-E · Plants: ENTSO-E · Wikidata · © OpenStreetMap contributors";

/** Source line, rendered by the page directly below the map card (outside its border). */
export function MapAttribution({ layout }: { layout: "wide" | "compact" }) {
  return (
    <p
      className={
        layout === "wide"
          ? "mt-1.5 px-1 text-[9px] leading-snug text-content-faint"
          : "mt-1.5 px-1 text-[10px] text-content-faint text-center"
      }
    >
      {ATTRIBUTION}
    </p>
  );
}

/** Outages that have no map position (or all of them on a failed load): still reachable. */
function UnmappedOutages({
  items,
  error,
  onPick,
}: {
  items: OtherOutage[];
  error?: boolean;
  onPick: (o: OtherOutage, el: HTMLElement) => void;
}) {
  if (error)
    return (
      <p className="text-[10px] text-content-muted">
        Plant status unavailable right now.
      </p>
    );
  if (items.length === 0) return null;
  return (
    <p className="text-[10px] text-content-muted leading-snug">
      Other outages:{" "}
      {items.map((o, i) => (
        <span key={otherId(o)}>
          {i > 0 && " · "}
          <button
            type="button"
            data-popover-trigger
            onClick={(e) => onPick(o, e.currentTarget)}
            className="underline decoration-dotted underline-offset-2 hover:text-content-primary"
          >
            {o.name} −{lostMw(o)} MW
          </button>
        </span>
      ))}
    </p>
  );
}
