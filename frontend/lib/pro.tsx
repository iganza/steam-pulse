"use client";

import { createContext, useContext } from "react";

const ProContext = createContext<boolean>(false);

export function ProProvider({
  isPro,
  children,
}: {
  isPro: boolean;
  children: React.ReactNode;
}) {
  return <ProContext.Provider value={isPro}>{children}</ProContext.Provider>;
}

export function usePro(): boolean {
  return useContext(ProContext);
}
