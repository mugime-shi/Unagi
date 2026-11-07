"use client";

import { useStory } from "../hooks/useStory";

export function TodayStory() {
  const { data, loading, error } = useStory();

  // A missing story must never break the page.
  if (error) return null;

  if (!data) {
    return loading ? (
      <div className="bg-surface-primary rounded-2xl p-4 animate-pulse space-y-2">
        <div className="h-5 w-3/4 bg-surface-secondary rounded" />
        <div className="h-4 w-1/2 bg-surface-secondary rounded" />
      </div>
    ) : null;
  }

  const { headline, facts } = data;
  return (
    <div className="bg-surface-primary rounded-2xl p-4 space-y-2">
      <p className="text-base font-medium text-content-primary">
        {headline.text}
      </p>
      {headline.sub && (
        <p className="text-sm text-content-secondary">{headline.sub}</p>
      )}
      {facts.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {facts.map((f) => (
            <span
              key={f.kind}
              className="text-xs text-content-secondary bg-surface-secondary rounded-full px-3 py-1"
            >
              {f.text}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
