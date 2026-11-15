import { useEffect, useState } from 'react'
import { api } from './api'
import { useAuth } from './Auth'
import { numeric, percent } from './format'
import { featureNames, ruleNames } from './labels'
import { ErrorMessage, Loading, Metric, Panel } from './ui'
import type { ResearchCase } from './types'

const contextNames: Record<string, string> = { calendar: '经济日历', publication: '公众号文章', news: '新闻', indicator: '宏观指标', research: '研究摘要', social: '社交媒体' }

function featureValue(feature: string, value: number | null) {
  if (value === null) return '—'
  if (feature === 'sample_count') return numeric(value, 0)
  if (feature === 'correlation') return numeric(value, 4)
  return percent(value, 3)
}

function deltaValue(feature: string, value: number | null) {
  if (value === null) return '—'
  const sign = value > 0 ? '+' : ''
  if (feature === 'sample_count') return `${sign}${numeric(value, 0)}`
  if (feature === 'correlation') return `${sign}${numeric(value, 4)}`
  return `${sign}${(value * 100).toFixed(3)}%`
}

export default function ResearchCase() {
  const { user } = useAuth()
  const [item, setItem] = useState<ResearchCase | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api<ResearchCase>('/api/research/cases/latest', controller.signal).then(setItem).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '研究案例暂不可用') })
    return () => controller.abort()
  }, [attempt])
  if (!item) return error ? <Panel title="可复核研究案例"><ErrorMessage message={error} onRetry={() => setAttempt(value => value + 1)} retryLabel="重新读取案例" /></Panel> : <Loading>正在选取真实规则案例与证据…</Loading>
  const { evidence } = item
  const canReplay = user.domains.includes('market') && user.domains.includes('catalog')
  return <>
    <div className="metrics three"><Metric label="案例事件日" value={item.event_time} detail="最近状态切换优先 · 当前规则视图" featured /><Metric label="触发规则" value={ruleNames[evidence.rule] ?? evidence.rule} detail={evidence.rule_version} /><Metric label="当日状态" value={evidence.state.label} detail={`训练数据截至 ${evidence.state.trained_through}`} /></div>
    <Panel title="01 · 发现状态变化" subtitle="来自确定性规则，不是人工金融事件标注或 LLM 判断">
      <div className="case-transition"><div><span>前一状态日</span><strong>{evidence.previous_state?.label ?? '—'}</strong><small>{evidence.previous_state?.date ?? '无更早状态'}</small></div><b>→</b><div><span>案例事件日</span><strong>{evidence.state.label}</strong><small>{item.event_time}</small></div></div>
      <p className="case-observation">{item.conclusion.observation}</p>
      <p className="method-note">选择策略：优先使用当前历史视图最近一次 REGIME_CHANGE；不存在时才回退到其他最新预警。案例不随页面请求重新训练。</p>
    </Panel>
    <Panel title="02 · 对照前后特征" subtitle="变化量 = 案例事件日 − 前一状态日；任一缺失则变化量缺失" className="table-panel">
      <div className="table-wrap"><table className="case-feature-table"><thead><tr><th>特征</th><th>前一状态日</th><th>案例事件日</th><th>变化量</th></tr></thead><tbody>{item.feature_changes.map(change => <tr key={change.feature}><td>{featureNames[change.feature] ?? change.feature}</td><td>{featureValue(change.feature, change.previous)}</td><td>{featureValue(change.feature, change.current)}</td><td>{deltaValue(change.feature, change.delta)}</td></tr>)}</tbody></table></div>
      <p className="method-note">特征对照描述统计变化，不表示某个特征导致了状态切换，也不构成收益预测。</p>
    </Panel>
    <Panel title="03 · 核对统计与当时可见背景" subtitle="统计证据与公开背景分开，背景只截至前一状态日">
      <dl className="evaluation-facts"><div><dt>模型版本</dt><dd>{evidence.state.model_version}</dd></div><div><dt>规则版本</dt><dd>{evidence.rule_version}</dd></div><div><dt>此前状态日</dt><dd>{evidence.history_days}</dd></div><div><dt>训练数据截至</dt><dd>{evidence.state.trained_through}</dd></div></dl>
      {evidence.context && <div className="case-context"><h3>公开背景 · {evidence.context.cutoff_date ?? '无前一状态日'}</h3><p>{evidence.context.description}</p>{evidence.context.sources.map(source => <section key={source.kind}><h4>{contextNames[source.kind] ?? source.kind}<small>{source.status === 'unavailable' ? '暂不可用' : `共 ${source.total ?? 0} 条`}</small></h4>{source.items.map(record => <article key={record.record_id}><strong>{record.title}</strong><small>{record.source_date}{record.source_time ? ` ${record.source_time}` : ''} · {record.time_basis}</small></article>)}{source.status === 'ok' && !source.items.length && <p>该日没有已入库记录。</p>}</section>)}<details><summary>未进入背景证据的数据与时间原因</summary>{evidence.context.excluded.map(excluded => <p key={excluded.kind}><b>{contextNames[excluded.kind] ?? excluded.kind}</b>：{excluded.reason}</p>)}</details></div>}
      <p className="method-note">背景记录用于复核信息环境，不参与状态或规则计算，不把统计关联写成因果。</p>
    </Panel>
    <Panel title="04 · 用历史回放验证" subtitle={`${item.replay.start_date} ～ ${item.replay.end_date} · 本地真实逐日计算`}>
      <p>{item.replay.description}</p>
      {canReplay ? <a className="case-replay-link" href={item.replay.url}>带入案例日期，前往历史回放 →</a> : <p className="method-note">当前账号缺少 market/catalog 任一功能域，不能创建或查看研究回放。</p>}
      <dl className="case-conclusion"><div><dt>统计证据</dt><dd>{item.conclusion.statistical_evidence}</dd></div><div><dt>复核方法</dt><dd>{item.conclusion.validation}</dd></div><div><dt>覆盖提示</dt><dd>{item.conclusion.coverage_note}</dd></div><div><dt>结论边界</dt><dd>{item.conclusion.limitations}</dd></div></dl>
    </Panel>
  </>
}
