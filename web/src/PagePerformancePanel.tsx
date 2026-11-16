import { Metric, Panel } from './ui'

type PageResult = {
  label: string
  cold_p95_ms: number | null
  hot_p95_ms: number | null
  slow_4g_p95_ms: number | null
  cold_samples: string
  hot_samples: string
  slow_4g_samples: string
  passes_provisional_target: boolean
}
export type PagePerformanceReport = {
  report_type: 'browser_page_performance'
  performance_version: string
  generated_at: string
  complete: boolean
  configuration: {
    data_profile: string
    pages: number
    rounds_per_page: number
    slow_4g_rounds_per_page: number
    viewport: { width: number; height: number }
    measurement_boundary: string
    cold_definition: string
    hot_definition: string
    slow_4g_definition: string
  }
  environment: { platform: string; node: string; git_revision: string; browser: { name: string; version: string; channel: string; headless: boolean } }
  measurement: Record<'cold_empty_context' | 'hot_repeat_reload' | 'slow_4g_reference', {
    attempt_count: number
    successful_count: number
    failed_count: number
    sample_count: number
    latency_ms: { p50: number | null; p95: number | null; p99: number | null; min: number | null; max: number | null; mean: number | null }
    target_p95_ms: number | null
    p95_within_target: boolean | null
  }>
  page_results: Record<string, PageResult>
  target_evaluation: {
    target_p95_ms: number
    primary_profiles: string[]
    all_primary_samples_successful: boolean
    all_pages_below_2s: boolean
    passes_provisional_target: boolean
    note: string
  }
  limitations: string[]
}

function milliseconds(value: number | null) { return value === null ? '—' : `${value.toFixed(3)} ms` }

export function PagePerformancePanel({ report, error }: { report: PagePerformanceReport | null; error: string }) {
  const cold = report?.measurement.cold_empty_context
  const hot = report?.measurement.hot_repeat_reload
  const pages = Object.entries(report?.page_results ?? {})
  return <Panel title="页面加载性能" subtitle="真实 Chrome 从导航到页面可用；新上下文冷加载与同上下文热 reload 分开，Slow 4G 仅作参考" className="table-panel">
    {error && <p className="method-note" role="status">{error}</p>}
    {report && cold && hot && <>
      <div className="metrics three">
        <Metric label="新上下文冷加载 p95" value={milliseconds(cold.latency_ms.p95)} tone={!cold.p95_within_target ? 'risk' : ''} detail={`${cold.successful_count}/${cold.attempt_count} 次成功 · ${report.configuration.pages} 个页面`} />
        <Metric label="同上下文热 reload p95" value={milliseconds(hot.latency_ms.p95)} tone={!hot.p95_within_target ? 'risk' : ''} detail={`${hot.successful_count}/${hot.attempt_count} 次成功 · 预热不计时`} />
        <Metric label="逐页暂定目标" value={report.target_evaluation.passes_provisional_target ? '全部通过' : '未全部通过'} tone={!report.target_evaluation.passes_provisional_target ? 'risk' : ''} detail={`${report.environment.browser.name} ${report.environment.browser.version} · ${report.configuration.viewport.width}×${report.configuration.viewport.height}`} />
      </div>
      <div className="table-wrap"><table className="computation-performance-table"><thead><tr><th>主要页面</th><th>冷加载 p95</th><th>成功</th><th>热 reload p95</th><th>成功</th><th>Slow 4G p95 · 参考</th><th>成功</th><th>&lt;2s 结论</th></tr></thead><tbody>
        {pages.map(([id, item]) => <tr key={id}><td>{item.label}</td><td className="numeric">{milliseconds(item.cold_p95_ms)}</td><td className="numeric">{item.cold_samples}</td><td className="numeric">{milliseconds(item.hot_p95_ms)}</td><td className="numeric">{item.hot_samples}</td><td className="numeric">{milliseconds(item.slow_4g_p95_ms)}</td><td className="numeric">{item.slow_4g_samples}</td><td>{item.passes_provisional_target ? '通过暂定目标' : '未通过暂定目标'}</td></tr>)}
      </tbody></table></div>
      <details className="evaluation-lineage"><summary>查看计时边界与环境</summary><p className="method-note">{report.configuration.measurement_boundary}。</p><p className="method-note">冷加载：{report.configuration.cold_definition}。热加载：{report.configuration.hot_definition}。Slow 4G：{report.configuration.slow_4g_definition}。</p><p className="method-note">报告生成于 {new Date(report.generated_at).toLocaleString('zh-CN')} · {report.environment.platform} · Node {report.environment.node} · {report.performance_version}。{report.target_evaluation.note}。</p></details>
      <details className="evaluation-lineage"><summary>测量限制</summary><ul>{report.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
    </>}
  </Panel>
}
