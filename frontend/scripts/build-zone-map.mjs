#!/usr/bin/env node
/**
 * Build frontend/src/data/swedenZones.json: the four Swedish bidding zones (SE1-SE4) as SVG paths.
 *
 * Rerun (from frontend/):   node scripts/build-zone-map.mjs
 * Needs: node >= 20, `unzip`, network access on first run (the SCB zip is cached in the OS temp dir;
 *        mapshaper is fetched via `npx`, pinned below, nothing is added to package.json).
 *
 * Pipeline: SCB municipality boundaries (SWEREF 99 TM, CC0) -> join kommun_elomrade.csv -> dissolve to 4 zones
 * -> simplify -> scale/flip the SWEREF 99 TM metres into an SVG viewBox (no reprojection: SWEREF 99 TM is a fine
 * projection for Sweden). Plant coordinates (WGS84, Wikidata, CC0) are converted to SWEREF 99 TM here.
 * Zone borders follow municipality borders, so they are approximate where a municipality straddles two zones.
 * Neighbouring land (Norway, Finland, Denmark, Baltics, ...) comes from Natural Earth admin-0 1:50m (public domain),
 * projected to SWEREF 99 TM and clipped to the map frame; Sweden's own Natural Earth outline is included as a base
 * layer under the zones so no sea-coloured slivers show through.
 * Boundaries: SCB (CC0) + Natural Earth (public domain). Do not commit the raw zips.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "../src/data/swedenZones.json");
const CSV = join(HERE, "data/kommun_elomrade.csv");
const NE_ZIP =
  "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip";
const SCB_ZIP =
  "https://www.scb.se/contentassets/3443fea3fa6640f7a57ea15d9a372d33/shape_svenska_260225.zip";
const MAPSHAPER = "mapshaper@0.7.101";

// Map frame in SWEREF 99 TM metres (roughly lon 1-37E, lat 54-70N), aspect 1.17. Sweden sits in the middle third.
const FRAME = { e0: -428000, e1: 1608000, n0: 6020000, n1: 7760000 };
// Tighter portrait crop around Sweden for phones (same data, different viewBox)
const MOBILE_CROP = { e0: 40000, e1: 957000, n0: 6070000, n1: 7720000 };
const VIEW_H = 1000; // viewBox height; width follows the frame aspect ratio
const LAND_COUNTRIES = [
  "Norway",
  "Finland",
  "Denmark",
  "Germany",
  "Poland",
  "Russia",
  "Estonia",
  "Latvia",
  "Lithuania",
  "Sweden",
];
// Intervals are tuned for 6x map zoom; SCB and Natural Earth 1:50m are already generalised, so going below ~100 m gains nothing.
const LAND_SIMPLIFY_M = Number(process.env.LAND_SIMPLIFY_M ?? 300);
// Tiny country labels: [lat, lon]
const COUNTRY_LABELS = {
  NORWAY: [63.3, 8.2],
  FINLAND: [63.8, 27.2],
  DENMARK: [55.9, 9.3],
  RUSSIA: [61.5, 33.5],
  ESTONIA: [58.9, 25.6],
  POLAND: [53.9, 19],
  GERMANY: [54.0, 10.5],
};
const SIMPLIFY_INTERVAL_M = Number(process.env.SIMPLIFY_INTERVAL_M ?? 100); // visvalingam effective-area interval, metres
const MIN_ISLAND_KM2 = 150; // drops archipelago specks, keeps Gotland, Oland, Orust
const ZONES = ["SE1", "SE2", "SE3", "SE4"];

// Nuclear sites: Wikidata (CC0). [lat N, lon E]
const SITES = {
  Forsmark: { q: "Q1575435", ll: [60.40333, 18.16667] },
  Ringhals: { q: "Q205774", ll: [57.26111, 12.10833] },
  Oskarshamn: { q: "Q1539046", ll: [57.41556, 16.67111] },
};

// Non-nuclear units with >= 300 MW outages in generation_outages (resource_name as ENTSO-E reports it).
// Wikidata (CC0) coordinates. Units not listed here are simply not drawn on the map.
const UNITS = {
  Harsprånget: { q: "Q3127967", ll: [66.885833, 19.815833] },
  Karlshamn: { q: "Q289958", ll: [56.152222, 14.8325] }, // Karlshamnsverket
  Letsi: { q: "Q10559896", ll: [66.5041, 20.3826] },
  Ligga: { q: "Q10561514", ll: [66.809167, 19.896667] },
  Porjus: { q: "Q2944573", ll: [66.961944, 19.804167] },
  Ritsem: { q: "Q10655892", ll: [67.72, 17.472778] },
  Stornorrfors: { q: "Q3499873", ll: [63.8525, 20.051667] },
  Vietas: { q: "Q19398054", ll: [67.493111, 18.354556] },
  "Öresundsverket CHP": { q: "Q10727554", ll: [55.626111, 13.040444] }, // Malmö
};

/** WGS84 -> SWEREF 99 TM (EPSG:3006), Kruger series (GRS80, k0 0.9996, lon0 15E, FE 500000). */
function toSweref(lat, lon) {
  const a = 6378137;
  const f = 1 / 298.257222101;
  const k0 = 0.9996;
  const n = f / (2 - f);
  const A = (a / (1 + n)) * (1 + n ** 2 / 4 + n ** 4 / 64);
  const alpha = [
    n / 2 - (2 * n ** 2) / 3 + (5 * n ** 3) / 16,
    (13 * n ** 2) / 48 - (3 * n ** 3) / 5,
    (61 * n ** 3) / 240,
  ];
  const rad = Math.PI / 180;
  const phi = lat * rad;
  const dl = (lon - 15) * rad;
  const c = (2 * Math.sqrt(n)) / (1 + n);
  const t = Math.sinh(
    Math.atanh(Math.sin(phi)) - c * Math.atanh(c * Math.sin(phi)),
  );
  const xi = Math.atan2(t, Math.cos(dl));
  const eta = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
  let N = xi;
  let E = eta;
  alpha.forEach((al, i) => {
    const j = 2 * (i + 1);
    N += al * Math.sin(j * xi) * Math.cosh(j * eta);
    E += al * Math.cos(j * xi) * Math.sinh(j * eta);
  });
  return [500000 + k0 * A * E, k0 * A * N];
}

function run(cmd, args) {
  return execFileSync(cmd, args, { stdio: ["ignore", "pipe", "inherit"] });
}

function download(url, dest) {
  if (existsSync(dest)) return;
  console.log(`downloading ${url}`);
  run("curl", ["-fsSL", "-o", dest, url]);
}

// ── geometry helpers (SWEREF metres) ──
const ringArea = (r) => {
  let s = 0;
  for (let i = 0; i < r.length - 1; i++)
    s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1];
  return s / 2;
};

function inRing(x, y, r) {
  let inside = false;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const [xi, yi] = r[i];
    const [xj, yj] = r[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

function distToRing(x, y, r) {
  let best = Infinity;
  for (let i = 0; i < r.length - 1; i++) {
    const [ax, ay] = r[i];
    const [bx, by] = r[i + 1];
    const dx = bx - ax;
    const dy = by - ay;
    const l2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2));
    best = Math.min(best, Math.hypot(x - ax - t * dx, y - ay - t * dy));
  }
  return best;
}

/** Point deepest inside the largest polygon (coarse grid search). */
function labelPoint(polys) {
  const poly = polys.reduce((a, b) =>
    ringArea(a[0]) > ringArea(b[0]) ? a : b,
  );
  const xs = poly[0].map((p) => p[0]);
  const ys = poly[0].map((p) => p[1]);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  let best = { d: -1, p: [0, 0] };
  const steps = 120;
  for (let i = 0; i <= steps; i++) {
    for (let j = 0; j <= steps; j++) {
      const x = x0 + ((x1 - x0) * i) / steps;
      const y = y0 + ((y1 - y0) * j) / steps;
      if (!inRing(x, y, poly[0]) || poly.slice(1).some((h) => inRing(x, y, h)))
        continue;
      const d = Math.min(...poly.map((r) => distToRing(x, y, r)));
      if (d > best.d) best = { d, p: [x, y] };
    }
  }
  return best.p;
}

// ── main ──
const work = join(tmpdir(), "unagi-zone-map");
mkdirSync(work, { recursive: true });
const outer = join(work, "scb.zip");
download(SCB_ZIP, outer);
run("unzip", ["-oq", outer, "Kommun_Sweref99TM.zip", "-d", work]);
run("unzip", ["-oq", join(work, "Kommun_Sweref99TM.zip"), "-d", work]);

// mapshaper's CSV reader has no comment support: strip the header comment
const csvClean = join(work, "kommun_elomrade.clean.csv");
writeFileSync(
  csvClean,
  readFileSync(CSV, "utf8")
    .split("\n")
    .filter((l) => !l.startsWith("#"))
    .join("\n"),
);

const zonesGeo = join(work, "zones.json");
run("npx", [
  "--yes",
  MAPSHAPER,
  join(work, "Kommun_Sweref99TM.shp"),
  "encoding=latin1",
  "-join",
  csvClean,
  "keys=KnKod,kommun_code",
  "string-fields=kommun_code,zone",
  "-dissolve",
  "zone",
  "-filter-islands",
  `min-area=${MIN_ISLAND_KM2}km2`,
  "remove-empty",
  "-simplify",
  "visvalingam",
  `interval=${SIMPLIFY_INTERVAL_M}`,
  "keep-shapes",
  "-o",
  zonesGeo,
  "format=geojson",
  "force",
]);

const features = JSON.parse(readFileSync(zonesGeo, "utf8")).features;
const polysByZone = {};
for (const f of features) {
  const z = f.properties.zone;
  if (!ZONES.includes(z)) throw new Error(`unexpected zone ${z}`);
  polysByZone[z] =
    f.geometry.type === "Polygon"
      ? [f.geometry.coordinates]
      : f.geometry.coordinates;
}
for (const z of ZONES) if (!polysByZone[z]) throw new Error(`missing ${z}`);

const minE = FRAME.e0;
const maxN = FRAME.n1;
const scale = VIEW_H / (FRAME.n1 - FRAME.n0);
const VIEW_W = Math.round((FRAME.e1 - FRAME.e0) * scale);
const px = ([e, n]) => [(e - minE) * scale, (maxN - n) * scale];
const toView = (e, n) => px([e, n]).map(Math.round);

// Coordinates snap to 0.1 viewBox units (~170 m): integer units are ~1.7 km and show as facets at 6x zoom.
const tenth = (v) => String(v / 10);
function pathD(polys) {
  const parts = [];
  for (const poly of polys) {
    for (const ring of poly) {
      const q = ring
        .slice(0, -1)
        .map(px)
        .map(([x, y]) => [Math.round(x * 10), Math.round(y * 10)]);
      // relative deltas in tenths; drop zero-length steps
      let d = `M${tenth(q[0][0])} ${tenth(q[0][1])}l`;
      const deltas = [];
      for (let i = 1; i < q.length; i++) {
        const dx = q[i][0] - q[i - 1][0];
        const dy = q[i][1] - q[i - 1][1];
        if (dx || dy) deltas.push(`${tenth(dx)} ${tenth(dy)}`);
      }
      d += deltas.join(" ").replace(/ -/g, "-") + "z";
      parts.push(d);
    }
  }
  return parts.join("");
}

// ── neighbouring land (Natural Earth) ──
const neZip = join(work, "ne_admin0.zip");
download(NE_ZIP, neZip);
const neDir = join(work, "ne");
mkdirSync(neDir, { recursive: true });
run("unzip", ["-oq", neZip, "-d", neDir]);
const landGeo = join(work, "land.json");
const names = LAND_COUNTRIES.map((n) => `'${n}'`).join(",");
run("npx", [
  "--yes",
  MAPSHAPER,
  join(neDir, "ne_50m_admin_0_countries.shp"),
  "-filter",
  `[${names}].includes(NAME)`,
  "-clip",
  "bbox=-5,50,45,72", // lon/lat, before projecting: keeps far-away territories out of the transform
  "-proj",
  "+init=epsg:3006",
  "-clip",
  `bbox=${FRAME.e0},${FRAME.n0},${FRAME.e1},${FRAME.n1}`,
  "-filter-islands",
  "min-area=300km2",
  "remove-empty",
  "-simplify",
  "visvalingam",
  `interval=${LAND_SIMPLIFY_M}`,
  "keep-shapes",
  "-o",
  landGeo,
  "format=geojson",
  "force",
]);
const landPolys = JSON.parse(readFileSync(landGeo, "utf8")).features.flatMap(
  (f) =>
    f.geometry.type === "Polygon"
      ? [f.geometry.coordinates]
      : f.geometry.coordinates,
);
const land = pathD(landPolys);
const countryLabels = Object.fromEntries(
  Object.entries(COUNTRY_LABELS).map(([k, ll]) => [
    k,
    toView(...toSweref(...ll)),
  ]),
);

const mobileViewBox = [
  ...toView(MOBILE_CROP.e0, MOBILE_CROP.n1),
  Math.round((MOBILE_CROP.e1 - MOBILE_CROP.e0) * scale),
  Math.round((MOBILE_CROP.n1 - MOBILE_CROP.n0) * scale),
];

const round1 = (v) => Math.round(v * 10) / 10;
const place = (ll) => px(toSweref(...ll)).map(round1);

const zones = {};
const labelPoints = {};
for (const z of ZONES) {
  zones[z] = pathD(polysByZone[z]);
  labelPoints[z] = px(labelPoint(polysByZone[z])).map(Math.round);
}
const sites = Object.fromEntries(
  Object.entries(SITES).map(([k, v]) => [k, place(v.ll)]),
);
const units = Object.fromEntries(
  Object.entries(UNITS).map(([k, v]) => [k, place(v.ll)]),
);

// Production units >= 100 MW (scripts/plants.json), keyed by ENTSO-E EIC so outages can be matched by resource_eic
const plantList = JSON.parse(
  readFileSync(join(HERE, "plants.json"), "utf8"),
).plants;
const plants = Object.fromEntries(
  plantList.map((p) => [
    p.eic,
    { name: p.name, psr: p.psr, area: p.area, mw: p.mw, xy: place(p.ll) },
  ]),
);

const out = {
  viewBox: `0 0 ${VIEW_W} ${VIEW_H}`,
  width: VIEW_W,
  height: VIEW_H,
  mobileViewBox, // [x, y, w, h] portrait crop around Sweden
  land,
  countryLabels,
  zones,
  labelPoints,
  sites,
  units,
  plants,
};
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(out) + "\n");
const bytes = Object.values(zones).reduce((s, d) => s + d.length, 0);
console.log(
  `wrote ${OUT}: zone path ${bytes} B, land path ${land.length} B, viewBox ${out.viewBox}, mobile ${mobileViewBox}`,
);
