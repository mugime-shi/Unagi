import zoneMap from "../data/swedenZones.json";
import { fuelCat, type FuelCat } from "./fuel";
import type { OtherOutage } from "../types/index";

export type PlantStatus = "running" | "reduced" | "offline";
export type Pt = [number, number];

export interface PlantUnit {
  eic: string;
  name: string;
  psr: string;
  area: string;
  mw: number;
}

/** Units that share a map position collapse into one marker. */
export interface PlantGroup {
  key: string;
  xy: Pt;
  units: PlantUnit[];
}

/** Plant + its current outage (if any), as drawn. */
export interface PlantState {
  unit: PlantUnit;
  nominalMw: number;
  availableMw: number;
  outage: OtherOutage["outage"];
  status: PlantStatus;
  lostMw: number;
}

const RAW = zoneMap.plants as unknown as Record<
  string,
  { name: string; psr: string; area: string; mw: number; xy: Pt }
>;

// Integer viewBox units are ~1.7 km: closer than that the glyphs would sit on top of each other anyway
function buildGroups(): PlantGroup[] {
  const groups = new Map<string, PlantGroup>();
  for (const [eic, p] of Object.entries(RAW)) {
    const key = `${Math.round(p.xy[0])},${Math.round(p.xy[1])}`;
    const unit: PlantUnit = {
      eic,
      name: p.name,
      psr: p.psr,
      area: p.area,
      mw: p.mw,
    };
    const g = groups.get(key);
    if (g) g.units.push(unit);
    else groups.set(key, { key, xy: p.xy, units: [unit] });
  }
  return [...groups.values()];
}

export const PLANT_GROUPS: PlantGroup[] = buildGroups();
export const PLANT_EICS = new Set(Object.keys(RAW));

/** Fuel categories present in the plant layer. */
export const PLANT_CATS: FuelCat[] = Array.from(
  new Set(Object.values(RAW).map((p) => fuelCat(p.psr))),
);

/**
 * Status of a co-located group / nuclear site: offline only when EVERY unit is offline; any other partial
 * outage (some offline or reduced) is "reduced"; all available is "running".
 */
export const groupStatus = (list: PlantStatus[]): PlantStatus =>
  list.length > 0 && list.every((s) => s === "offline")
    ? "offline"
    : list.some((s) => s !== "running")
      ? "reduced"
      : "running";

/** Per-plant outage lookup by resource_eic; several outages on one unit keep the deepest. */
export function outagesByEic(other: OtherOutage[]): Map<string, OtherOutage> {
  const m = new Map<string, OtherOutage>();
  for (const o of other) {
    if (!o.resource_eic) continue;
    const prev = m.get(o.resource_eic);
    if (!prev || o.available_mw < prev.available_mw) m.set(o.resource_eic, o);
  }
  return m;
}

export function plantState(
  unit: PlantUnit,
  outage: OtherOutage | undefined,
): PlantState {
  const nominalMw = outage?.nominal_mw ?? unit.mw;
  const availableMw = outage?.available_mw ?? unit.mw;
  const status: PlantStatus = !outage
    ? "running"
    : availableMw <= 0
      ? "offline"
      : availableMw < nominalMw
        ? "reduced"
        : "running";
  return {
    unit,
    nominalMw,
    availableMw,
    outage: outage?.outage ?? null,
    status,
    lostMw: Math.max(0, Math.round(nominalMw - availableMw)),
  };
}
