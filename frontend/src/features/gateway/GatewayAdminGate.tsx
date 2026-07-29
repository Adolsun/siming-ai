import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { Button, Input, Spin, Tag, Typography } from 'antd'
import {
  CloudServerOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { apiClient } from '../../api/client'
import { GatewayRuntimeContext, useGatewayRuntime } from '../../components/GatewayRuntimeContext'
import { getGatewayAdminSession, getGatewayStatus, loginGatewayAdmin } from './api'
import type { LauncherGatewaySettings } from './types'
import './GatewayAdminGate.css'

const { Text, Title } = Typography

interface Envelope<T> {
  code: number
  data: T
}

type GateState = 'checking' | 'open' | 'locked' | 'error'

export { useGatewayRuntime }

function GatewayAdminGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('checking')
  const [headless, setHeadless] = useState(false)
  const [bootstrapKey, setBootstrapKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const checkAccess = useCallback(async () => {
    setError('')
    try {
      const response = await apiClient.get<Envelope<LauncherGatewaySettings>>('/config/launcher')
      const isHeadless = Boolean(response.data.data.gateway_headless)
      setHeadless(isHeadless)
      if (!isHeadless) {
        setState('open')
        return
      }
      const session = await getGatewayAdminSession()
      setState(session.authenticated ? 'open' : 'locked')
    } catch (checkError) {
      setError(checkError instanceof Error ? checkError.message : '无法连接 Gateway')
      setState('error')
    }
  }, [])

  useEffect(() => {
    void checkAccess()
  }, [checkAccess])

  useEffect(() => {
    if (!headless) return undefined
    const requireLogin = () => setState('locked')
    window.addEventListener('siming:gateway-unauthorized', requireLogin)
    return () => window.removeEventListener('siming:gateway-unauthorized', requireLogin)
  }, [headless])

  const unlock = async () => {
    const key = bootstrapKey.trim()
    if (key.length < 12) return
    setBusy(true)
    setError('')
    try {
      await loginGatewayAdmin(key)
      await getGatewayStatus()
      setBootstrapKey('')
      setState('open')
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : '管理口令验证失败')
      setState('locked')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'open') {
    return (
      <GatewayRuntimeContext.Provider value={{ headless }}>
        {children}
      </GatewayRuntimeContext.Provider>
    )
  }

  if (state === 'checking') {
    return (
      <main className="gateway-gate gateway-gate-loading" aria-live="polite">
        <span className="gateway-gate-wordmark">司命</span>
        <Spin />
        <Text type="secondary">正在确认 Gateway 运行边界…</Text>
      </main>
    )
  }

  return (
    <main className="gateway-gate">
      <section className="gateway-gate-card" aria-labelledby="gateway-gate-title">
        <div className="gateway-gate-header">
          <span className="gateway-gate-seal" aria-hidden="true"><LockOutlined /></span>
          <div>
            <span className="gateway-gate-kicker">USER-OWNED GATEWAY</span>
            <Title id="gateway-gate-title" level={2}>解锁自己的创作中枢</Title>
            <Text>
              这里连接的是你部署的 Gateway，不是司命官方数据服务器。验证管理口令后，作品、设备与云端模型配置才会显示。
            </Text>
          </div>
        </div>

        {state === 'locked' ? (
          <div className="gateway-gate-form">
            <label htmlFor="gateway-bootstrap-key">Gateway 管理口令</label>
            <div className="gateway-gate-input-row">
              <Input.Password
                id="gateway-bootstrap-key"
                autoFocus
                autoComplete="off"
                value={bootstrapKey}
                prefix={<SafetyCertificateOutlined />}
                placeholder="SIMING_GATEWAY_BOOTSTRAP_KEY"
                onChange={(event) => setBootstrapKey(event.target.value)}
                onPressEnter={() => void unlock()}
              />
              <Button
                type="primary"
                icon={<LockOutlined />}
                loading={busy}
                disabled={bootstrapKey.trim().length < 12}
                onClick={() => void unlock()}
              >
                验证并进入
              </Button>
            </div>
            {error && <div className="gateway-gate-error" role="alert">{error}</div>}
            <Text type="secondary" className="gateway-gate-hint">
              口令只提交给当前 Gateway，不写入浏览器存储。忘记时请在部署设备上更新环境变量并重启容器。
            </Text>
          </div>
        ) : (
          <div className="gateway-gate-error gateway-gate-connect-error" role="alert">
            <b>暂时无法读取 Gateway 状态</b>
            <span>{error}</span>
            <Button icon={<SyncOutlined />} onClick={() => void checkAccess()}>重新连接</Button>
          </div>
        )}

        <div className="gateway-gate-boundary">
          <Tag icon={<CloudServerOutlined />}>运行在你的设备</Tag>
          <Tag icon={<SafetyCertificateOutlined />} color="success">HttpOnly 会话</Tag>
          <Tag icon={<SyncOutlined />} color="processing">离线副本可写</Tag>
        </div>
      </section>
    </main>
  )
}

export default GatewayAdminGate
