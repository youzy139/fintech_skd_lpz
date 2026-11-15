import { Metric, Panel } from './ui'

type Latency = { p50: number | null; p95: number | null; p99: number | null; min: number | null; max: number | null }
export type ApiMeasurement = {
  requests: number
  successful: number
  statuses: Record<string, number>
  latency_ms: Latency
  throughput_requests_per_second: number | null
  p95_within_50ms: boolean
  scenarios?: Record<string, { requests: number; latency_ms: Latency }>
  round_metrics?: Array<{ requests: number; successful: number; latency_ms: Latency }>
}
export type ApiPerformanceReport = {
  report_type: 'independent_user_api_performance'
  performance_version: string
  generated_at: string
  configuration: { users: number; rounds: number; warmup_requests: number; timeout_seconds: number; scenarios: Record<string, string>; server_thread_pool_size: number }
  identity: { unique_sessions: number; type: string }
  environment: { git_revision: string; platform: string; python: string }
  measurement: {
    new_connection_per_request: ApiMeasurement
    keep_alive_per_user: ApiMeasurement
    server_metrics?: { routes: Array<{ route: string; sample_size: number; p95_ms: number | null; auth_p95_ms: number | null; governance_p95_ms: number | null }> }
  }
  catalog_version_performance?: {
    performance_version: string
    source_files: number
    samples_per_path: number
    legacy: { p50_ms: number; p95_ms: number; mean_ms: number }
    cached: { p50_ms: number; p95_ms: number; mean_ms: number }
    mean_reduction_percent: number
    limitations: string
  }
  target_evaluation: { independent_users_above_100: boolean; all_requests_successful: boolean; api_p95_below_50ms: boolean; passes_provisional_target: boolean; note: string }
  baseline_comparison?: {
    comparison_version: string
    baseline_generated_at: string
    baseline_git_revision?: string
    interpretation: string
    groups: Record<'new_connection_per_request' | 'keep_alive_per_user', { baseline_p95_ms: number; current_p95_ms: number; delta_ms: number; change_percent: number | null; sample_count: number }>
  }
}

const groups = [
  ['new_connection_per_request', '每次新建连接'],
  ['keep_alive_per_user', '每用户长连接'],
] as const
function milliseconds(value: number | null) { return value === null ? '—' : `${value.toFixed(3)} ms` }
function signedChange(delta: number, percent: number | null) {
  if (delta === 0) return '无变化'
  return `${delta < 0 ? '减少' : '增加'} ${Math.abs(delta).toFixed(3)} ms${percent === null ? '' : `（${Math.abs(percent).toFixed(2)}%）`}`
}

export function ApiPerformancePanel({ report, error }: { report: ApiPerformanceReport | null; error: string }) {
  return <Panel title="独立用户 API 性能" subtitle="隔离合成账号与数据的真实本地 HTTP 基准；包含冷轮次，不是公网容量或生产 SLA" className="table-panel">
    {error && <p className="method-note" role="status">{error}</p>}
    {report && <>
      <div className="metrics three">
        <Metric label="独立用户与请求" value={`${report.configuration.users} 用户 · ${report.measurement.new_connection_per_request.requests + report.measurement.keep_alive_per_user.requests} 请求`} detail={`${report.identity.unique_sessions} 个独立会话 · 每种模式 ${report.configuration.rounds} 轮 · 预热 ${report.configuration.warmup_requests} 请求`} />
        <Metric label="暂定目标结论" value={report.target_evaluation.passes_provisional_target ? '通过' : '未通过'} tone={report.target_evaluation.passes_provisional_target ? '' : 'risk'} detail={`独立用户 >100、全部成功且两种模式 p95 <50ms 必须同时满足`} />
        <Metric label="报告与源码" value={report.environment.git_revision.slice(0, 12)} detail={`${new Date(report.generated_at).toLocaleString('zh-CN')} · ${report.environment.python} · ${report.performance_version}`} />
      </div>
      {report.baseline_comparison && <section className="performance-baseline"><h3>API 前后同口径对照</h3><p>基线 {report.baseline_comparison.baseline_git_revision ? `${report.baseline_comparison.baseline_git_revision.slice(0, 12)} · ` : ''}生成于 {new Date(report.baseline_comparison.baseline_generated_at).toLocaleString('zh-CN')}；保留全部样本，变化方向如实展示；提交号相同时仍以双方运行源码摘要区分。</p><div className="table-wrap"><table className="performance-baseline-table"><thead><tr><th>连接模式</th><th>此前 p95</th><th>本次 p95</th><th>变化</th><th>样本数</th></tr></thead><tbody>{groups.map(([key, label]) => { const data = report.baseline_comparison!.groups[key]; return <tr key={key}><td>{label}</td><td className="numeric">{milliseconds(data.baseline_p95_ms)}</td><td className="numeric">{milliseconds(data.current_p95_ms)}</td><td>{signedChange(data.delta_ms, data.change_percent)}</td><td className="numeric">{data.sample_count}</td></tr> })}</tbody></table></div><p className="method-note">{report.baseline_comparison.interpretation}。</p></section>}
      {report.catalog_version_performance && <section className="performance-baseline"><h3>目录数据版本微基准</h3><p>真实 SQLite 只读目录 · {report.catalog_version_performance.source_files.toLocaleString('zh-CN')} 个来源文件 · 交错测量顺序 · 均值减少 {report.catalog_version_performance.mean_reduction_percent.toFixed(3)}%。</p><div className="table-wrap"><table className="performance-baseline-table"><thead><tr><th>查询路径</th><th>样本数</th><th>p50</th><th>p95</th><th>平均值</th></tr></thead><tbody>{([['legacy', '每次扫描全部来源行'], ['cached', '未变化时复用精确摘要']] as const).map(([key, label]) => { const data = report.catalog_version_performance![key]; return <tr key={key}><td>{label}</td><td className="numeric">{report.catalog_version_performance!.samples_per_path}</td><td className="numeric">{milliseconds(data.p50_ms)}</td><td className="numeric">{milliseconds(data.p95_ms)}</td><td className="numeric">{milliseconds(data.mean_ms)}</td></tr> })}</tbody></table></div><p className="method-note">{report.catalog_version_performance.limitations}。</p></section>}
      <div className="table-wrap"><table className="api-performance-table"><thead><tr><th>连接模式</th><th>成功/请求</th><th>p50</th><th>p95</th><th>p99</th><th>最大值</th><th>吞吐</th><th>结论</th></tr></thead><tbody>{groups.map(([key, label]) => { const data = report.measurement[key]; return <tr key={key}><td>{label}</td><td className="numeric">{data.successful}/{data.requests}</td><td className="numeric">{milliseconds(data.latency_ms.p50)}</td><td className="numeric">{milliseconds(data.latency_ms.p95)}</td><td className="numeric">{milliseconds(data.latency_ms.p99)}</td><td className="numeric">{milliseconds(data.latency_ms.max)}</td><td className="numeric">{data.throughput_requests_per_second?.toFixed(3) ?? '—'} 请求/秒</td><td>{data.p95_within_50ms ? 'p95 通过暂定目标' : 'p95 未通过暂定目标'}</td></tr> })}</tbody></table></div>
      <div className="table-wrap"><table className="api-performance-table"><thead><tr><th>业务场景</th><th>新连接样本</th><th>新连接 p95</th><th>长连接样本</th><th>长连接 p95</th></tr></thead><tbody>{Object.entries(report.configuration.scenarios).map(([name, path]) => { const fresh = report.measurement.new_connection_per_request.scenarios?.[path]; const persistent = report.measurement.keep_alive_per_user.scenarios?.[path]; return <tr key={name}><td>{name}<small className="table-secondary">{path}</small></td><td className="numeric">{fresh?.requests ?? '—'}</td><td className="numeric">{milliseconds(fresh?.latency_ms.p95 ?? null)}</td><td className="numeric">{persistent?.requests ?? '—'}</td><td className="numeric">{milliseconds(persistent?.latency_ms.p95 ?? null)}</td></tr> })}</tbody></table></div>
      {report.measurement.server_metrics?.routes && <section className="performance-baseline"><h3>服务端路由分段（进程内）</h3><div className="table-wrap"><table className="api-performance-table"><thead><tr><th>路由</th><th>样本数</th><th>完整路由 p95</th><th>身份验证 p95</th><th>限流 p95</th></tr></thead><tbody>{report.measurement.server_metrics.routes.map(route => <tr key={route.route}><td>{route.route}</td><td className="numeric">{route.sample_size}</td><td className="numeric">{milliseconds(route.p95_ms)}</td><td className="numeric">{milliseconds(route.auth_p95_ms)}</td><td className="numeric">{milliseconds(route.governance_p95_ms)}</td></tr>)}</tbody></table></div><p className="method-note">进程内分段用于定位，不包含完整客户端连接、同机调度和网络边界，不能替代上述客户端 p95 结论。</p></section>}
      {report.measurement.keep_alive_per_user.round_metrics && <details className="evaluation-lineage"><summary>查看长连接逐轮结果（首轮不排除）</summary><div className="table-wrap"><table className="api-performance-table"><thead><tr><th>轮次</th><th>成功/请求</th><th>p50</th><th>p95</th><th>p99</th><th>最大值</th></tr></thead><tbody>{report.measurement.keep_alive_per_user.round_metrics.map((round, index) => <tr key={index}><td>第 {index + 1} 轮{index === 0 ? ' · 冷轮次保留' : ''}</td><td className="numeric">{round.successful}/{round.requests}</td><td className="numeric">{milliseconds(round.latency_ms.p50)}</td><td className="numeric">{milliseconds(round.latency_ms.p95)}</td><td className="numeric">{milliseconds(round.latency_ms.p99)}</td><td className="numeric">{milliseconds(round.latency_ms.max)}</td></tr>)}</tbody></table></div></details>}
      <p className="method-note">计时从客户端发起请求到读取完整响应，客户端与服务端位于同一机器；登录计时排除，但每个请求都执行真实 JWT、用户/会话校验和限流。整体 p95 包含长连接首轮，不能用后续热轮次替代。{report.target_evaluation.note}。</p>
    </>}
  </Panel>
}
