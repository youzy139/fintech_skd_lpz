import { Metric, Panel } from './ui'

export type LatencySummary = {
  sample_count: number
  latency_ms: { p50: number | null; p95: number | null; p99: number | null; min: number | null; max: number | null; mean: number | null }
  target_p95_ms: number
  p95_within_target: boolean | null
}
export type PerformanceSummaries = { features: LatencySummary; regime_non_refit: LatencySummary; regime_refit: LatencySummary; regime_all: LatencySummary }
export type ComputationPerformanceReport = {
  report_type: 'model_computation_performance'
  performance_version: string
  generated_at: string
  complete: boolean
  result_consistent: boolean
  targets_conclusive: boolean
  result_comparison?: { compared_days_per_run: number; exact_digest_matching_days: number }
  configuration: { event_start: string; event_end: string; event_days_per_run: number; runs: number; loaded_assets: number; data_profile?: string; measurement_boundary: string; temperature_boundary: string }
  environment: { git_revision: string; platform: string; python: string; computation_sources_dirty_at_generation?: boolean | null }
  summary: PerformanceSummaries
  runs?: Array<{ run_index: number; temperature: string; initialization_ms_excluded_from_daily_samples: number; summary: PerformanceSummaries }>
}

const rows = [
  ['features', '特征单日计算'],
  ['regime_non_refit', '状态识别 · 非重训日'],
  ['regime_refit', '状态识别 · 重训日'],
] as const
function milliseconds(value: number | null) { return value === null ? '—' : `${value.toFixed(3)} ms` }
function conclusion(data: LatencySummary, conclusive: boolean) {
  if (!data.sample_count) return '未测量'
  if (!conclusive) return '结果不一致，不可判定'
  if (data.p95_within_target === null) return '不可判定'
  return data.p95_within_target ? '通过暂定目标' : '未通过暂定目标'
}

export function ComputationPerformancePanel({ report, error }: { report: ComputationPerformanceReport | null; error: string }) {
  return <Panel title="单日计算性能" subtitle="固定输入的只读离线基准；阈值采用暂定 p95 口径，不代表并发、端到端或公网性能" className="table-panel">
    {error && <p className="method-note" role="status">{error}</p>}
    {report && <>
      <div className="metrics three">
        <Metric label="测量区间" value={`${report.configuration.event_start} ～ ${report.configuration.event_end}`} detail={`${report.configuration.data_profile === 'synthetic-e2e' ? '合成 E2E 数据 · ' : report.configuration.data_profile === 'real-competition-read-only' ? '真实赛题只读行情 · ' : ''}每轮 ${report.configuration.event_days_per_run} 个事件日 · ${report.configuration.runs} 轮 · ${report.configuration.loaded_assets} 个资产`} />
        <Metric label="报告状态" value={!report.complete ? '测量不完整' : report.targets_conclusive ? '轮次结果一致' : '轮次结果不一致'} tone={!report.complete || !report.targets_conclusive ? 'risk' : ''} detail={`${report.result_comparison ? `容差比较 · 精确摘要 ${report.result_comparison.exact_digest_matching_days}/${report.result_comparison.compared_days_per_run} 日一致 · ` : ''}${new Date(report.generated_at).toLocaleString('zh-CN')}`} />
        <Metric label="源码提交" value={report.environment.git_revision.slice(0, 12)} detail={`${report.environment.python} · ${report.environment.computation_sources_dirty_at_generation ? '生成时含未提交计算源码，以摘要为准' : '计算源码摘要已绑定'} · ${report.performance_version}`} />
      </div>
      <div className="table-wrap"><table className="computation-performance-table"><thead><tr><th>计算阶段</th><th>样本数</th><th>p50</th><th>p95</th><th>p99</th><th>最大值</th><th>暂定目标</th><th>结论</th></tr></thead><tbody>
        {rows.map(([key, label]) => { const data = report.summary[key]; return <tr key={key}><td>{label}</td><td className="numeric">{data.sample_count}</td><td className="numeric">{milliseconds(data.latency_ms.p50)}</td><td className="numeric">{milliseconds(data.latency_ms.p95)}</td><td className="numeric">{milliseconds(data.latency_ms.p99)}</td><td className="numeric">{milliseconds(data.latency_ms.max)}</td><td className="numeric">p95 &lt; {data.target_p95_ms} ms</td><td>{conclusion(data, report.complete && report.targets_conclusive)}</td></tr> })}
      </tbody></table></div>
      {report.runs && <details className="evaluation-lineage"><summary>查看逐轮结果与排除的初始化耗时</summary><div className="table-wrap"><table className="computation-performance-table"><thead><tr><th>轮次</th><th>初始化（不计入单日）</th><th>特征 p95</th><th>非重训 p95</th><th>重训 p95</th></tr></thead><tbody>{report.runs.map(run => <tr key={run.run_index}><td>第 {run.run_index} 轮 · {run.temperature === 'first_engine_in_process' ? '同进程首个 engine' : '同进程后续 engine'}</td><td className="numeric">{milliseconds(run.initialization_ms_excluded_from_daily_samples)}</td><td className="numeric">{milliseconds(run.summary.features.latency_ms.p95)}</td><td className="numeric">{milliseconds(run.summary.regime_non_refit.latency_ms.p95)}</td><td className="numeric">{milliseconds(run.summary.regime_refit.latency_ms.p95)}</td></tr>)}</tbody></table></div></details>}
      <p className="method-note">计时仅包含生产连续回放中的真实特征计算和状态预测；历史初始化/预热、输入追加、预警、持久化不计入单日样本。无有效特征或无状态的日子不记为零耗时成功样本。轮次结果按 1e-12 数值容差比较并排除 replay_time，精确摘要一致日数单独列出。首轮与后续轮次都在同一进程新建 engine，不是冷进程测试。{report.configuration.measurement_boundary}。</p>
    </>}
  </Panel>
}
