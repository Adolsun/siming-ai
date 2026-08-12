import { apiClient } from '../../api/client'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface CreationSessionSummary {
  id: string
  revision: number
  updated_at?: string | null
}

export interface CreationContext {
  revision: number
  constraints?: Record<string, unknown>
  creative_direction?: {
    selected_concept_id?: string | null
    selected?: Record<string, unknown>
  }
  world_style?: Record<string, unknown>
  artifact_statuses?: Record<string, string>
}

export interface CreationBriefResponse {
  session: CreationSessionSummary | null
  context: CreationContext | null
}

export interface CreationBriefUpdateResponse {
  project_id: string
  creation_session_id: string
  revision: number
  changed_artifacts: string[]
  creation: CreationContext
}

export function fetchCreationBrief(projectId: string) {
  return apiClient.get<ApiResponse<CreationBriefResponse>>(`/projects/${projectId}/creation-brief`)
}

export function ensureCreationBrief(projectId: string) {
  return apiClient.post<ApiResponse<CreationBriefResponse>>(`/projects/${projectId}/creation-brief/ensure`)
}

export function updateCreationBrief(projectId: string, payload: Record<string, unknown>) {
  return apiClient.patch<ApiResponse<CreationBriefUpdateResponse>>(
    `/projects/${projectId}/creation-brief`,
    payload,
  )
}
