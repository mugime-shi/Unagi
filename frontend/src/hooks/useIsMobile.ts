import { useState, useEffect } from "react";

export function useIsMobile(breakpoint: number = 640): boolean {
  // Start with a fixed value that matches the server render (desktop). Reading
  // window during the initial render would diverge from SSR on narrow screens
  // and trip a hydration mismatch — so the real value is set after mount.
  const [isMobile, setIsMobile] = useState<boolean>(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const update = (): void => setIsMobile(mql.matches);
    update(); // correct the value once mounted (client-only)
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [breakpoint]);

  return isMobile;
}
