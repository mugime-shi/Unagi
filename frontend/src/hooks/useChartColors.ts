"use client";

import { useTheme } from "next-themes";
import { useMemo } from "react";

/**
 * Recharts は SVG attributes (stroke/fill) を文字列として扱うため CSS 変数を直接渡せない。
 * このフックは resolved theme に応じて hex オブジェクトを返す。
 */

export interface ChartColors {
  grid: string;
  axis: string;
  axisDim: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  daLine: string;
  daFill: string;
  nowDotRing: string;
  avgLine: string;
  imbShort: string;
  imbLong: string;
  hydro: string;
  wind: string;
  nuclear: string;
  solar: string;
  other: string;
  SE1: string;
  SE2: string;
  SE3: string;
  SE4: string;
  lgbm: string;
  weekdayAvg: string;
  fallback: string;
  // Cost floor
  costSpot: string;
  costElnat: string;
  costSkatt: string;
  costMoms: string;
}

const DARK: ChartColors = {
  // Axis & grid
  grid: "#374151", // gray-700
  axis: "#9ca3af", // gray-400
  axisDim: "#6b7280", // gray-500

  // Tooltip
  tooltipBg: "#122240", // sea-800
  tooltipBorder: "#1a3058", // sea-700
  tooltipText: "#cbd5e1", // slate-300

  // Day-ahead / spot
  daLine: "#60a5fa", // blue-400
  daFill: "#60a5fa",
  nowDotRing: "#0f172a", // slate-900

  // Reference & baseline
  avgLine: "#6b7280",

  // Imbalance
  imbShort: "#f97316", // orange-500
  imbLong: "#2dd4bf", // teal-400

  // Generation mix
  hydro: "#3b82f6", // blue-500
  wind: "#22d3ee", // cyan-400
  nuclear: "#eab308", // yellow-500
  solar: "#f97316", // orange-500
  other: "#6b7280", // gray-500

  // Zones
  SE1: "#60a5fa",
  SE2: "#34d399",
  SE3: "#fbbf24",
  SE4: "#f87171",

  // Models
  lgbm: "#fbbf24", // amber-400
  weekdayAvg: "#94a3b8", // slate-400
  fallback: "#6366f1", // indigo-500
  // Cost floor — bar-friendly (~70% saturation of Unagi palette)
  costSpot: "#5b8ec9", // blue — daLine family, toned for bars
  costElnat: "#2d8f9d", // teal — ocean depth
  costSkatt: "#c49630", // amber — brand accent, controlled
  costMoms: "#55627a", // slate blue — neutral
};

const LIGHT: ChartColors = {
  // Axis & grid
  grid: "#e5e7eb", // gray-200
  axis: "#6b7280", // gray-500
  axisDim: "#9ca3af", // gray-400

  // Tooltip
  tooltipBg: "#ffffff",
  tooltipBorder: "#cbd5e1", // slate-300
  tooltipText: "#1f2937", // gray-800

  // Day-ahead / spot
  daLine: "#2563eb", // blue-600
  daFill: "#3b82f6", // blue-500
  nowDotRing: "#ffffff",

  // Reference & baseline
  avgLine: "#9ca3af",

  // Imbalance
  imbShort: "#ea580c", // orange-600
  imbLong: "#0d9488", // teal-600

  // Generation mix
  hydro: "#2563eb", // blue-600
  wind: "#0891b2", // cyan-600
  nuclear: "#ca8a04", // yellow-600
  solar: "#ea580c", // orange-600
  other: "#6b7280",

  // Zones
  SE1: "#2563eb",
  SE2: "#059669",
  SE3: "#d97706",
  SE4: "#dc2626",

  // Models
  lgbm: "#d97706", // amber-600
  weekdayAvg: "#64748b", // slate-500
  fallback: "#4f46e5", // indigo-600
  // Cost floor — bar-friendly (light mode, brighter for white bg)
  costSpot: "#4a8fd0", // medium blue — visible on white
  costElnat: "#2a9aaa", // medium teal — clear on white
  costSkatt: "#c49630", // warm amber — same warmth as dark
  costMoms: "#8895a8", // light slate — neutral but readable
};

export function useChartColors(): ChartColors {
  const { resolvedTheme } = useTheme();
  return useMemo(
    () => (resolvedTheme === "light" ? LIGHT : DARK),
    [resolvedTheme],
  );
}
