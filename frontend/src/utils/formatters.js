/**
 * Format a UTC ISO timestamp to CET/CEST local hour label, e.g. "14:00"
 * Sweden is UTC+1 (winter) / UTC+2 (summer).
 * Using 'Europe/Stockholm' locale for correct DST handling.
 */
export function toLocalHour(isoString) {
  return new Date(isoString).toLocaleTimeString('sv-SE', {
    timeZone: 'Europe/Stockholm',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/**
 * Current hour in CET, 0–23, for highlighting the active slot.
 */
export function currentCETHour() {
  const now = new Date()
  return parseInt(
    now.toLocaleString('sv-SE', {
      timeZone: 'Europe/Stockholm',
      hour: '2-digit',
      hour12: false,
    }),
    10,
  )
}

