export interface Cluster<T> {
  seed: T;
  /** Includes the seed, in the priority order of the input. */
  members: T[];
}

/**
 * Greedy screen-space clustering. `items` must already be sorted by priority (highest first): each item joins the
 * first cluster whose SEED is closer than `radiusPx`, else founds a new one. Because only seeds are compared,
 * seeds are always >= radiusPx apart, so hit areas of at most that size never overlap.
 */
export function clusterMarkers<T extends { key: string; xy: [number, number] }>(
  items: T[],
  unitsPerPx: number,
  radiusPx: number,
): Cluster<T>[] {
  const r = radiusPx * unitsPerPx;
  const r2 = r * r;
  const out: Cluster<T>[] = [];
  for (const it of items) {
    const home = out.find((c) => {
      const dx = c.seed.xy[0] - it.xy[0];
      const dy = c.seed.xy[1] - it.xy[1];
      return dx * dx + dy * dy < r2;
    });
    if (home) home.members.push(it);
    else out.push({ seed: it, members: [it] });
  }
  return out;
}
