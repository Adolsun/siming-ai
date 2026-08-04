import { Alert, Button } from 'antd'
import { PersistentOutcome, RecoveryPanel } from '../interaction'

interface StageBlocker {
  stage: string
  label: string
}
export function StageFeedback({
  currentStage,
  status,
  hasData,
  staleReason,
  blockers,
  error,
  recommendedStageLabel,
  canRetryNext,
  onViewStage,
  onRetryNext,
}: {
  currentStage: string
  status?: string
  hasData: boolean
  staleReason?: string
  blockers: StageBlocker[]
  error?: string
  recommendedStageLabel: string
  canRetryNext: boolean
  onViewStage: (stage: string) => void
  onRetryNext: () => void
}) {
  return (
    <>
      {status === 'generated' && hasData && (
        <PersistentOutcome
          className="creation-stage-outcome"
          outcome="waiting_user"
          title={currentStage === 'final_review' ? '最终审阅已生成，等待你创建正式作品' : '生成完成，等待你确认'}
          description="内容已保存到立项草稿。你可以阅读、修改、确认，也可以先生成其他阶段。"
        />
      )}
      {status === 'stale' && (
        <PersistentOutcome
          className="creation-stage-outcome"
          outcome="blocked"
          title="上游内容已变化，本阶段需要重新校验"
          description={staleReason || '请检查内容后重新生成或编辑，再完成确认。'}
        />
      )}
      {status === 'pending' && blockers.length > 0 && (
        <Alert
          className="creation-stage-outcome"
          type="info"
          showIcon
          message={`先确认“${blockers[0].label}”`}
          description="只有真正缺少必要数据时才会阻止生成；其他阶段可以按任意顺序处理。"
          action={<Button onClick={() => onViewStage(blockers[0].stage)}>返回确认</Button>}
        />
      )}
      {error && (
        <RecoveryPanel
          title="下一步没有启动"
          description={error}
          retryLabel={`重试生成${recommendedStageLabel}`}
          onRetry={canRetryNext ? onRetryNext : undefined}
        />
      )}
    </>
  )
}
