import { createContext, useContext, type ReactNode } from 'react';

const FeeManagement = createContext(false);
export function FeeVisibility({ enabled, children }: { enabled: boolean; children?: ReactNode }) {
  return <FeeManagement.Provider value={enabled}>{children}</FeeManagement.Provider>;
}
export const useFeeManagement = () => useContext(FeeManagement);
