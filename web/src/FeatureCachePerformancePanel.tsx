import { Metric, Panel } from './ui'

type Latency = {
  sample_count: number
  latency_ms: { p50: number | null; p95: number | null; p99: number | null; min: number | null; max: number | null; mean: number | null }
  target_p95_ms: number | null
  p95_within_target: boolean | null
  result_consistent?: boolean
}
export type FeatureCachePerformanceReport = {
  report_type: 'redis_feature_cache_performance'
  performance_version: string
  generated_at: string
  complete: boolean
  configuration: {
    data_profile: string
    data: string
    measurement_path: string
    measurement_boundary: string
    http_boundary: string
    rounds: number
    samples_per_round: number
    http_samples: number
    miss_samples: number
    redis_host: string
    redis_port: number
  }
  environment: { git_revision: string; platform: string; python: string; redis_version: string; redis_mode: string }
  measurement: {
    validated_hit: Latency & { rounds: Array<{ round_index: number } & Latency> }
    cache_miss_repopulation: Latency
    http_keep_alive: Latency & { statuses: Record<string, number> }
  }
  checks: Record<string, boolean>
  target_evaluation: {
    primary_measurement: string
    target_p95_ms: number
    redis_feature_p95_below_10ms: boolean
    passes_provisional_target: boolean
    functional_checks_all_passed: boolean
    note: string
  }
  limitations: string[]
}

const checkNames: Record<string, string> = {
  real_redis_write_and_hit: '真实 Redis 写入与命中',
  authoritative_result_consistent: '缓存与权威快照一致',
  cross_service_object_hit: '独立服务对象共享命中',
  cache_miss_repopulation: '未命中回填',
  ttl_expiry: 'TTL 到期回源',
  corrupt_envelope_rejected: '损坏信封拒绝并修复',
  refused_endpoint_fallback: '拒绝连接时返回权威快照',
  circuit_opened: '连续故障打开熔断',
  circuit_recovery: '恢复探测闭合熔断',
  restricted_account_forbidden: '受限资产账号返回 403',
  forbidden_before_cache_read: '权限拒绝先于缓存读取',
}
function milliseconds(value: number | null) { return value === null ? '—' : `${value.toFixed(3)} ms` }
function conclusion(data: Latency, complete: boolean) {
  if (!data.sample_count) return '未测量'
  if (data.target_p95_ms === null) return '参考项，不判定'
  if (!complete || data.result_consistent === false) return '结果不完整，不可判定'
  return data.p95_within_target ? '通过暂定目标' : '未通过暂定目标'
}

export function FeatureCachePerformancePanel({ report, error }: { report: FeatureCachePerformanceReport | null; error: string }) {
  const rows = report ? [
    ['validated_hit', 'Redis 有效命中 · 生产服务主口径', report.measurement.validated_hit],
    ['cache_miss_repopulation', 'Redis 未命中与快照回填', report.measurement.cache_miss_repopulation],
    ['http_keep_alive', '完整 HTTP 长连接 · 参考', report.measurement.http_keep_alive],
  ] as const : []
  return <Panel title="Redis 热特征性能" subtitle="真实 Redis 与独立合成数据；主口径只测生产热特征读取，完整 HTTP 与功能检查分开报告" className="table-panel">
    {error && <p className="method-note" role="status">{error}</p>}
    {report && <>
      <div className="metrics three">
        <Metric label="热特征 p95" value={milliseconds(report.measurement.validated_hit.latency_ms.p95)} tone={!report.target_evaluation.passes_provisional_target ? 'risk' : ''} detail={`${report.measurement.validated_hit.sample_count} 个有效命中样本 · ${report.target_evaluation.passes_provisional_target ? '通过暂定 <10ms 目标' : '未通过暂定 <10ms 目标'}`} />
        <Metric label="真实缓存环境" value={`Redis ${report.environment.redis_version}`} detail={`${report.configuration.data_profile === 'synthetic-e2e' ? '合成 E2E 数据' : report.configuration.data_profile} · ${report.environment.redis_mode} · ${report.configuration.rounds} 轮`} />
        <Metric label="功能与一致性" value={report.target_evaluation.functional_checks_all_passed ? '全部通过' : '存在未通过项'} tone={!report.target_evaluation.functional_checks_all_passed ? 'risk' : ''} detail={`${Object.values(report.checks).filter(Boolean).length}/${Object.keys(report.checks).length} 项 · ${new Date(report.generated_at).toLocaleString('zh-CN')}`} />
      </div>
      <div className="table-wrap"><table className="computation-performance-table"><thead><tr><th>测量路径</th><th>样本数</th><th>p50</th><th>p95</th><th>p99</th><th>最大值</th><th>结论</th></tr></thead><tbody>
        {rows.map(([key, label, data]) => <tr key={key}><td>{label}</td><td className="numeric">{data.sample_count}</td><td className="numeric">{milliseconds(data.latency_ms.p50)}</td><td className="numeric">{milliseconds(data.latency_ms.p95)}</td><td className="numeric">{milliseconds(data.latency_ms.p99)}</td><td className="numeric">{milliseconds(data.latency_ms.max)}</td><td>{conclusion(data, report.complete)}</td></tr>)}
      </tbody></table></div>
      <details className="evaluation-lineage"><summary>查看逐轮热命中与功能检查</summary>
        <div className="table-wrap"><table className="computation-performance-table"><thead><tr><th>轮次</th><th>样本数</th><th>p50</th><th>p95</th><th>p99</th><th>最大值</th></tr></thead><tbody>{report.measurement.validated_hit.rounds.map(run => <tr key={run.round_index}><td>第 {run.round_index} 轮</td><td className="numeric">{run.sample_count}</td><td className="numeric">{milliseconds(run.latency_ms.p50)}</td><td className="numeric">{milliseconds(run.latency_ms.p95)}</td><td className="numeric">{milliseconds(run.latency_ms.p99)}</td><td className="numeric">{milliseconds(run.latency_ms.max)}</td></tr>)}</tbody></table></div>
        <div className="table-wrap"><table><thead><tr><th>行为检查</th><th>结果</th></tr></thead><tbody>{Object.entries(report.checks).map(([key, passed]) => <tr key={key}><td>{checkNames[key] ?? key}</td><td>{passed ? '通过' : '未通过'}</td></tr>)}</tbody></table></div>
      </details>
      <p className="method-note">主口径：{report.configuration.measurement_path}。{report.configuration.measurement_boundary}。HTTP 参考：{report.configuration.http_boundary}。{report.target_evaluation.note}。</p>
      <details className="evaluation-lineage"><summary>测量限制</summary><ul>{report.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
    </>}
  </Panel>
}
