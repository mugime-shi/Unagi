import { createContext, useContext } from "react";

export interface RefreshState {
  key: number;
  lastUpdatedAt: Date;
  bump: () => void;
}

// Context + hook live apart from the provider component so fast refresh
// only has to deal with a components-only file (RefreshProvider.tsx).
export const RefreshContext = createContext<RefreshState>({
  key: 0,
  lastUpdatedAt: new Date(),
  bump: () => {},
});

export function useRefresh(): RefreshState {
  return useContext(RefreshContext);
}
