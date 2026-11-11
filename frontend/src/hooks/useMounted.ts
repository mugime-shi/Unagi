import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

// false during SSR and the hydration pass, true afterwards — avoids the
// setState-in-effect "mounted" flag while keeping hydration markup identical.
export function useMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
