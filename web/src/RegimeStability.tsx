import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from './Icon'
import CoverageSensitivityPanel from './CoverageSensitivityPanel'
import ModelCardPanel from './ModelCardPanel'
import { api } from './api'
import { numeric, percent } from './format'
import { ErrorMessage, Loading, Metric, Panel } from './ui'
import type { StabilityPeriod, StabilityReport } from './types'

const periodOrder: StabilityPeriod[] = ['all', 'development', 'validation', 'holdout']

function downloadReport(report: StabilityReport) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${report.evaluation_id}.json`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function RegimeStability() {
  const [report, setReport] = useState<StabilityReport | null>(null)
  const [period, setPeriod] = useState<StabilityPeriod>('all')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const load = useCallback(() => { setError(''); setLoading(true); setAttempt(value => value + 1) }, [])
  useEffect(() => {
    const controller = new AbortController()
    api<StabilityReport>('/api/regimes/evaluation/stability', controller.signal)
      .then(setReport)
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '稳定性报告暂不可用') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [attempt])
  const comparisons = useMemo(() => report?.comparisons.filter(item => item.period === period) ?? [], [report, period])
  const pairMap = useMemo(() => new Map(comparisons.map(item => [`${item.left_run_id}:${item.right_run_id}`, item])), [comparisons])
  if (loading && !report) return <Loading>正在读取已固定的稳定性实验报告…</Loading>
  if (error && !report) return <Panel title="模型稳定性报告" subtitle="只读评估，不修改当前模型或历史回放"><ErrorMessage message={error} onRetry={load} retryLabel="重新读取报告" /><p className="method-note">报告由独立脚本离线生成。缺失或版本不匹配时不会回退展示旧结论。</p></Panel>
  if (!report) return null
  const summary = report.summary[period]
  const referenceComparisons = comparisons.filter(item => item.left_run_id === report.reference_run_id || item.right_run_id === report.reference_run_id)
  return <>
    {error && <ErrorMessage message={error} onRetry={load} retryLabel="重新读取报告" />}
    <div className="metrics four">
      <Metric label="完整实验组合" value={<>{report.grid.run_count}<em>组</em></>} detail={`${report.fixed.cluster_count} 簇 · ${report.fixed.regime_identity}`} />
      <Metric label="ARI 中位数" value={numeric(summary.adjusted_rand_index.median, 3)} detail={`${summary.pair_count} 个两两组合 · 编号置换不变`} featured />
      <Metric label="最低语义一致率" value={percent(summary.semantic_agreement.min, 2)} detail="仅比较语义名称，不等于画像相同" />
      <Metric label="共同状态日" value={summary.common_state_days.median?.toLocaleString() ?? '—'} detail={report.period_definitions[period].label} />
    </div>
    <Panel title="实验概览" subtitle={`${report.protocol_version} · 协议草案，待团队复核`} action={<div className="report-actions"><label>评估区间<select aria-label="评估区间" value={period} onChange={event => setPeriod(event.target.value as StabilityPeriod)}>{periodOrder.map(key => <option key={key} value={key}>{report.period_definitions[key].label}</option>)}</select></label><button className="text-button" onClick={() => downloadReport(report)}><Icon name="download" />导出报告 JSON</button></div>}>
      <div className="evaluation-notice"><Icon name="alerts" /><p><strong>稳定性不是预测准确率。</strong>本报告比较参数扰动下的历史状态分区，不提供金融事件命中率、误报率或投资效果结论。事件标注与预警 episode 回测仍未完成。</p></div>
      <dl className="evaluation-facts"><div><dt>评估区间</dt><dd>{report.period_definitions[period].start ?? report.runs[0]?.periods[period].first_state ?? '—'} ～ {report.period_definitions[period].end ?? report.runs[0]?.periods[period].last_state ?? '—'}</dd></div><div><dt>当前基准组合</dt><dd className="numeric">{report.reference_run_id}</dd></div><div><dt>报告生成时间</dt><dd>{new Date(report.generated_at).toLocaleString('zh-CN')}</dd></div><div><dt>输入规模</dt><dd>{report.loaded_assets} 个资产 · {report.feature_days.toLocaleString()} 个特征日</dd></div></dl>
    </Panel>
    {report.model_card ? <ModelCardPanel card={report.model_card} /> : <Panel title="模型卡与输入覆盖" subtitle="当前报告尚未包含 model-card-v1"><p className="method-note">请重新运行只读评估脚本生成输入覆盖信息；既有稳定性结果仍按原报告展示。</p></Panel>}
    {report.coverage_sensitivity && <CoverageSensitivityPanel data={report.coverage_sensitivity} period={period} />}
    <Panel title="全部参数组合" subtitle="完整展示实验网格；持续期在评估区间边界截断" className="table-panel stability-runs">
      <div className="table-wrap"><table className="stability-run-table"><thead><tr><th>组合</th><th>训练窗口</th><th>重训间隔</th><th>随机种子</th><th>状态日</th><th>切换 / 100日</th><th>持续期中位数</th><th>P90 持续期</th><th>边界切换占比</th></tr></thead><tbody>{report.runs.map(run => { const result = run.periods[period]; return <tr key={run.run_id}><td><strong className="numeric">{run.run_id}</strong>{run.is_reference && <small className="table-subtitle">当前基准</small>}</td><td>{run.training_window} 日</td><td>{run.refit_interval} 日</td><td>{run.random_seed}</td><td>{result.state_days.toLocaleString()}</td><td>{numeric(result.switches_per_100_state_days, 2)}</td><td>{numeric(result.median_duration_days, 1)} 日</td><td>{numeric(result.p90_duration_days, 1)} 日</td><td>{percent(result.refit_boundary_switch_share, 2)}</td></tr> })}</tbody></table></div>
      <p className="method-note">边界切换占比 = 发生在重训边界的切换数 ÷ 全部切换数；无切换时显示缺失。切换使用含稳定身份的完整标签，与当前切换规则口径一致。</p>
    </Panel>
    <Panel title="与当前基准组合对照" subtitle="ARI 衡量分区相似性；语义一致率单独列示" className="table-panel">
      <div className="table-wrap"><table><thead><tr><th>对照组合</th><th>共同状态日</th><th>共同区间</th><th>调整兰德指数（ARI）</th><th>语义标签一致率</th></tr></thead><tbody>{referenceComparisons.map(item => <tr key={`${item.left_run_id}-${item.right_run_id}`}><td className="numeric">{item.left_run_id === report.reference_run_id ? item.right_run_id : item.left_run_id}</td><td>{item.common_state_days.toLocaleString()}</td><td className="numeric">{item.common_start ?? '—'} ～ {item.common_end ?? '—'}</td><td>{numeric(item.adjusted_rand_index, 4)}</td><td>{percent(item.semantic_agreement, 2)}</td></tr>)}</tbody></table></div>
      <p className="method-note">{report.metric_definitions.adjusted_rand_index} {report.metric_definitions.semantic_agreement}</p>
    </Panel>
    <Panel title="两两组合 ARI 矩阵" subtitle={`${report.period_definitions[period].label} · 不只保留表现最好的组合`} className="table-panel stability-matrix-panel">
      <div className="table-wrap"><table className="stability-matrix"><thead><tr><th>组合</th>{report.runs.map(run => <th key={run.run_id}><abbr title={run.run_id}>{run.run_id}</abbr></th>)}</tr></thead><tbody>{report.runs.map(left => <tr key={left.run_id}><th><abbr title={left.run_id}>{left.run_id}</abbr></th>{report.runs.map(right => { const same = left.run_id === right.run_id; const pair = pairMap.get(`${left.run_id}:${right.run_id}`) ?? pairMap.get(`${right.run_id}:${left.run_id}`); const value = same ? left.periods[period].state_days > 0 ? 1 : null : pair?.adjusted_rand_index; return <td key={right.run_id}>{numeric(value, 3)}</td> })}</tr>)}</tbody></table></div>
    </Panel>
    <Panel title="口径、血缘与限制" subtitle="报告绑定输入、特征与模型参数；版本变化后必须重新生成">
      <details className="evaluation-lineage"><summary>查看固定参数与版本摘要</summary><dl className="contract-versions"><dt>评估 ID</dt><dd>{report.evaluation_id}</dd><dt>输入版本</dt><dd>{report.input_version}</dd><dt>特征版本</dt><dd>{report.feature_version}</dd><dt>特征内容摘要</dt><dd>{report.feature_sha256}</dd>{Object.entries(report.source_sha256).map(([name, digest]) => <div key={name}><dt>{name}</dt><dd>{digest}</dd></div>)}</dl></details>
      <ul className="evaluation-limitations">{report.limitations.map(item => <li key={item}>{item}</li>)}</ul>
      {report.daily_results && <p className="method-note">逐日最小结果另存于 {report.daily_results.file}，共 {report.daily_results.state_days.toLocaleString()} 条；SHA-256：{report.daily_results.sha256}</p>}
    </Panel>
  </>
}
