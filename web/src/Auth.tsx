import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'
import Icon from './Icon'

type User = { username: string; role: 'observer' | 'analyst' | 'admin'; domains: string[]; assets: string[]; sources: string[]; expires_at: number | null; can_control_replay: boolean }
const developer: User = { username: 'local-dev', role: 'admin', domains: ['market', 'catalog'], assets: ['*'], sources: ['*'], expires_at: null, can_control_replay: true }
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
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let disposed = false
    setError('')
    api<{ enabled: boolean; setup_required: boolean }>('/api/auth/status').then(async result => {
      if (disposed) return
      setStatus(result)
      if (!result.enabled) setUser(developer)
      else if (!result.setup_required) {
        try { const current = await api<User>('/api/auth/me'); if (!disposed) setUser(current) } catch { /* Login form remains available. */ }
      }
    }).catch(() => setError('无法连接身份服务，请刷新重试'))
    const expired = () => { setUser(null); setError('登录已失效，请重新登录') }
    window.addEventListener('marketlens:unauthorized', expired)
    return () => { disposed = true; window.removeEventListener('marketlens:unauthorized', expired) }
  }, [attempt])
  useEffect(() => {
    if (!user?.expires_at) return
    const timer = setTimeout(() => { setUser(null); setError('登录已到期，请重新登录') }, Math.max(0, user.expires_at * 1000 - Date.now()))
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
    try { await api('/api/auth/logout', undefined, { method: 'POST' }); setUser(null); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '退出失败，请重试') }
    finally { setBusy(false) }
  }
  if (!status) return <main className="boot"><div className="boot-brand">M<span>·</span></div><h1>MarketLens</h1><p role={error ? 'alert' : 'status'}>{error || '正在检查登录状态…'}</p>{error && <button onClick={() => setAttempt(value => value + 1)}>重新连接身份服务</button>}</main>
  if (!user) return <main className="auth-screen"><section className="auth-intro"><span className="auth-brand">M<span>·</span></span><p className="eyebrow">MARKETLENS TERMINAL</p><h1>市场状态研究，<br />从可信证据开始。</h1><p>多资产行情 · Walk-forward 状态识别<br />确定性预警 · 事件时间回放</p><small>历史数据研究环境，不提供实时行情或买卖指令。</small></section><form className="auth-card" onSubmit={event => void submit(event)}><span className="eyebrow">SECURE WORKSPACE</span><h2>{status.setup_required ? '创建首位管理员' : '登录市场工作台'}</h2><p>{status.setup_required ? '使用本机初始化凭据设置管理员账号。' : '登录后按账号权限查看市场、数据与历史回放。'}</p>{status.setup_required && <label>初始化凭据<input required autoComplete="off" value={code} onChange={event => setCode(event.target.value)} type="password" /></label>}<label>用户名<input required autoComplete="username" value={username} maxLength={40} onChange={event => setUsername(event.target.value)} /></label><label>密码<input required autoComplete={status.setup_required ? 'new-password' : 'current-password'} minLength={status.setup_required ? 12 : 1} maxLength={128} type="password" value={password} onChange={event => setPassword(event.target.value)} /></label>{status.setup_required && <small>密码至少 12 位；用户名支持字母、数字、点、下划线和短横线。</small>}{error && <p className="error" role="alert">{error}</p>}<button disabled={busy} type="submit">{busy ? '正在验证…' : status.setup_required ? '创建并进入' : '登录'}<Icon name="arrow" /></button></form></main>
  return <Context.Provider value={{ user, enabled: status.enabled }}><div className="app-frame">
    <div className="account-bar"><a className="account-brand" href="#/home"><span>M·</span>MarketLens<small>市场状态终端</small></a><span className="account-environment">{status.enabled ? '研究与监控环境' : '本地开发模式 · 未启用认证'}</span><small>{user.domains.includes('market') ? '市场分析 ' : ''}{user.domains.includes('catalog') ? '数据目录' : ''}</small><span className="account-user">{user.username} · {roles[user.role]}</span>{status.enabled && <>{user.role === 'admin' && <button onClick={() => { window.location.hash = '/accounts' }}>账号权限</button>}{user.role === 'admin' && <button onClick={() => { window.location.hash = '/audit' }}>审计记录</button>}{user.role === 'admin' && <button onClick={() => { window.location.hash = '/system' }}>系统监控</button>}<button disabled={busy} onClick={() => void logout()}><Icon name="logout" />退出登录</button></>}</div>
    {error && <div className="global-error" role="alert">{error}</div>}
    <div key={user.username}>{children}</div>
  </div></Context.Provider>
}
