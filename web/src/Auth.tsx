import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'
import { Audit } from './Audit'

type User = { username: string; role: 'observer' | 'analyst' | 'admin'; domains: string[]; expires_at: number | null; can_control_replay: boolean }
const developer: User = { username: 'local-dev', role: 'admin', domains: ['market', 'catalog'], expires_at: null, can_control_replay: true }
const Context = createContext<{ user: User; enabled: boolean }>({ user: developer, enabled: false })
export const useAuth = () => useContext(Context)
const roles: Record<string, string> = { observer: '观察者', analyst: '分析员', admin: '管理员' }

export function AuthBoundary({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<{ enabled: boolean; setup_required: boolean } | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [accounts, setAccounts] = useState(false)
  const [audit, setAudit] = useState(false)

  useEffect(() => {
    let disposed = false
    api<{ enabled: boolean; setup_required: boolean }>('/api/auth/status').then(async result => {
      if (disposed) return
      setStatus(result)
      if (!result.enabled) setUser(developer)
      else if (!result.setup_required) {
        try { const current = await api<User>('/api/auth/me'); if (!disposed) setUser(current) } catch { /* Login form remains available. */ }
      }
    }).catch(() => setError('无法连接身份服务，请刷新重试'))
    const expired = () => { setUser(null); setAccounts(false); setAudit(false); setError('登录已失效，请重新登录') }
    window.addEventListener('marketlens:unauthorized', expired)
    return () => { disposed = true; window.removeEventListener('marketlens:unauthorized', expired) }
  }, [])

  useEffect(() => {
    if (!user?.expires_at) return
    const timer = setTimeout(() => { setUser(null); setAccounts(false); setError('登录已到期，请重新登录') }, Math.max(0, user.expires_at * 1000 - Date.now()))
    return () => clearTimeout(timer)
  }, [user])

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const current = await api<User>(status?.setup_required ? '/api/auth/bootstrap' : '/api/auth/login', undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, ...(status?.setup_required ? { setup_code: code } : {}) }) })
      setPassword(''); setCode(''); setStatus({ enabled: true, setup_required: false }); setUser(current)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败') }
    finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true)
    try { await api('/api/auth/logout', undefined, { method: 'POST' }); setUser(null); setAccounts(false); setAudit(false); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '退出失败，请重试') }
    finally { setBusy(false) }
  }

  if (!status) return <main className="boot"><h1>MarketLens</h1><p>{error || '正在检查登录状态…'}</p></main>
  if (!user) return <main className="auth-screen"><form className="auth-card" onSubmit={event => void submit(event)}><span className="eyebrow">MARKETLENS</span><h1>{status.setup_required ? '创建首位管理员' : '登录市场工作台'}</h1><p>{status.setup_required ? '使用本机初始化凭据设置管理员账号。' : '登录后按账号权限查看市场、数据与历史回放。'}</p>{status.setup_required && <label>初始化凭据<input required autoComplete="off" value={code} onChange={event => setCode(event.target.value)} type="password" /></label>}<label>用户名<input required autoComplete="username" value={username} maxLength={40} onChange={event => setUsername(event.target.value)} /></label><label>密码<input required autoComplete={status.setup_required ? 'new-password' : 'current-password'} minLength={status.setup_required ? 12 : 1} maxLength={128} type="password" value={password} onChange={event => setPassword(event.target.value)} /></label>{status.setup_required && <small>密码至少 12 位；用户名支持字母、数字、点、下划线和短横线。</small>}{error && <p className="error" role="alert">{error}</p>}<button disabled={busy} type="submit">{busy ? '正在验证…' : status.setup_required ? '创建并进入' : '登录'}</button></form></main>
  return <Context.Provider value={{ user, enabled: status.enabled }}><div className="account-bar"><span>{status.enabled ? `${user.username} · ${roles[user.role]}` : '本地开发模式 · 未启用认证'}</span><small>{user.domains.includes('market') ? '市场分析 ' : ''}{user.domains.includes('catalog') ? '数据目录' : ''}</small>{status.enabled && <>{user.role === 'admin' && <button onClick={() => { setAccounts(!accounts); setAudit(false) }}>{accounts ? '返回平台' : '账号权限'}</button>}{user.role === 'admin' && <button onClick={() => { setAudit(!audit); setAccounts(false) }}>{audit ? '返回平台' : '审计记录'}</button>}<button disabled={busy} onClick={() => void logout()}>退出登录</button></>}</div>{error && <div className="error" role="alert">{error}</div>}{audit ? <Audit /> : accounts ? <Accounts /> : <div key={user.username}>{children}</div>}</Context.Provider>
}

function Accounts() {
  const { user } = useAuth()
  const [users, setUsers] = useState<(User & { enabled: boolean })[]>([])
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('observer')
  const [domains, setDomains] = useState(['market', 'catalog'])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const load = () => api<typeof users>('/api/auth/users').then(setUsers)
  useEffect(() => { load().catch(() => setError('无法加载用户列表')) }, [])
  async function save(action: () => Promise<unknown>) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await load(); setPassword(''); setNotice('已保存；修改已有账号会立即撤销其原登录状态。') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') }
    finally { setBusy(false) }
  }
  return <main className="account-page"><h1>账号与数据权限</h1><p>观察者只读；分析员可控制回放；管理员管理账号。回放需要市场和数据目录两个范围。</p>{error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}<section className="panel"><h2>新增账号</h2><form className="account-form" onSubmit={event => { event.preventDefault(); void save(() => api('/api/auth/users', undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: name, password, role, domains }) })) }}><label>用户名<input required value={name} onChange={event => setName(event.target.value)} /></label><label>初始密码<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /></label><label>角色<select value={role} onChange={event => { setRole(event.target.value); if (event.target.value === 'admin') setDomains(['market', 'catalog']) }}>{Object.entries(roles).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>{['market', 'catalog'].map(domain => <label key={domain}><input type="checkbox" checked={domains.includes(domain)} disabled={role === 'admin'} onChange={event => setDomains(current => event.target.checked ? [...current, domain] : current.filter(value => value !== domain))} />{domain === 'market' ? '市场分析' : '数据目录'}</label>)}<button disabled={busy}>创建账号</button></form></section><section className="panel"><h2>已有账号</h2>{users.map(account => <AccountRow key={JSON.stringify(account)} account={account} self={account.username === user.username} busy={busy} onSave={settings => void save(() => api(`/api/auth/users/${encodeURIComponent(account.username)}`, undefined, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) }))} />)}</section></main>
}

function AccountRow({ account, self, busy, onSave }: { account: User & { enabled: boolean }; self: boolean; busy: boolean; onSave: (settings: unknown) => void }) {
  const [role, setRole] = useState(account.role)
  const [domains, setDomains] = useState(account.domains)
  const [enabled, setEnabled] = useState(account.enabled)
  const [password, setPassword] = useState('')
  return <form className="account-form" onSubmit={event => { event.preventDefault(); onSave({ role, domains, enabled, ...(password ? { password } : {}) }) }}><strong>{account.username}{self ? '（当前账号）' : ''}</strong><select aria-label={`${account.username}角色`} disabled={self} value={role} onChange={event => { setRole(event.target.value as User['role']); if (event.target.value === 'admin') setDomains(['market', 'catalog']) }}>{Object.entries(roles).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>{['market', 'catalog'].map(domain => <label key={domain}><input type="checkbox" disabled={self || role === 'admin'} checked={domains.includes(domain)} onChange={event => setDomains(current => event.target.checked ? [...current, domain] : current.filter(value => value !== domain))} />{domain === 'market' ? '市场分析' : '数据目录'}</label>)}<label><input type="checkbox" checked={enabled} disabled={self} onChange={event => setEnabled(event.target.checked)} />启用</label><input aria-label={`${account.username}新密码`} type="password" placeholder="新密码（留空不改）" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /><button disabled={busy}>保存</button></form>
}
