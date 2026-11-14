export interface Cluster<T> {
  seed: T;
  /** Includes the seed, in the priority order of the input. */
  members: T[];
}

/**
 * Greedy screen-space clustering. `items` must already be sorted by priority (highest first): each item joins the
 * first cluster whose SEED is within `radiusPx` on both axes, else founds a new one. Distance is Chebyshev
 * (max of |dx|, |dy|), not Euclidean, because hit areas are squares: two squares of side s overlap iff both axis
 * gaps are < s, so seeds >= radiusPx apart on some axis guarantee square hit areas smaller than that never overlap.
 * (Euclidean spacing let diagonal neighbours' squares overlap by up to ~30%.)
 */
export function clusterMarkers<T extends { key: string; xy: [number, number] }>(
  items: T[],
  unitsPerPx: number,
  radiusPx: number,
): Cluster<T>[] {
  const r = radiusPx * unitsPerPx;
  const out: Cluster<T>[] = [];
  for (const it of items) {
    const home = out.find(
      (c) =>
        Math.abs(c.seed.xy[0] - it.xy[0]) < r &&
        Math.abs(c.seed.xy[1] - it.xy[1]) < r,
    );
    if (home) home.members.push(it);
    else out.push({ seed: it, members: [it] });
  }
  return out;
}
