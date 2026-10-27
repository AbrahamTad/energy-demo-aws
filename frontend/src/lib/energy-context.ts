import { createContext, useContext } from "react";
import type { EnergyResponse } from "./energy";
export type EnergyState = {
  data: EnergyResponse | null;
  loading: boolean;
  error: string;
  fetchedAt: Date | null;
  refresh: () => void;
};
export const EnergyContext = createContext<EnergyState | null>(null);
export function useEnergy() {
  const context = useContext(EnergyContext);
  if (!context) throw new Error("EnergyProvider is required");
  return context;
}
