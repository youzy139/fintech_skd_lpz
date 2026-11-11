import { useEffect, useState } from 'react'
import { scrollExactlyToTop } from './motion'
import { percent, numeric } from './format'
import Icon from './Icon'
import type { Page } from './navigation'
import type { HomeSummary } from './types'

export default function Landing({ data, onEnter, onNavigate, error, onRetry }: { data: HomeSummary | null; onEnter: () => void; onNavigate: (page: Page) => void; error: string; onRetry: () => void }) {
  const [showBackToTop, setShowBackToTop] = useState(false)
  useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 360)
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  const latest = data?.latest
  const scroll = (event: React.MouseEvent, id: string) => { event.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }) }
  return <div className="landing" id="top">
    <nav className="landing-nav" aria-label="首页导航"><a className="landing-brand" href="#/home"><span className="brand-mark">M<span>·</span></span>MarketLens</a><div className="landing-links"><a href="#capabilities" onClick={event => scroll(event, 'capabilities')}>研究工具</a><a href="#method" onClick={event => scroll(event, 'method')}>分析方法</a><a href="#data" onClick={event => scroll(event, 'data')}>数据基础</a></div><button className="nav-entry" onClick={onEnter}>进入工作台 <Icon name="arrow" /></button></nav>
    <main><section className="hero"><div className="hero-copy"><div className="hero-badge"><span />MARKET REGIME RESEARCH</div><h1>读懂市场状态，<br /><em>让判断有据可循。</em></h1><p>把多资产行情、状态模型与风险证据放在同一视野。观察市场如何变化，也理解每一次判断从何而来。</p><div className="hero-actions"><button className="primary-action" onClick={onEnter}>进入市场工作台 <Icon name="arrow" /></button><button className="hero-secondary" onClick={() => onNavigate('replay')}><Icon name="replay" />探索历史回放</button></div><div className="hero-proof"><span>真实历史数据</span><span>逐日滚动建模</span><span>证据可追溯</span></div></div>
      <div className="research-preview"><div className="preview-heading"><span><i />MARKET OBSERVATION</span><span>01 / 市场快照</span></div><div className="preview-date">{latest?.date ?? '等待市场数据'}</div><div className="preview-label">当前市场状态</div><h2>{latest?.label ?? (error ? '摘要暂不可用' : '正在连接数据')}</h2><div className="preview-confidence"><span>模型置信度</span><strong>{percent(latest?.confidence, 1)}</strong><div><i style={{ width: `${Math.min(100, Math.max(0, (latest?.confidence ?? 0) * 100))}%` }} /></div></div><div className="preview-numbers"><div><span>年化波动率</span><b>{percent(latest?.features.volatility)}</b></div><div><span>60 日动量</span><b>{percent(latest?.features.momentum)}</b></div><div><span>资产相关性</span><b>{numeric(latest?.features.correlation, 3)}</b></div></div><div className="preview-method"><span>观察</span><Icon name="arrow" /><span>识别</span><Icon name="arrow" /><span>复核</span></div><p className="preview-foot">历史观测 · 数学模型识别 · 非实时行情</p>{error && <div className="error" role="alert">{error}<button onClick={onRetry}>重新加载摘要</button></div>}</div>
    </section><section className="data-ribbon" id="data"><div><span>DATA FOUNDATION</span><p>让分散的数据，形成连贯的视野。</p></div><div><strong>{data?.loaded_assets.toLocaleString() ?? '—'}<small>个</small></strong><span>有效资产序列</span></div><div><strong>{data?.total_rows.toLocaleString() ?? '—'}</strong><span>有效行情记录</span></div><div><strong>{data?.state_count.toLocaleString() ?? '—'}</strong><span>历史状态日</span></div></section>
    <section className="capabilities" id="capabilities"><div className="section-heading"><span>THE RESEARCH TOOLKIT</span><h2>从一个更清晰的视角，观察市场。</h2><p>从总览到证据，从当日观测到历史验证。</p></div><div className="capability-grid">{[
      ['01', 'regimes', '识别市场环境', '观察市场状态与特征热力图，理解不同阶段的波动、动量和资产联动。', 'regimes'],
      ['02', 'alerts', '追溯风险证据', '查看触发规则、历史阈值与当日状态，关联当时已公开的事件背景。', 'alerts'],
      ['03', 'replay', '重现历史过程', '按事件时间逐日重新计算，在当时可见的数据范围内检验判断。', 'replay'],
    ].map(([number, icon, title, description, page]) => <article key={number}><div><Icon name={icon} /><span>{number}</span></div><h3>{title}</h3><p>{description}</p><button onClick={() => onNavigate(page as Page)}>开始探索 <Icon name="arrow" /></button></article>)}</div></section>
    <section className="method" id="method"><div><p className="eyebrow">METHOD, NOT MYSTERY</p><h2>每一个结论，<br />都有一条可复核的路径。</h2><p>特征由数学计算，状态由滚动模型识别，预警由确定性规则产生。训练数据严格早于识别当日。</p><button className="text-button" onClick={() => onNavigate('features')}>查看特征与口径 <Icon name="arrow" /></button></div><ol className="method-steps"><li><span>01</span><div><h3>保留数据与时间</h3><p>原始字段、来源文件和事件日期可追溯。</p></div></li><li><span>02</span><div><h3>计算多资产特征</h3><p>收益、波动、动量、趋势与相关性。</p></div></li><li><span>03</span><div><h3>逐日识别与规则预警</h3><p>Walk-forward · PCA / KMeans · 历史分位阈值。</p></div></li><li><span>04</span><div><h3>交叉复核与历史验证</h3><p>证据抽屉、状态热力图与三通道历史回放。</p></div></li></ol></section>
    <section className="landing-cta"><span>SEE THE CONTEXT. FOLLOW THE EVIDENCE.</span><h2>下一次研究，从全貌开始。</h2><button className="primary-action" onClick={onEnter}>打开研究工作台 <Icon name="arrow" /></button></section></main>
    <footer className="landing-footer"><a className="landing-brand" href="#/home">MarketLens<span>市场状态研究平台</span></a><p>2026 上海科技大学金融科技竞赛 · 历史数据研究 · 不构成投资建议</p></footer>
    <button className={`back-to-top ${showBackToTop ? 'visible' : ''}`} aria-label="回到顶部" onClick={scrollExactlyToTop}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m6 12 6-6 6 6M12 6v13" /></svg></button>
  </div>
}
