import { useEffect, useState } from 'react'
import { api } from './api'

type Event = { id: number; occurred: number; actor: string; action: string; target: string; request_id: string; status: number }
type Page = { items: Event[]; next_before: number | null }
const actions: Record<string, string> = { bootstrap: '管理员初始化', login: '登录成功', login_failed: '登录失败', logout: '退出登录', user_create: '创建账号', user_update: '修改账号', replay_create: '创建回放', replay_start: '启动回放', replay_pause: '暂停回放', replay_resume: '继续回放', replay_speed: '调整回放速度', replay_restart: '重开回放' }

actions.replay_denied = '回放越权拦截'

export function Audit() {
  const [page, setPage] = useState<Page>({ items: [], next_before: null })
  const [actor, setActor] = useState('')
  const [action, setAction] = useState('')
  const [filter, setFilter] = useState({ actor: '', action: '' })
  const [cursor, setCursor] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    const query = new URLSearchParams({ before: String(cursor), limit: '25' })
    if (filter.actor) query.set('actor', filter.actor)
    if (filter.action) query.set('action', filter.action)
    api<Page>('/api/auth/audit?' + query, controller.signal).then(setPage).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法加载审计记录')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [cursor, filter, revision])
  return <main className="account-page"><h1>审计记录</h1><p>仅管理员可查看。记录账号事件与回放操作的时间、操作者、结果和请求 ID；不保存密码、令牌或请求正文。</p><form className="account-form" onSubmit={event => { event.preventDefault(); setCursor(0); setHistory([]); setFilter({ actor: actor.trim(), action }) }}><label>操作者<input value={actor} maxLength={40} onChange={event => setActor(event.target.value)} placeholder="完整用户名" /></label><label>操作类型<select value={action} onChange={event => setAction(event.target.value)}><option value="">全部操作</option>{Object.entries(actions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button disabled={busy}>筛选</button><button type="button" disabled={busy} onClick={() => { setCursor(0); setHistory([]); setRevision(value => value + 1) }}>刷新最新</button></form>{error ? <p role="alert" className="error">{error}</p> : busy ? <p role="status">正在加载审计记录…</p> : <><div className="audit-table"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>目标</th><th>状态码</th><th>请求 ID</th></tr></thead><tbody>{page.items.map(item => <tr key={item.id}><td>{new Date(item.occurred * 1000).toLocaleString()}</td><td>{item.actor === 'anonymous' ? '未登录' : item.actor}</td><td>{actions[item.action] || item.action}</td><td>{item.target || '—'}</td><td>{item.status || '历史记录未采集'}</td><td><code>{item.request_id || '历史记录未采集'}</code></td></tr>)}</tbody></table></div>{!page.items.length && <p>没有符合条件的审计记录。</p>}</>}<div className="account-form"><button disabled={busy || !history.length} onClick={() => { setCursor(history[history.length - 1]); setHistory(values => values.slice(0, -1)) }}>上一页</button><button disabled={busy || !!error || page.next_before === null} onClick={() => { setHistory(values => [...values, cursor]); setCursor(page.next_before!) }}>下一页</button></div><small>当前记录位于单主机身份库，尚无防篡改归档或自动保留策略。</small></main>
}
