import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { useAuth } from './Auth'
import type { Alert, ReplayRegime } from './types'

type RuleSettings = { volatility_quantile: number; correlation_quantile: number; minimum_history: number; regime_change_enabled: boolean }
type RuleVersion = { version: string; settings: RuleSettings; created_at: string; created_by: string; active: boolean }
type Rules = { active: RuleVersion; versions: RuleVersion[] }
type ContextItem = { record_id: string; kind: string; title: string; source_path: string; source_date: string; source_time: string | null; source_timestamp: string | null; time_basis: string }
type ContextSource = { kind: string; status: string; total: number | null; items: ContextItem[] }
type EvidenceContext = { cutoff_date: string | null; status: string; description: string; sources: ContextSource[]; excluded: { kind: string; reason: string }[] }
type Evidence = { event_time: string; rule: string; rule_version: string; alert: Alert; state: ReplayRegime; previous_state: ReplayRegime | null; history_days: number; parameters: RuleSettings; evidence_links: { type: string; url: string }[]; context?: EvidenceContext }

const ruleNames: Record<string, string> = { HIGH_VOLATILITY: '高波动', HIGH_CORRELATION: '相关性异常', REGIME_CHANGE: '状态切换' }
const contextNames: Record<string, string> = { calendar: '经济日历', publication: '公众号文章', news: '新闻', indicator: '宏观指标', research: '研究摘要', social: '社交媒体' }

function percent(value: number | null | undefined) { return value === null || value === undefined ? '—' : `${(value * 100).toFixed(2)}%` }

export default function AlertCenter({ alerts, onChanged }: { alerts: Alert[]; onChanged: () => void }) {
  const { user } = useAuth()
  const [rules, setRules] = useState<Rules | null>(null)
  const [form, setForm] = useState<RuleSettings | null>(null)
  const [filter, setFilter] = useState('all')
  const [selectedVersion, setSelectedVersion] = useState('')
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [evidenceFor, setEvidenceFor] = useState<Alert | null>(null)
  const [evidenceError, setEvidenceError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const evidenceRequest = useRef(0)
  const evidenceTrigger = useRef<HTMLElement | null>(null)
  const loadRules = useCallback(async () => {
    const result = await api<Rules>('/api/alert-rules')
    setRules(result); setForm(result.active.settings); setSelectedVersion(result.active.version)
  }, [])
  useEffect(() => { loadRules().catch(reason => setError(reason instanceof Error ? reason.message : '无法加载预警规则')) }, [loadRules])

  useEffect(() => {
    if (!evidenceFor) return
    const previousOverflow = document.body.style.overflow
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') closeEvidence() }
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [evidenceFor])

  async function save() {
    if (!form) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<RuleVersion>('/api/alert-rules', undefined, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      await loadRules(); onChanged(); setNotice(`已启用 ${result.version}，当前历史预警已按此版本重新计算`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '规则保存失败') }
    finally { setBusy(false) }
  }

  async function activate() {
    if (!selectedVersion) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<RuleVersion>(`/api/alert-rules/${selectedVersion}/activate`, undefined, { method: 'POST' })
      await loadRules(); onChanged(); setNotice(`已恢复 ${result.version}`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '版本恢复失败') }
    finally { setBusy(false) }
  }

  async function showEvidence(alert: Alert, trigger?: HTMLElement) {
    const request = ++evidenceRequest.current
    evidenceTrigger.current = trigger ?? evidenceTrigger.current ?? document.activeElement as HTMLElement | null
    setEvidenceFor(alert); setEvidence(null); setEvidenceError(''); setBusy(true)
    try {
      const result = await api<Evidence>(`/api/alerts/${alert.rule}/${alert.date}`)
      if (request === evidenceRequest.current) setEvidence(result)
    } catch (reason) {
      if (request === evidenceRequest.current) setEvidenceError(reason instanceof Error ? reason.message : '证据加载失败')
    } finally {
      if (request === evidenceRequest.current) setBusy(false)
    }
  }

  function closeEvidence() {
    evidenceRequest.current += 1
    setEvidenceFor(null); setEvidence(null); setEvidenceError(''); setBusy(false)
    evidenceTrigger.current?.focus()
  }

  const filtered = filter === 'all' ? alerts : alerts.filter(item => item.level === filter)
  return <>
    <section className="panel"><div className="panel-head"><div><h2>确定性预警规则</h2><p>阈值只影响预警，不改变市场状态模型；保存后重新计算当前历史预警视图</p></div>{rules && <code>{rules.active.version}</code>}</div>
      {form && <div className="account-form"><label>波动率历史分位<input aria-label="波动率历史分位" type="number" min={50} max={99} step={1} disabled={user.role !== 'admin' || busy} value={form.volatility_quantile * 100} onChange={event => setForm({ ...form, volatility_quantile: Number(event.target.value) / 100 })} /></label><label>相关性历史分位<input aria-label="相关性历史分位" type="number" min={50} max={99} step={1} disabled={user.role !== 'admin' || busy} value={form.correlation_quantile * 100} onChange={event => setForm({ ...form, correlation_quantile: Number(event.target.value) / 100 })} /></label><label>最少历史状态日<input aria-label="最少历史状态日" type="number" min={10} max={1000} disabled={user.role !== 'admin' || busy} value={form.minimum_history} onChange={event => setForm({ ...form, minimum_history: Number(event.target.value) })} /></label><label><input type="checkbox" disabled={user.role !== 'admin' || busy} checked={form.regime_change_enabled} onChange={event => setForm({ ...form, regime_change_enabled: event.target.checked })} />启用状态切换预警</label>{user.role === 'admin' && <button disabled={busy} onClick={() => void save()}>保存并启用新版本</button>}</div>}
      {rules && <div className="account-form"><label>历史规则版本<select aria-label="历史规则版本" value={selectedVersion} onChange={event => setSelectedVersion(event.target.value)}>{rules.versions.map(item => <option key={item.version} value={item.version}>{item.version} · {item.created_by}{item.active ? ' · 当前' : ''}</option>)}</select></label>{user.role === 'admin' && <button disabled={busy || selectedVersion === rules.active.version} onClick={() => void activate()}>恢复所选版本</button>}</div>}
      {user.role !== 'admin' && <p className="method-note">当前账号只读，不能修改或恢复规则。</p>}
    </section>
    {error && <div className="error" role="alert">{error}</div>}{notice && <p role="status">{notice}</p>}
    <section className="panel"><div className="panel-head"><div><h2>预警记录</h2><p>高波动、相关性异常与状态切换；每条记录可核对当日状态证据</p></div><select aria-label="预警级别" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部级别</option><option value="high">高级别</option><option value="medium">中级别</option></select></div>
      {filtered.length ? <div className="alert-list">{filtered.map((item, index) => <article className="alert" key={`${item.date}-${item.rule}-${index}`}><span className={`alert-level ${item.level}`}>{item.level === 'high' ? '高' : '中'}</span><div><h3>{item.title}<small>{ruleNames[item.rule] ?? item.rule} · {item.rule_version ?? '历史版本未记录'}</small></h3><p>{item.evidence}</p><button disabled={busy} onClick={event => void showEvidence(item, event.currentTarget)}>查看证据</button></div><time>{item.date}</time></article>)}</div> : <div className="empty">当前筛选条件下暂无预警</div>}
    </section>
    {evidenceFor && <div className="evidence-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closeEvidence() }}>
      <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title">
        <div className="evidence-drawer-head"><div><p className="eyebrow">ALERT EVIDENCE</p><h2 id="evidence-drawer-title">{evidenceFor.title} · 证据</h2><p>{evidenceFor.date}{evidence && ` · ${evidence.rule_version}`}</p></div><button autoFocus aria-label="关闭证据抽屉" onClick={closeEvidence}>关闭</button></div>
        <div className="evidence-drawer-body">
          {busy && <p role="status">正在加载证据…</p>}
          {evidenceError && <div className="error" role="alert">{evidenceError}<button onClick={() => void showEvidence(evidenceFor)}>重试</button></div>}
          {evidence && <>
            <dl className="replay-facts"><div><dt>实际值</dt><dd>{evidence.rule === 'HIGH_CORRELATION' ? evidence.alert.value?.toFixed(3) ?? '—' : percent(evidence.alert.value)}</dd></div><div><dt>触发阈值</dt><dd>{evidence.rule === 'HIGH_CORRELATION' ? evidence.alert.threshold?.toFixed(3) ?? '—' : percent(evidence.alert.threshold)}</dd></div><div><dt>当日状态</dt><dd>{evidence.state.label}</dd></div><div><dt>前一状态</dt><dd>{evidence.previous_state?.label ?? '—'}</dd></div><div><dt>此前状态日</dt><dd>{evidence.history_days}</dd></div><div><dt>模型版本</dt><dd>{evidence.state.model_version}</dd></div><div><dt>训练数据截至</dt><dd>{evidence.state.trained_through}</dd></div></dl>
            <p className="method-note">贡献值和分位阈值是统计证据，不代表因果关系。</p>
            {evidence.context && <div className="context-evidence"><h3>截至前一状态日的公开背景 {evidence.context.cutoff_date && `· ${evidence.context.cutoff_date}`}</h3><p>{evidence.context.description}</p>
              {evidence.context.sources.map(source => <section key={source.kind}><h4>{contextNames[source.kind] ?? source.kind}<small>{source.status === 'unavailable' ? '暂不可用' : `共 ${source.total ?? 0} 条，最多展示 6 条`}</small></h4>{source.items.map(item => <article key={item.record_id}><strong>{item.title}</strong><small>{item.source_date}{item.source_time ? ` ${item.source_time}` : ''} · {item.time_basis}</small></article>)}{source.status === 'ok' && !source.items.length && <p>该日没有已入库记录。</p>}</section>)}
              <details><summary>未进入证据链的数据与时间原因</summary>{evidence.context.excluded.map(item => <p key={item.kind}><b>{contextNames[item.kind] ?? item.kind}</b>：{item.reason}</p>)}</details>
            </div>}
            {evidence.evidence_links.map(link => <a key={link.url} href={link.url} target="_blank" rel="noreferrer">查看当日原始状态 API</a>)}
          </>}
        </div>
      </aside>
    </div>}
  </>
}
