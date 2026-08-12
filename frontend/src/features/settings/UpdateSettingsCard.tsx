import {
  Alert,
  Button,
  Card,
  Descriptions,
  Radio,
  Space,
  Typography,
} from 'antd'
import {
  DownloadOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SaveOutlined,
} from '@ant-design/icons'

const { Paragraph, Text } = Typography

export type UpdateChannel = 'stable' | 'preview'

interface UpdateSignature {
  valid: boolean
  status: string
  subject?: string
  thumbprint?: string
}

interface UpdateMetadata {
  version: string
  channel: UpdateChannel
  source: string
  download_url: string
  sha256_available: boolean
}

interface StagedUpdate {
  version: string
  sha256: string
  signature?: UpdateSignature | null
  ready_to_install: boolean
  error?: string
}

export interface UpdateStatus {
  current_version: string
  update_channel: UpdateChannel
  update_available: boolean
  update?: UpdateMetadata | null
  staged_update?: StagedUpdate | null
  automatic_updates: boolean
  downloaded?: boolean
}

interface UpdateSettingsCardProps {
  updateChannel: UpdateChannel
  savedUpdateChannel?: UpdateChannel
  updateStatus: UpdateStatus | null
  launcherLoading: boolean
  checkingUpdate: boolean
  downloadingUpdate: boolean
  installingUpdate: boolean
  onChannelChange: (channel: UpdateChannel) => void
  onSaveChannel: () => void
  onCheck: () => void
  onDownload: () => void
  onInstall: () => void
}

export function UpdateSettingsCard({
  updateChannel,
  savedUpdateChannel,
  updateStatus,
  launcherLoading,
  checkingUpdate,
  downloadingUpdate,
  installingUpdate,
  onChannelChange,
  onSaveChannel,
  onCheck,
  onDownload,
  onInstall,
}: UpdateSettingsCardProps) {
  return (
    <Card className="settings-card" title={<span><SafetyCertificateOutlined /> 安全更新</span>}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Paragraph style={{ margin: 0 }}>
          司命不会在启动时自动检查、下载或替换程序。只有你点击下方按钮后，才会检查版本；下载后必须通过 SHA256 和 Windows 代码签名校验，才能安装。
        </Paragraph>
        <Radio.Group
          value={updateChannel}
          onChange={(event) => {
            onChannelChange(event.target.value)
          }}
        >
          <Space direction="vertical" size={8}>
            <Radio value="stable">
              <Text strong>稳定通道</Text>
              <Text type="secondary"> 只接收正式版本，适合日常创作。</Text>
            </Radio>
            <Radio value="preview">
              <Text strong>预览通道</Text>
              <Text type="secondary"> 可接收 alpha、beta 和 RC，用于参与 3.0 测试。</Text>
            </Radio>
          </Space>
        </Radio.Group>
        <Space wrap>
          <Button
            icon={<SaveOutlined />}
            aria-label="保存更新通道"
            loading={launcherLoading}
            disabled={savedUpdateChannel === updateChannel}
            onClick={onSaveChannel}
          >
            保存更新通道
          </Button>
          <Button aria-label="检查更新" icon={<ReloadOutlined />} loading={checkingUpdate} onClick={onCheck}>
            检查更新
          </Button>
          {updateStatus?.update_available && updateStatus.update && (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              aria-label={`下载并校验 ${updateStatus.update.version}`}
              loading={downloadingUpdate}
              disabled={!updateStatus.update.sha256_available}
              onClick={onDownload}
            >
              下载并校验 {updateStatus.update.version}
            </Button>
          )}
          {updateStatus?.staged_update?.ready_to_install && (
            <Button
              type="primary"
              icon={<SafetyCertificateOutlined />}
              aria-label="安装并重启"
              loading={installingUpdate}
              onClick={onInstall}
            >
              安装并重启
            </Button>
          )}
        </Space>
        {!updateStatus && (
          <Text type="secondary">尚未检查更新。不会有后台下载或静默安装。</Text>
        )}
        {updateStatus && !updateStatus.update_available && !updateStatus.staged_update && (
          <Text type="secondary">已检查：当前版本 {updateStatus.current_version} 暂无可验证更新。</Text>
        )}
        {updateStatus?.update_available && updateStatus.update && (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="可用版本">{updateStatus.update.version}</Descriptions.Item>
            <Descriptions.Item label="更新通道">
              {updateStatus.update.channel === 'preview' ? '预览通道' : '稳定通道'}
            </Descriptions.Item>
            <Descriptions.Item label="SHA256">
              {updateStatus.update.sha256_available ? '发布页提供，下载后会复核' : '发布页未提供，司命不会下载或安装'}
            </Descriptions.Item>
            <Descriptions.Item label="代码签名">下载后必须验证为可信签名</Descriptions.Item>
          </Descriptions>
        )}
        {updateStatus?.staged_update && (
          <Alert
            showIcon
            type={updateStatus.staged_update.ready_to_install ? 'success' : 'warning'}
            message={updateStatus.staged_update.ready_to_install ? '更新已验证，可以由你确认安装' : '已下载的更新需要重新校验'}
            description={updateStatus.staged_update.ready_to_install
              ? `版本 ${updateStatus.staged_update.version}，SHA256：${updateStatus.staged_update.sha256}`
              : updateStatus.staged_update.error || '请重新下载更新。'}
          />
        )}
      </Space>
    </Card>
  )
}
