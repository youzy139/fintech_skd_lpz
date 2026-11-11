import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { ErrorMessage, Panel } from './ui'

type Event = { id: number; occurred: number; actor: string; action: string; target: string; request_id: string; status: number }
type Page = { items: Event[]; next_before: number | null }
type Archive = { id: string; first_id: number; last_id: number; first_occurred: number; last_occurred: number; record_count: number; sha256: string; size: number; bucket: string; object_key: string; created: number; last_verified: number | null; verification: string }
type Overview = { enabled: boolean; policy: { retention_days: number; online_min_records: number; batch_limit: number }; online_records: number; archives: Archive[] }
const actions: Record<string, string> = { bootstrap: '管理员初始化', login: '登录成功', login_failed: '登录失败', logout: '退出登录', user_create: '创建账号', user_update: '修改账号', replay_create: '创建回放', replay_start: '启动回放', replay_pause: '暂停回放', replay_resume: '继续回放', replay_speed: '调整回放速度', replay_restart: '重开回放', replay_denied: '回放越权拦截', rule_update: '更新预警规则', rule_activate: '恢复规则版本', audit_archive: '归档审计记录' }
function AuditTable({ items }: { items: Event[] }) { return <div className="audit-table table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>目标</th><th>状态码</th><th>请求 ID</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td className="numeric">{new Date(item.occurred * 1000).toLocaleString()}</td><td>{item.actor === 'anonymous' ? '未登录' : item.actor}</td><td>{actions[item.action] || item.action}</td><td>{item.target || '—'}</td><td>{item.status || '历史记录未采集'}</td><td><code>{item.request_id || '历史记录未采集'}</code></td></tr>)}</tbody></table></div> }

export function Audit() {
  const [page, setPage] = useState<Page>({ items: [], next_before: null })
  const [overview, setOverview] = useState<Overview | null>(null)
  const [actor, setActor] = useState('')
  const [action, setAction] = useState('')
  const [filter, setFilter] = useState({ actor: '', action: '' })
  const [cursor, setCursor] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const [busy, setBusy] = useState(true)
  const [archiveBusy, setArchiveBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [expanded, setExpanded] = useState('')
  const [archivedItems, setArchivedItems] = useState<Event[]>([])
  const loadOverview = useCallback(async () => setOverview(await api<Overview>('/api/auth/audit/overview')), [])
  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError('')
    const query = new URLSearchParams({ before: String(cursor), limit: '25' }); if (filter.actor) query.set('actor', filter.actor); if (filter.action) query.set('action', filter.action)
    Promise.all([api<Page>('/api/auth/audit?' + query, controller.signal), api<Overview>('/api/auth/audit/overview', controller.signal)]).then(([records, status]) => { setPage(records); setOverview(status) }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法加载审计记录') }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [cursor, filter, revision])
  async function archiveNow() {
    setArchiveBusy(true); setError(''); setNotice('')
    try { const result = await api<{ archived: number; reason?: string }>('/api/auth/audit/archive', undefined, { method: 'POST' }); setNotice(result.archived ? `已归档 ${result.archived} 条到期记录，在线记录已按保留下限保留。` : result.reason ?? '没有需要归档的记录。'); await loadOverview(); setRevision(value => value + 1) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '审计归档失败') }
    finally { setArchiveBusy(false) }
  }
  async function verifyArchive(archive: Archive) {
    setArchiveBusy(true); setError(''); setNotice('')
    try { const result = await api<{ record_count: number }>(`/api/auth/audit/archives/${archive.id}/verify`, undefined, { method: 'POST' }); setNotice(`归档回读校验通过：${result.record_count} 条记录，SHA-256 与归档元数据一致。`); await loadOverview() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '归档校验失败'); await loadOverview().catch(() => {}) }
    finally { setArchiveBusy(false) }
  }
  async function toggleArchive(archive: Archive) {
    if (expanded === archive.id) { setExpanded(''); setArchivedItems([]); return }
    setArchiveBusy(true); setError('')
    try { const result = await api<{ items: Event[] }>(`/api/auth/audit/archives/${archive.id}/records`); setArchivedItems(result.items); setExpanded(archive.id) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取归档记录') }
    finally { setArchiveBusy(false) }
  }
  return <div className="account-page"><div className="admin-heading"><div><h2>审计记录</h2><p>记录账号、规则与回放操作的时间、操作者、结果和请求 ID；不保存密码、令牌或请求正文。</p></div></div>
    <Panel title="保留与对象归档" subtitle={overview?.enabled ? `默认将 ${overview.policy.retention_days} 天前的记录归档到 MinIO，同时至少保留最近 ${overview.policy.online_min_records.toLocaleString()} 条在线记录。` : '当前未启用 MinIO，审计记录仅保存在在线身份库。'} action={<button disabled={archiveBusy || !overview?.enabled} onClick={() => void archiveNow()}>{archiveBusy ? '正在处理…' : '归档到期记录'}</button>}>
      {overview && <p>在线 {overview.online_records.toLocaleString()} 条 · 已生成 {overview.archives.length} 个归档批次 · 每小时自动检查一次</p>}
      <p className="method-note">系统先写入对象并记录 SHA-256，再在身份库事务中登记归档并删除对应在线记录。上传或登记失败时不会按未归档数据执行删除。校验可发现内容变化，但当前 MinIO 未启用对象锁，不能宣称防管理员篡改。</p>
      {overview?.archives.map(archive => <article className="archive-row" key={archive.id}><div><strong>{new Date(archive.first_occurred * 1000).toLocaleDateString()} — {new Date(archive.last_occurred * 1000).toLocaleDateString()}</strong><small>{archive.record_count} 条 · ID {archive.first_id}–{archive.last_id} · {archive.size.toLocaleString()} 字节</small><code title={archive.sha256}>SHA-256 {archive.sha256.slice(0, 16)}…</code></div><span className={archive.verification === 'failed' ? 'negative' : ''}>{archive.verification === 'verified' ? '校验通过' : archive.verification === 'failed' ? '校验失败' : '尚未回读校验'}</span><button disabled={archiveBusy} onClick={() => void verifyArchive(archive)}>回读校验</button><button disabled={archiveBusy} onClick={() => void toggleArchive(archive)}>{expanded === archive.id ? '收起' : '查看记录'}</button></article>)}
    </Panel>
    {notice && <p className="notice" role="status">{notice}</p>}{error && <ErrorMessage message={error} />}
    {expanded && <Panel title="归档记录"><AuditTable items={archivedItems} /></Panel>}
    <Panel title="在线记录" action={<form className="account-form audit-filters" onSubmit={event => { event.preventDefault(); setCursor(0); setHistory([]); setFilter({ actor: actor.trim(), action }) }}><label>操作者<input value={actor} maxLength={40} onChange={event => setActor(event.target.value)} placeholder="完整用户名" /></label><label>操作类型<select value={action} onChange={event => setAction(event.target.value)}><option value="">全部操作</option>{Object.entries(actions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button disabled={busy}>筛选</button><button type="button" disabled={busy} onClick={() => { setCursor(0); setHistory([]); setRevision(value => value + 1) }}>刷新最新</button></form>}>
      {busy ? <p role="status">正在加载审计记录…</p> : <><AuditTable items={page.items} />{!page.items.length && <p>没有符合条件的审计记录。</p>}</>}<div className="pagination"><span>按审计游标分页</span><div><button disabled={busy || !history.length} onClick={() => { setCursor(history[history.length - 1]); setHistory(values => values.slice(0, -1)) }}>上一页</button><button disabled={busy || !!error || page.next_before === null} onClick={() => { setHistory(values => [...values, cursor]); setCursor(page.next_before!) }}>下一页</button></div></div>
    </Panel>
  </div>
}
