import { useEffect, useState } from 'react'
import { api } from './api'
import { useAuth } from './Auth'
import { ErrorMessage } from './ui'

type AccountUser = { username: string; role: 'observer' | 'analyst' | 'admin'; domains: string[]; assets: string[]; sources: string[]; expires_at: number | null; can_control_replay: boolean; enabled: boolean }
const scopeList = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean)
const roles: Record<string, string> = { observer: '观察者', analyst: '分析员', admin: '管理员' }

export default function Accounts() {
  const { user } = useAuth()
  const [users, setUsers] = useState<AccountUser[]>([])
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<AccountUser['role']>('observer')
  const [domains, setDomains] = useState(['market', 'catalog'])
  const [assets, setAssets] = useState('*')
  const [sources, setSources] = useState('*')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const load = () => api<AccountUser[]>('/api/auth/users').then(setUsers)
  useEffect(() => { load().catch(() => setError('无法加载用户列表')) }, [])
  async function save(action: () => Promise<unknown>) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await load(); setPassword(''); setNotice('已保存；修改已有账号会立即撤销其原登录状态。') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') }
    finally { setBusy(false) }
  }
  return <div className="account-page"><p className="page-note">观察者只读；分析员可控制回放；管理员管理账号。回放需要市场和数据目录两个范围。</p>{error && <ErrorMessage message={error} />}{notice && <p className="notice" role="status">{notice}</p>}
    <section className="panel"><div className="panel-head"><div><h2>新增账号</h2><p>初始密码只在本次提交中传输，不写入浏览器存储。范围 ID 用逗号分隔，* 表示全部。</p></div></div><div className="panel-body"><form className="account-form" onSubmit={event => { event.preventDefault(); void save(() => api('/api/auth/users', undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: name, password, role, domains, assets: scopeList(assets), sources: scopeList(sources) }) })) }}><label>用户名<input required value={name} onChange={event => setName(event.target.value)} /></label><label>初始密码<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /></label><label>角色<select aria-label="新账号角色" value={role} onChange={event => { setRole(event.target.value as AccountUser['role']); if (event.target.value === 'admin') { setDomains(['market', 'catalog']); setAssets('*'); setSources('*') } }}>{Object.entries(roles).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>{['market', 'catalog'].map(domain => <label key={domain}><input type="checkbox" checked={domains.includes(domain)} disabled={role === 'admin'} onChange={event => setDomains(current => event.target.checked ? [...current, domain] : current.filter(value => value !== domain))} />{domain === 'market' ? '市场分析' : '数据目录'}</label>)}<label>资产 ID<input value={assets} disabled={role === 'admin'} onChange={event => setAssets(event.target.value)} /></label><label>来源 ID<input value={sources} disabled={role === 'admin'} onChange={event => setSources(event.target.value)} /></label><button disabled={busy}>创建账号</button></form></div></section>
    <section className="panel"><div className="panel-head"><div><h2>已有账号</h2><p>角色或权限修改会撤销该账号已有会话。</p></div></div><div className="panel-body account-list">{users.map(account => <AccountRow key={JSON.stringify(account)} account={account} self={account.username === user.username} busy={busy} onSave={settings => void save(() => api(`/api/auth/users/${encodeURIComponent(account.username)}`, undefined, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) }))} />)}</div></section>
  </div>
}

function AccountRow({ account, self, busy, onSave }: { account: AccountUser; self: boolean; busy: boolean; onSave: (settings: unknown) => void }) {
  const [role, setRole] = useState(account.role)
  const [domains, setDomains] = useState(account.domains)
  const [assets, setAssets] = useState(account.assets.join(','))
  const [sources, setSources] = useState(account.sources.join(','))
  const [enabled, setEnabled] = useState(account.enabled)
  const [password, setPassword] = useState('')
  return <form className="account-form" onSubmit={event => { event.preventDefault(); onSave({ role, domains, assets: scopeList(assets), sources: scopeList(sources), enabled, ...(password ? { password } : {}) }) }}><strong>{account.username}{self ? '（当前账号）' : ''}</strong><select aria-label={`${account.username}角色`} disabled={self} value={role} onChange={event => { setRole(event.target.value as AccountUser['role']); if (event.target.value === 'admin') { setDomains(['market', 'catalog']); setAssets('*'); setSources('*') } }}>{Object.entries(roles).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>{['market', 'catalog'].map(domain => <label key={domain}><input type="checkbox" disabled={self || role === 'admin'} checked={domains.includes(domain)} onChange={event => setDomains(current => event.target.checked ? [...current, domain] : current.filter(value => value !== domain))} />{domain === 'market' ? '市场分析' : '数据目录'}</label>)}<label>资产 ID<input aria-label={`${account.username}资产范围`} disabled={self || role === 'admin'} value={assets} onChange={event => setAssets(event.target.value)} /></label><label>来源 ID<input aria-label={`${account.username}来源范围`} disabled={self || role === 'admin'} value={sources} onChange={event => setSources(event.target.value)} /></label><label><input type="checkbox" checked={enabled} disabled={self} onChange={event => setEnabled(event.target.checked)} />启用</label><input aria-label={`${account.username}新密码`} type="password" placeholder="新密码（留空不改）" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /><button disabled={busy}>保存</button></form>
}
