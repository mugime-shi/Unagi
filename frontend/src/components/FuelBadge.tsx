import { type FuelCat } from "../utils/fuel";
import { PHOSPHOR_DUOTONE } from "../utils/phosphorIcons";

/** Marker glyph colour. */
const GLYPH_COLOR = "var(--text-primary)";

/**
 * Phosphor duotone glyph centred on (0,0), sized in px units (use inside an SVG
 * group scaled to CSS px). No badge: a surface-coloured halo keeps it legible
 * over the map.
 */
export function FuelBadgeShape({
  cat,
  r,
  size: sizeOverride,
}: {
  cat: FuelCat;
  r: number;
  size?: number;
}) {
  const icon = PHOSPHOR_DUOTONE[cat];
  const size = sizeOverride ?? (r >= 9 ? 22 : 19); // glyph px: wide / compact
  const sg = size / 256;
  // Halo hugs the outline only; wider halos fill the atom's inner gaps.
  const halo = 1.1;
  const tf = `scale(${sg}) translate(-128 -128)`;
  return (
    <g transform={tf} shapeRendering="geometricPrecision">
      <path
        d={icon.d}
        fill="var(--surface-primary)"
        stroke="var(--surface-primary)"
        strokeWidth={(2 * halo) / sg}
        strokeLinejoin="round"
      />
      {icon.tint && <path d={icon.tint} fill={GLYPH_COLOR} opacity={0.4} />}
      <path d={icon.d} fill={GLYPH_COLOR} />
    </g>
  );
}

/** Standalone inline icon for HTML contexts. */
export function FuelBadgeIcon({
  cat,
  r,
  size,
}: {
  cat: FuelCat;
  r: number;
  size?: number;
}) {
  const half = size ? size / 2 + 2.5 : r + 2.5;
  return (
    <svg
      width={half * 2}
      height={half * 2}
      viewBox={`${-half} ${-half} ${half * 2} ${half * 2}`}
      aria-hidden="true"
      className="block shrink-0 overflow-visible"
    >
      <FuelBadgeShape cat={cat} r={r} size={size} />
    </svg>
  );
}
