import { createContext, useContext } from "react";

export const AppSurfaceOverlayRootContext = createContext<HTMLElement | null>(null);

export function useAppSurfaceOverlayRoot() {
  return useContext(AppSurfaceOverlayRootContext);
}
