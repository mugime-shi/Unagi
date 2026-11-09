import type { CSSProperties } from "react";

/** Glassy overlay surface shared by every card placed on the map. */
export const GLASS_STYLE: CSSProperties = {
  background: "color-mix(in srgb, var(--surface-primary) 72%, transparent)",
  border: "1px solid color-mix(in srgb, var(--text-primary) 12%, transparent)",
  boxShadow: "0 8px 24px -10px rgba(0, 0, 0, 0.45)",
  backdropFilter: "blur(10px)",
  WebkitBackdropFilter: "blur(10px)",
};
