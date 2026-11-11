import { useEffect, useState } from 'react'
import Icon from './Icon'
import { useAuth } from './Auth'
import { directionTone, percent, numeric } from './format'
import { allowedPages, pages, type Page } from './navigation'
import { scrollExactlyToTop } from './motion'
import type { Regime } from './types'

const descriptions: Partial<Record<Page, string>> = {
  home: '聚合市场状态、数据基础与研究入口。',
  overview: '从资产走势、市场状态与风险信号进入研究。',
  regimes: '沿时间复核市场状态、训练边界与特征变化。',
  features: '比较多资产特征的历史变化与标准化偏离。',
  alerts: '按确定性规则定位异常，并核对统计与背景证据。',
  replay: '按事件时间重现当时可见数据形成的判断。',
  data: '检索多源记录、原始字段、标签与来源文件。',
  accounts: '管理用户角色、功能域和账号状态。',
  audit: '复核管理操作、回放控制与归档证据。',
  system: '检查依赖连接、缓存分工与熔断状态。',
}

export default function Workspace({ page, onNavigate, latest, alertCount, children }: { page: Page; onNavigate: (page: Page) => void; latest?: Regime; alertCount: number; children: React.ReactNode }) {
  const { user } = useAuth()
  const [menu, setMenu] = useState(false)
  const [showBackToTop, setShowBackToTop] = useState(false)
  const current = pages.find(item => item[0] === page)!
  const allowed = allowedPages(user.domains, user.role)
  useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 420)
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  const navigate = (next: Page) => { onNavigate(next); setMenu(false) }
  return <div className="shell">
    <a className="skip-link" href="#workspace-content" onClick={event => { event.preventDefault(); document.getElementById('workspace-content')?.focus() }}>跳转到主要内容</a>
    {menu && <button className="nav-scrim" aria-label="关闭导航" onClick={() => setMenu(false)} />}
    <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
      <div className="sidebar-heading"><span>MARKETLENS</span><small>专业市场研究终端</small></div>
      {(['research', 'system'] as const).map(group => {
        const items = pages.filter(([id, , , , section]) => section === group && allowed.includes(id))
        if (!items.length) return null
        return <nav aria-label={group === 'system' ? '系统管理' : '市场研究'} key={group}><p className="nav-caption">{group === 'system' ? '系统管理' : '市场研究'}</p>{items.map(([id, label, icon]) => <button key={id} className={page === id ? 'active' : ''} aria-current={page === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon name={icon} /><span>{label}</span>{id === 'alerts' && alertCount > 0 && <b>{alertCount}</b>}</button>)}</nav>
      })}
      <div className="sidebar-foot"><span className="history-dot" />历史数据研究环境<small>事件时间驱动 · 非实时行情</small></div>
    </aside>
    <main className="main" id="workspace-content" tabIndex={-1}>
      <div className="workspace-topline"><button className="mobile-menu" aria-label="打开导航" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="menu" /></button><span>MarketLens <i>/</i> {current[1]}</span><span className="environment-label">RESEARCH · v0.3.5</span></div>
      <div className="market-context" aria-label="市场环境摘要">
        {latest ? <><span className="context-state"><i />{latest.label}</span><span>年化波动 <b>{percent(latest.features.volatility)}</b></span><span>中期动量 <b className={directionTone(latest.features.momentum)}>{percent(latest.features.momentum)}</b></span><span>资产相关性 <b>{numeric(latest.features.correlation, 3)}</b></span><span className="context-date">观测日 <b>{latest.date}</b></span></> : <span className="context-state"><i />多源数据与研究环境</span>}
        <span className="context-warning">历史观测 · 非实时行情</span>
      </div>
      <header className="page-header"><div><p className="eyebrow">{current[3]}</p><h1>{current[1]}</h1><p className="page-description">{descriptions[page]}</p></div><Icon name={current[2]} className="page-header-icon" /></header>
      {children}
      <footer><span>MarketLens · 研究始于证据</span><span>市场状态用于研究辅助，不构成投资建议</span></footer>
    </main>
    <button className={`back-to-top ${showBackToTop ? 'visible' : ''}`} aria-label="回到顶部" onClick={scrollExactlyToTop}><Icon name="arrow" /></button>
  </div>
}
