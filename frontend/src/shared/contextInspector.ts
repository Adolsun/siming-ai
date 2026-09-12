export type TraceScope = {
  kind: 'project_conversation' | 'creation_session' | 'system_conversation' | 'operation'
  id: string
}

export interface ContextInspectorRequest { scope?: TraceScope; correlationId?: string }
export const CONTEXT_INSPECTOR_OPEN = 'siming:open-context-inspector'

export function openContextInspector(request: ContextInspectorRequest) {
  window.dispatchEvent(new CustomEvent(CONTEXT_INSPECTOR_OPEN, { detail: request }))
}
