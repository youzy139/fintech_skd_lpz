import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { ErrorMessage, Metric, Panel } from './ui'

type Check = { name: string; status: 'ok' | 'disabled' | 'unavailable'; latency_ms: number | null; probe?: string; error_type?: string }
type Circuit = { state: 'closed' | 'open' | 'half_open'; consecutive_failures: number; short_circuits: number; recovery_timeout_seconds: number }
type Report = { status: 'ok' | 'degraded'; generated_at: string; checks: Check[]; governance: { mode: string; circuit: Circuit }; catalog_cache?: { hits: number; misses: number; errors: number; circuit: Circuit; local?: { enabled: boolean; hits?: number; misses?: number; entries?: number; max_entries?: number; evictions?: number; expirations?: number }; shared?: { enabled: boolean; hits?: number; misses?: number; writes?: number; errors?: number } } }
const names: Record<string, string> = { mysql: 'MySQL 元数据', clickhouse: 'ClickHouse 主读', redis: 'Redis 共享状态', minio: 'MinIO 原始对象', kafka: 'Kafka 事件通道', flink: 'Flink 窗口集群' }
const statuses = { ok: '正常', disabled: '未启用', unavailable: '不可用' }
const circuits = { closed: '闭合', open: '熔断中', half_open: '恢复探测中' }
function CircuitStatus({ title, circuit }: { title: string; circuit: Circuit }) { return <Metric label={title} value={circuits[circuit.state]} tone={circuit.state === 'open' ? 'risk' : ''} detail={`连续失败 ${circuit.consecutive_failures} · 短路 ${circuit.short_circuits} 次 · ${circuit.recovery_timeout_seconds}s 后探测`} /> }

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
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort() }, [load])
  return <div className="account-page"><div className="admin-heading"><div><h2>系统运行监控</h2><p>独立探测各依赖的真实连接与响应；未启用不代表故障，探测结果不改变业务数据。</p></div><button disabled={busy} onClick={() => void load()}>{busy ? '正在探测…' : '重新探测'}</button></div>
    {error && <ErrorMessage message={error} />}
    {report && <><p className={`system-summary ${report.status}`} role="status">整体状态：{report.status === 'ok' ? '已启用依赖均正常' : '存在不可用依赖'} · {new Date(report.generated_at).toLocaleString('zh-CN')}</p><div className="metrics three"><CircuitStatus title="共享限流与租约熔断" circuit={report.governance.circuit} />{report.catalog_cache && <CircuitStatus title="目录缓存熔断" circuit={report.catalog_cache.circuit} />}<Metric label="限流运行模式" value={report.governance.mode} detail={report.catalog_cache ? `缓存命中 ${report.catalog_cache.hits} · 回源/失败 ${report.catalog_cache.errors}` : '当前入口不持有目录缓存'} /></div>
      <Panel title="依赖探针" subtitle="耗时为本次探测耗时，不代表业务查询的完整延迟" className="table-panel"><div className="table-wrap"><table><thead><tr><th>依赖</th><th>状态</th><th>探测方式</th><th>耗时</th><th>异常类型</th></tr></thead><tbody>{report.checks.map(item => <tr key={item.name}><td>{names[item.name] ?? item.name}</td><td><span className={`status-dot ${item.status}`} />{statuses[item.status]}</td><td>{item.probe ?? '—'}</td><td className="numeric">{item.latency_ms === null ? '—' : `${item.latency_ms.toFixed(1)} ms`}</td><td>{item.error_type ?? '—'}</td></tr>)}</tbody></table></div></Panel>
      {report.catalog_cache?.local && <Panel title="目录缓存分工" subtitle="统计来自实际处理目录查询的数据服务；大偏移分页不进入缓存" className="table-panel"><div className="table-wrap"><table><thead><tr><th>缓存层</th><th>职责</th><th>命中</th><th>未命中/回源</th><th>容量或异常</th></tr></thead><tbody><tr><td>进程内一级缓存</td><td>避免同一实例重复访问 Redis，短 TTL、有界 LRU</td><td>{report.catalog_cache.local.hits ?? 0}</td><td>{report.catalog_cache.local.misses ?? 0}</td><td>{report.catalog_cache.local.enabled ? `${report.catalog_cache.local.entries ?? 0}/${report.catalog_cache.local.max_entries ?? 0} 项 · 淘汰 ${report.catalog_cache.local.evictions ?? 0} · 过期 ${report.catalog_cache.local.expirations ?? 0}` : '未启用'}</td></tr><tr><td>Redis 二级缓存</td><td>跨实例共享目录结果，数据版本变化自动隔离旧键</td><td>{report.catalog_cache.shared?.hits ?? report.catalog_cache.hits}</td><td>{report.catalog_cache.shared?.misses ?? report.catalog_cache.misses}</td><td>异常 {report.catalog_cache.shared?.errors ?? report.catalog_cache.errors} · 熔断 {circuits[report.catalog_cache.circuit.state]}</td></tr></tbody></table></div><p className="method-note">一级缓存未命中才访问 Redis；Redis 不可用时回源 ClickHouse，不返回伪造结果。权限在入口与数据服务先行校验，目录查询键包含数据版本与完整筛选参数。</p></Panel>}
      <p className="method-note">熔断打开时，普通读取使用受限本地降级；管理、回放控制和连接租约保持失败关闭。恢复探测成功后自动闭合，无需重启服务。</p>
    </>}
  </div>
}
