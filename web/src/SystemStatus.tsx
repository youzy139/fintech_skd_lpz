import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

type Check = { name: string; status: 'ok' | 'disabled' | 'unavailable'; latency_ms: number | null; probe?: string; error_type?: string }
type Circuit = { state: 'closed' | 'open' | 'half_open'; consecutive_failures: number; short_circuits: number; recovery_timeout_seconds: number }
type Report = {
  status: 'ok' | 'degraded'
  generated_at: string
  checks: Check[]
  governance: { mode: string; circuit: Circuit }
  catalog_cache?: { hits: number; misses: number; errors: number; circuit: Circuit }
}

const names: Record<string, string> = { mysql: 'MySQL 元数据', clickhouse: 'ClickHouse 主读', redis: 'Redis 共享状态', minio: 'MinIO 原始对象', kafka: 'Kafka 事件通道', flink: 'Flink 窗口集群' }
const statuses = { ok: '正常', disabled: '未启用', unavailable: '不可用' }
const circuits = { closed: '闭合', open: '熔断中', half_open: '恢复探测中' }

function CircuitStatus({ title, circuit }: { title: string; circuit: Circuit }) {
  return <div className="metric"><span>{title}</span><strong>{circuits[circuit.state]}</strong><small>连续失败 {circuit.consecutive_failures} · 短路 {circuit.short_circuits} 次 · {circuit.recovery_timeout_seconds}s 后探测</small></div>
}

export function SystemStatus() {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true); setError('')
    try { setReport(await api<Report>('/api/system/dependencies', signal)) }
    catch (reason) { if (!signal?.aborted) setError(reason instanceof Error ? reason.message : '无法加载依赖状态') }
    finally { if (!signal?.aborted) setBusy(false) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])
  return <main className="account-page"><div className="panel-head"><div><h1>系统运行监控</h1><p>独立探测各依赖的真实连接与响应；未启用不代表故障，探测结果不改变业务数据。</p></div><button disabled={busy} onClick={() => void load()}>{busy ? '正在探测…' : '重新探测'}</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {report && <>
      <p role="status">整体状态：{report.status === 'ok' ? '已启用依赖均正常' : '存在不可用依赖'} · {new Date(report.generated_at).toLocaleString('zh-CN')}</p>
      <div className="metrics three"><CircuitStatus title="共享限流与租约熔断" circuit={report.governance.circuit} />{report.catalog_cache && <CircuitStatus title="目录缓存熔断" circuit={report.catalog_cache.circuit} />}<div className="metric"><span>限流运行模式</span><strong>{report.governance.mode}</strong><small>{report.catalog_cache ? `缓存命中 ${report.catalog_cache.hits} · 回源/失败 ${report.catalog_cache.errors}` : '当前入口不持有目录缓存'}</small></div></div>
      <section className="panel"><div className="panel-head"><div><h2>依赖探针</h2><p>耗时为本次探测耗时，不代表业务查询的完整延迟</p></div></div><div className="table-wrap"><table><thead><tr><th>依赖</th><th>状态</th><th>探测方式</th><th>耗时</th><th>异常类型</th></tr></thead><tbody>{report.checks.map(item => <tr key={item.name}><td>{names[item.name] ?? item.name}</td><td><span className={`status-dot ${item.status}`} />{statuses[item.status]}</td><td>{item.probe ?? '—'}</td><td>{item.latency_ms === null ? '—' : `${item.latency_ms.toFixed(1)} ms`}</td><td>{item.error_type ?? '—'}</td></tr>)}</tbody></table></div></section>
      <p className="method-note">熔断打开时，普通读取使用受限本地降级；管理、回放控制和连接租约保持失败关闭。恢复探测成功后自动闭合，无需重启服务。</p>
    </>}
  </main>
}
