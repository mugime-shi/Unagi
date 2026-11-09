// Shared time-bucketing for long-range charts: ≤30d daily, ≤90d weekly,
// ≤180d bi-weekly, otherwise monthly (30-day buckets).

export function bucketDaysFor(rangeDays: number): number {
  if (rangeDays <= 30) return 1;
  if (rangeDays <= 90) return 7;
  if (rangeDays <= 180) return 14;
  return 30;
}

export function granularityLabel(rangeDays: number): string {
  const b = bucketDaysFor(rangeDays);
  if (b === 1) return "daily";
  if (b === 7) return "weekly";
  if (b === 14) return "bi-weekly";
  return "monthly";
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Label for a bucket starting at ISO date: "Apr '25" (monthly) or "MM-DD". */
export function bucketLabel(isoDate: string, rangeDays: number): string {
  if (bucketDaysFor(rangeDays) >= 30) {
    const [y, m] = isoDate.split("-");
    return `${MONTHS[parseInt(m, 10) - 1]} '${y.slice(2)}`;
  }
  return isoDate.slice(5);
}

/**
 * Split date-sorted rows into consecutive buckets for the range. Daily ranges
 * return one single-row bucket per row.
 */
export function chunkByRange<T>(rows: T[], rangeDays: number): T[][] {
  const size = bucketDaysFor(rangeDays);
  const chunks: T[][] = [];
  for (let i = 0; i < rows.length; i += size) {
    chunks.push(rows.slice(i, i + size));
  }
  return chunks;
}

export function meanOf(values: (number | null | undefined)[]): number | null {
  const nums = values.filter((v): v is number => v != null);
  return nums.length ? nums.reduce((s, v) => s + v, 0) / nums.length : null;
}
