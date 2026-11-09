/** Generation category shown as a small icon on the map. */
export type FuelCat =
  | "nuclear"
  | "fossil"
  | "hydro"
  | "wind"
  | "solar"
  | "bio"
  | "other";

export const FUEL_CAT_LABEL: Record<FuelCat, string> = {
  nuclear: "Nuclear",
  fossil: "Fossil",
  hydro: "Hydro",
  wind: "Wind",
  solar: "Solar",
  bio: "Bio / waste",
  other: "Other",
};

/** ENTSO-E psr_type -> category (null / unknown -> other). */
export function fuelCat(psr: string | null | undefined): FuelCat {
  switch (psr) {
    case "B14":
      return "nuclear";
    case "B02":
    case "B03":
    case "B04":
    case "B05":
    case "B06":
    case "B07":
    case "B08":
      return "fossil";
    case "B10":
    case "B11":
    case "B12":
      return "hydro";
    case "B18":
    case "B19":
      return "wind";
    case "B16":
      return "solar";
    case "B01":
    case "B17":
      return "bio";
    default:
      return "other";
  }
}

const PSR_NAME: Record<string, string> = {
  B01: "Biomass",
  B02: "Lignite",
  B03: "Coal-derived gas",
  B04: "Fossil gas",
  B05: "Hard coal",
  B06: "Fossil oil",
  B07: "Oil shale",
  B08: "Peat",
  B09: "Geothermal",
  B10: "Pumped storage hydro",
  B11: "Run-of-river hydro",
  B12: "Reservoir hydro",
  B13: "Marine",
  B14: "Nuclear",
  B15: "Other renewable",
  B16: "Solar",
  B17: "Waste",
  B18: "Offshore wind",
  B19: "Onshore wind",
  B20: "Other",
};

export function fuelName(psr: string | null | undefined): string {
  return (psr && PSR_NAME[psr]) || "Other";
}
