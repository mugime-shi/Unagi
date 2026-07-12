"use client";

import type { ShapExplanations } from "../types/index";

/**
 * Plain-language read of the model's SHAP attribution for a forecast day.
 * The backend already returns human-readable group names (Wind, Demand,
 * "Gas & imports", …). We net each group's impact across the day and name the
 * biggest up/down contributors.
 *
 * Framed as *model attribution*, not measured causation — SHAP explains what
 * the model weighed, which is the honest claim for a transparency page.
 */
export function ShapNarrative({
  shap,
  dateLabel,
}: {
  shap?: ShapExplanations | null;
  dateLabel?: string;
}) {
  if (!shap?.hours?.length) return null;

  const net = new Map<string, number>();
  for (const h of shap.hours) {
    for (const f of h.top) net.set(f.group, (net.get(f.group) ?? 0) + f.impact);
  }
  const ranked = [...net.entries()].sort((a, b) => b[1] - a[1]);
  const up = ranked
    .filter(([, v]) => v > 0)
    .slice(0, 2)
    .map(([g]) => g);
  const down = ranked
    .filter(([, v]) => v < 0)
    .slice(-2)
    .reverse()
    .map(([g]) => g);

  if (up.length === 0 && down.length === 0) return null;

  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-sm font-medium text-content-primary mb-1">
        What the model weighed
        {dateLabel ? ` for ${dateLabel}` : ""}
      </h2>
      <p className="text-xs text-content-secondary leading-relaxed">
        {up.length > 0 && (
          <>
            Pushing prices{" "}
            <span className="font-medium text-rose-500 dark:text-rose-400">
              up
            </span>
            : {up.join(" and ")}.{" "}
          </>
        )}
        {down.length > 0 && (
          <>
            Holding them{" "}
            <span className="font-medium text-emerald-600 dark:text-emerald-400">
              down
            </span>
            : {down.join(" and ")}.
          </>
        )}
      </p>
      <p className="text-[11px] text-content-faint mt-1">
        Model attribution (SHAP) — what the forecast weighed, not measured
        causation.
      </p>
    </div>
  );
}
