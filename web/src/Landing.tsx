import { useEffect, useState } from 'react'
import { scrollExactlyToTop } from './motion'
import type { HomeSummary } from './types'

type LandingData = HomeSummary

export default function Landing({ data, onEnter }: { data: LandingData | null; onEnter: () => void }) {
  const [showBackToTop, setShowBackToTop] = useState(false)
  const latest = data?.latest
  useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 360)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  const backToTop = scrollExactlyToTop
  return <div className="landing">
    <nav className="landing-nav">
      <a className="landing-brand" href="#top" aria-label="MarketLens 首页"><span className="brand-mark">M</span><span>MarketLens<small>市场状态监控平台</small></span></a>
      <div className="landing-links"><a href="#capabilities">产品能力</a><a href="#method">技术方法</a><a href="#data">数据基础</a></div>
      <button className="nav-entry" onClick={onEnter}>进入工作台 <span>→</span></button>
    </nav>

    <main id="top">
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-badge"><span className="pulse" />多资产市场状态智能监控</div>
          <h1>读懂市场状态，<br /><em>先于风险一步。</em></h1>
          <p>汇聚多资产行情，以可解释的机器学习识别市场状态、追踪特征变化并监测风险，让复杂市场信息成为清晰的研究依据。</p>
          <div className="hero-actions"><button className="primary-action" onClick={onEnter}>进入市场工作台 <span>→</span></button><a href="#method">了解技术方法</a></div>
          <div className="hero-proof"><span>39 类真实资产序列</span><span>Walk-forward 建模</span><span>可解释风险预警</span></div>
        </div>
        <div className="hero-visual" aria-label="实时市场状态摘要">
          <div className="visual-grid" />
          <div className="live-card">
            <div className="live-head"><span><i />MARKET REGIME</span><small>{latest?.date ?? '等待数据服务'}</small></div>
            <div className="live-state">{latest?.label ?? '市场状态待连接'}</div>
            <div className="live-confidence"><span>模型置信度</span><strong>{latest ? `${(latest.confidence * 100).toFixed(1)}%` : '—'}</strong></div>
            <div className="confidence-track"><i style={{ width: `${(latest?.confidence ?? 0) * 100}%` }} /></div>
            <div className="live-features"><div><span>年化波动率</span><strong>{latest ? `${(latest.features.volatility * 100).toFixed(2)}%` : '—'}</strong></div><div><span>中期动量</span><strong>{latest ? `${(latest.features.momentum * 100).toFixed(2)}%` : '—'}</strong></div><div><span>资产相关性</span><strong>{latest?.features.correlation.toFixed(3) ?? '—'}</strong></div></div>
            <div className="mini-chart"><svg viewBox="0 0 400 100" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#47d7ac" stopOpacity=".3"/><stop offset="1" stopColor="#47d7ac" stopOpacity="0"/></linearGradient></defs><path d="M0 82 L25 76 L50 79 L75 62 L100 68 L125 48 L150 57 L175 43 L200 50 L225 31 L250 39 L275 22 L300 30 L325 19 L350 25 L375 12 L400 16 L400 100 L0 100Z" fill="url(#area)"/><path d="M0 82 L25 76 L50 79 L75 62 L100 68 L125 48 L150 57 L175 43 L200 50 L225 31 L250 39 L275 22 L300 30 L325 19 L350 25 L375 12 L400 16" fill="none" stroke="#47d7ac" strokeWidth="2"/></svg></div>
            <div className="live-foot"><span>状态判断</span><span>预警决策</span><span>分析建议</span></div>
          </div>
          <div className="floating-note"><span>Δ</span><div><small>持续监测</small><strong>{data?.alert_count ?? '—'} 条风险信号</strong></div></div>
        </div>
      </section>

      <section className="capabilities" id="capabilities">
        <div className="section-heading"><span>CORE CAPABILITIES</span><h2>从原始数据到市场洞察</h2><p>不是单一图表，而是一条可验证、可追溯的市场监控链路。</p></div>
        <div className="capability-grid"><article><b>01</b><h3>市场状态识别</h3><p>融合收益、波动、动量和相关性，通过滚动训练模型识别不同市场环境。</p><span>PCA · KMeans · Walk-forward</span></article><article><b>02</b><h3>风险监测预警</h3><p>用确定性规则捕捉高波动、异常联动与状态切换，展示触发证据。</p><span>异常检测 · 规则引擎</span></article><article><b>03</b><h3>多维特征分析</h3><p>观察特征变化及其标准化偏离，理解模型为什么给出当前判断。</p><span>特征工程 · 状态画像</span></article></div>
      </section>

      <section className="method" id="method"><div className="section-heading"><span>HOW IT WORKS</span><h2>判断有依据，结果可追溯</h2></div><div className="method-flow"><div><b>1</b><h3>多源数据</h3><p>保留原始交易日历与字段口径</p></div><i>→</i><div><b>2</b><h3>特征计算</h3><p>从行情提取市场统计特征</p></div><i>→</i><div><b>3</b><h3>状态与预警</h3><p>模型判断，规则决定是否提醒</p></div><i>→</i><div><b>4</b><h3>可视化研究</h3><p>在看板中查看证据与历史变化</p></div></div></section>

      <section className="data-banner" id="data"><div><span>REAL DATA, VERIFIABLE RESULTS</span><h2>每一个判断，都从真实数据开始。</h2></div><div className="data-numbers"><div><strong>{data?.loaded_assets ?? '—'}</strong><span>可用资产</span></div><div><strong>{data?.total_rows.toLocaleString() ?? '—'}</strong><span>行情记录</span></div><div><strong>{data?.state_count ?? '—'}</strong><span>历史状态</span></div></div></section>

      <section className="landing-cta"><span>MARKETLENS WORKSPACE</span><h2>从一个更清晰的视角，观察市场。</h2><p>进入工作台，探索市场状态、关键特征与风险预警。</p><button className="primary-action" onClick={onEnter}>开始探索 <span>→</span></button></section>
    </main>
    <footer className="landing-footer"><div className="landing-brand"><span className="brand-mark">M</span><span>MarketLens</span></div><p>市场状态用于研究辅助，不构成投资建议 · v0.3.0 测试版本</p></footer>
    <button className={`back-to-top ${showBackToTop ? 'visible' : ''}`} onClick={backToTop} aria-label="回到顶部" title="回到顶部" tabIndex={showBackToTop ? 0 : -1}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg></button>
  </div>
}
