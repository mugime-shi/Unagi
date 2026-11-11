import { useCallback, useMemo, useState, type ReactNode } from "react";
import { RefreshContext, type RefreshState } from "./useRefresh";

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ key: number; lastUpdatedAt: Date }>(
    () => ({ key: 0, lastUpdatedAt: new Date() }),
  );

  const bump = useCallback(() => {
    setState((prev) => ({ key: prev.key + 1, lastUpdatedAt: new Date() }));
  }, []);

  const value = useMemo<RefreshState>(
    () => ({ key: state.key, lastUpdatedAt: state.lastUpdatedAt, bump }),
    [state.key, state.lastUpdatedAt, bump],
  );

  return (
    <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>
  );
}
