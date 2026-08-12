import { apiClient } from '../../shared/api/client'
import type { ApiEnvelope } from '../../shared/api/contracts'

export interface GovernanceItem {
  id: string
  title?: string
  description?: string
  status: string
  importance?: string
  priority?: string
  cause?: string
  effect?: string
  strength?: number
  target_chapter_number?: number
  evidence?: string
  source_chapter_id?: string
  target_chapter_id?: string
  resolved_chapter_id?: string
  source_chapter_version?: number
  source_excerpt?: string
  source_char_start?: number
  source_char_end?: number
  source_locator_method?: string
  source_locator_confidence?: number
  resolved_chapter_version?: number
  resolution_note?: string
  resolution_evidence?: string
  verification_note?: string
  verified_at?: string
  last_checked_at?: string
  stale_reason?: string
  closed_by?: string
  recent_events?: GovernanceEvent[]
  created_at?: string
}

export interface GovernanceEvent {
  id: string
  from_status?: string
  to_status: string
  chapter_id?: string
  chapter_version?: number
  note?: string
  actor: string
  created_at?: string
}

export interface GovernanceStatusPayload {
  status: string
  target_chapter_id?: string
  target_chapter_number?: number
  resolved_chapter_id?: string
  evidence?: string
  resolution_note?: string
  resolution_evidence?: string
  verification_note?: string
  closed_by?: string
}

export interface ChapterGovernanceReview {
  id?: string | null
  chapter_id: string
  chapter_title: string
  chapter_version: number
  status: 'missing' | 'needs_review' | 'assessed' | 'verified' | 'stale'
  source?: string | null
  findings_count: number
  confidence?: number | null
  evidence?: string | null
  reviewed_at?: string | null
  previous_review_version?: number | null
}

export interface NarrativeCheckpoint {
  id: string
  sequence: number
  label: string
  trigger_type: string
  chapter_id?: string
  created_at?: string
  review_summary?: Record<string, unknown> | null
}

export interface NarrativeDashboard {
  foreshadowings: GovernanceItem[]
  causal_edges: GovernanceItem[]
  narrative_debts: GovernanceItem[]
  character_states: Array<Record<string, unknown>>
  quality_metrics: Array<Record<string, unknown>>
  chapter_reviews: ChapterGovernanceReview[]
  coverage: {
    total_chapters: number
    assessed_chapters: number
    verified_chapters: number
    gaps: number
  }
  checkpoints: NarrativeCheckpoint[]
  counts: {
    open_foreshadowings: number
    open_causal_edges: number
    open_debts: number
    high_risk?: number
    pending_review?: number
    stale?: number
    coverage_gaps?: number
  }
}

export async function getNarrativeDashboard(projectId: string, view: string) {
  const response = await apiClient.get<ApiEnvelope<NarrativeDashboard>>(
    `/projects/${projectId}/narrative-governance`,
    { view },
  )
  return response.data.data
}

export async function updateNarrativeStatus(
  projectId: string,
  type: string,
  id: string,
  payload: GovernanceStatusPayload,
) {
  const response = await apiClient.patch<ApiEnvelope<GovernanceItem>>(
    `/projects/${projectId}/narrative-governance/items/${type}/${id}`,
    payload,
  )
  return response.data.data
}

export async function verifyNarrativeReview(
  projectId: string,
  reviewId: string,
  evidence: string,
) {
  const response = await apiClient.post<ApiEnvelope<ChapterGovernanceReview>>(
    `/projects/${projectId}/narrative-governance/reviews/${reviewId}/verify`,
    { evidence },
  )
  return response.data.data
}

export async function getNarrativeCheckpointDiff(projectId: string, checkpointId: string) {
  const response = await apiClient.get<ApiEnvelope<Record<string, unknown>>>(
    `/projects/${projectId}/narrative-governance/checkpoints/${checkpointId}/diff`,
  )
  return response.data.data
}

export async function restoreNarrativeCheckpoint(projectId: string, checkpointId: string) {
  await apiClient.post(
    `/projects/${projectId}/narrative-governance/checkpoints/${checkpointId}/restore`,
    { confirmation: 'restore' },
  )
}
