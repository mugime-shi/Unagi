export function useIsMobile(breakpoint = 640) {
  if (typeof window === 'undefined') return false

  const width = window.innerWidth || 0
  return width < breakpoint
}

