import { createContext, useContext } from "react";
import type { Layout, ScreenName } from "./lib/layout";

export interface LayoutController {
  layout: Layout | null;
  editing: boolean;
  setScreen: (screen: ScreenName, items: Layout["screens"][ScreenName]) => void;
}

const LayoutContext = createContext<LayoutController | null>(null);

export const LayoutProvider = LayoutContext.Provider;

export function useLayout(): LayoutController | null {
  return useContext(LayoutContext);
}
