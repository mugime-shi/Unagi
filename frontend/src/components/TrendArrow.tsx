export function TrendArrow({ trend }: { trend: "up" | "down" | null }) {
  if (!trend) return null;
  const up = trend === "up";
  return (
    <span
      className={`text-xs ${up ? "text-rose-500 dark:text-rose-400" : "text-emerald-600 dark:text-emerald-400"}`}
      title={
        up
          ? "Heading up over the next few hours (day-ahead)"
          : "Heading down over the next few hours (day-ahead)"
      }
      aria-label={up ? "price rising" : "price falling"}
    >
      {up ? "▲" : "▼"}
    </span>
  );
}
