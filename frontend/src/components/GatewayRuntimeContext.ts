import { createContext, useContext } from 'react'

export interface GatewayRuntimeState {
  headless: boolean
}

export const GatewayRuntimeContext = createContext<GatewayRuntimeState>({ headless: false })

export function useGatewayRuntime() {
  return useContext(GatewayRuntimeContext)
}
