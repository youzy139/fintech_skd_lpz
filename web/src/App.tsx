import { useCallback, useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import Landing from './Landing'
import SourceCatalog from './SourceCatalog'
import ReplayCenter from './ReplayCenter'
import { api } from './api'
import type { Alert, Asset, AssetSeries, HomeSummary, Regime } from './types'

const pages = [
  ['home', '网站首页', '⌂'],
  ['overview', '市场总览', '⌁'],
  ['regimes', '状态分析', '◫'],
  ['replay', '历史回放', '↻'],
  ['features', '特征分析', '∿'],
  ['alerts', '预警中心', '△'],
  ['data', '数据中心', '▤'],
] as const

type Page = typeof pages[number][0]
type DashboardData = { assets: Asset[]; latest: Regime; states: Regime[]; alerts: Alert[] }

const featureNames: Record<string, string> = { market_return: '市场收益', volatility: '年化波动率', momentum: '中期动量', correlation: '资产相关性', trend: '短期趋势', sample_count: '有效资产数' }
const regimeColors = ['#47d7ac', '#f3b65c', '#f07878', '#77a8f8', '#b38cf2']

function percent(value: number, digits = 2) { return `${(value * 100).toFixed(digits)}%` }
function dateText(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(`${value}T00:00:00`)) }

function Panel({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="panel"><div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}

function Workspace({ page, onNavigate, latestDate, alertCount, children }: { page: Page; onNavigate: (page: Page) => void; latestDate?: string; alertCount: number; children: React.ReactNode }) {
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">M</span><div>MarketLens<small>市场状态监控平台</small></div></div>
      <nav>{pages.map(([id, label, icon]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => onNavigate(id)}><span>{icon}</span>{label}{id === 'alerts' && alertCount > 0 && <b>{alertCount}</b>}</button>)}</nav>
      <div className="sidebar-foot"><span className="pulse" />数据服务运行中<small>v0.3.3 · 测试版本</small></div>
    </aside>
    <main className="main" key={page}>
      <header><div><p className="eyebrow">MULTI-ASSET INTELLIGENCE</p><h1>{pages.find(item => item[0] === page)?.[1]}</h1></div><div className="asof"><span>数据截至</span><strong>{latestDate ? dateText(latestDate) : '—'}</strong></div></header>
      {children}
      <footer>MarketLens · 市场状态用于研究辅助，不构成投资建议</footer>
    </main>
  </div>
}

function App() {
  const [page, setPage] = useState<Page>('home')
  const [homeData, setHomeData] = useState<HomeSummary | null>(null)
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [selectedAsset, setSelectedAsset] = useState('SPX.GI')
  const [series, setSeries] = useState<AssetSeries | null>(null)
  const [alertFilter, setAlertFilter] = useState('all')

  const loadMarket = useCallback(async () => {
    setError('')
    try {
      const [assets, latest, states, alerts] = await Promise.all([
        api<Asset[]>('/api/assets'), api<Regime>('/api/regimes/latest'), api<Regime[]>('/api/regimes?limit=2000'), api<Alert[]>('/api/alerts?limit=100'),
      ])
      setData({ assets, latest, states, alerts })
      if (!assets.some(item => item.code === selectedAsset)) setSelectedAsset(assets[0]?.code ?? '')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接数据服务') }
  }, [selectedAsset])

  const navigate = useCallback((next: Page) => {
    setPage(next)
    if (next !== 'home' && next !== 'data' && next !== 'replay' && !data) void loadMarket()
  }, [data, loadMarket])

  useEffect(() => { api<HomeSummary>('/api/home/summary').then(setHomeData).catch(() => setHomeData(null)) }, [])
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior }) }, [page])
  useEffect(() => {
    if (page !== 'overview' || !data || !selectedAsset) return
    api<AssetSeries>(`/api/assets/${encodeURIComponent(selectedAsset)}/series?limit=500`).then(setSeries).catch(() => setSeries(null))
  }, [page, data, selectedAsset])

  const priceOption = useMemo(() => ({
    grid: { left: 54, right: 20, top: 24, bottom: 38 }, tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'category' as const, data: series?.points.map(point => point.date) ?? [], axisLine: { lineStyle: { color: '#304353' } }, axisLabel: { color: '#78909f' } },
    yAxis: { type: 'value' as const, scale: true, splitLine: { lineStyle: { color: '#1d303d' } }, axisLabel: { color: '#78909f' } },
    series: [{ type: 'line' as const, data: series?.points.map(point => point.value) ?? [], showSymbol: false, lineStyle: { color: '#47d7ac', width: 2 }, areaStyle: { color: 'rgba(71,215,172,.08)' } }],
  }), [series])

  const regimeOption = useMemo(() => {
    const states = data?.states.slice(-500) ?? []
    const labels = [...new Set(states.map(item => item.label))]
    return {
      grid: { left: 45, right: 20, top: 25, bottom: 45 }, tooltip: { formatter: (params: unknown) => { const point = params as { value: (string | number)[] }; return `${point.value[0]}<br/>${labels[Number(point.value[1])]}` } },
      xAxis: { type: 'category' as const, data: states.map(item => item.date), axisLabel: { color: '#78909f' }, axisLine: { lineStyle: { color: '#304353' } } },
      yAxis: { type: 'category' as const, data: labels, axisLabel: { color: '#a9b9c4' }, splitLine: { show: true, lineStyle: { color: '#1d303d' } } },
      series: [{ type: 'scatter' as const, symbolSize: 7, data: states.map(item => [item.date, labels.indexOf(item.label)]), itemStyle: { color: (params: unknown) => { const point = params as { value: (string | number)[] }; return regimeColors[Number(point.value[1]) % regimeColors.length] } } }],
    }
  }, [data])

  if (page === 'home') return <Landing data={homeData} onEnter={() => navigate('overview')} />
  if (page === 'replay') return <Workspace page={page} onNavigate={navigate} latestDate={homeData?.latest.date} alertCount={homeData?.alert_count ?? 0}><ReplayCenter /></Workspace>
  if (page === 'data') return <Workspace page={page} onNavigate={navigate} latestDate={homeData?.latest.date} alertCount={homeData?.alert_count ?? 0}><SourceCatalog /></Workspace>
  if (!data && !error) return <main className="boot"><div className="loader" /><h1>MarketLens</h1><p>正在加载市场状态与分析结果…</p></main>
  if (!data) return <main className="boot"><h1>暂时无法连接</h1><p>{error}</p><button onClick={() => void loadMarket()}>重新连接</button></main>

  const { latest, states, alerts, assets } = data
  const filteredAlerts = alertFilter === 'all' ? alerts : alerts.filter(item => item.level === alertFilter)

  return <Workspace page={page} onNavigate={navigate} latestDate={latest.date} alertCount={alerts.length}>
    {error && <div className="error">{error}</div>}

    {page === 'overview' && <>
      <div className="metrics">
        <div className="metric featured"><span>当前市场状态</span><strong>{latest.label}</strong><small>模型置信度 {percent(latest.confidence, 1)}</small></div>
        <div className="metric"><span>年化波动率</span><strong>{percent(latest.features.volatility)}</strong><small>20 日滚动窗口</small></div>
        <div className="metric"><span>中期动量</span><strong className={latest.features.momentum >= 0 ? 'positive' : 'negative'}>{percent(latest.features.momentum)}</strong><small>60 日多资产均值</small></div>
        <div className="metric"><span>最新预警</span><strong>{alerts[0]?.title ?? '暂无预警'}</strong><small>{alerts[0] ? dateText(alerts[0].date) : '规则引擎持续监测'}</small></div>
      </div>
      <div className="grid wide-left">
        <Panel title="资产价格走势" subtitle="最近 500 个有效观测值" action={<select value={selectedAsset} onChange={event => setSelectedAsset(event.target.value)}>{assets.map(item => <option key={item.code} value={item.code}>{item.name} · {item.field}</option>)}</select>}><Chart option={priceOption} /></Panel>
        <Panel title="状态判断依据" subtitle={`模型 ${latest.model_version}`}><div className="evidence">{latest.contributions.map(item => <div key={item.feature}><span>{featureNames[item.feature] ?? item.feature}</span><div className="bar"><i style={{ width: `${Math.min(100, Math.abs(item.standardized) * 45)}%` }} /></div><b>{item.standardized.toFixed(2)}σ</b></div>)}</div><p className="method-note">贡献值表示当前特征相对训练窗口的标准化偏离，不代表因果关系。</p></Panel>
      </div>
      <Panel title="近期风险信号" subtitle="由确定性规则与市场状态模型共同产生"><AlertList alerts={alerts.slice(0, 4)} /></Panel>
    </>}

    {page === 'regimes' && <>
      <div className="metrics three"><div className="metric"><span>历史状态观测</span><strong>{states.length}</strong><small>逐日 walk-forward 识别</small></div><div className="metric"><span>当前状态</span><strong>{latest.label}</strong><small>训练数据截至 {latest.trained_through}</small></div><div className="metric"><span>有效资产覆盖</span><strong>{latest.features.sample_count}</strong><small>当日实际参与计算</small></div></div>
      <Panel title="市场状态时间图谱" subtitle="最近 500 个状态日 · 颜色对应不同状态画像"><Chart option={regimeOption} className="tall" /></Panel>
      <Panel title="最近状态记录" subtitle="每次识别仅使用当日及此前数据"><div className="table-wrap"><table><thead><tr><th>日期</th><th>状态</th><th>置信度</th><th>波动率</th><th>动量</th><th>模型版本</th></tr></thead><tbody>{states.slice(-10).reverse().map(item => <tr key={item.date}><td>{item.date}</td><td><span className="status-dot" />{item.label}</td><td>{percent(item.confidence, 1)}</td><td>{percent(item.features.volatility)}</td><td>{percent(item.features.momentum)}</td><td className="muted">{item.model_version}</td></tr>)}</tbody></table></div></Panel>
    </>}

    {page === 'features' && <>
      <div className="metrics three">{['volatility', 'momentum', 'correlation'].map(key => <div className="metric" key={key}><span>{featureNames[key]}</span><strong>{key === 'correlation' ? latest.features[key].toFixed(3) : percent(latest.features[key])}</strong><small>截至 {latest.date}</small></div>)}</div>
      <div className="grid equal"><Panel title="特征偏离程度" subtitle="绝对标准化值越大，当前状态越异常"><div className="feature-list">{latest.contributions.map(item => <div className="feature-row" key={item.feature}><div><span>{featureNames[item.feature]}</span><strong>{item.standardized.toFixed(3)}σ</strong></div><div className="track"><i className={item.standardized < 0 ? 'below' : ''} style={{ width: `${Math.min(100, Math.abs(item.standardized) * 40)}%` }} /></div><small>原始值 {item.value.toFixed(4)}</small></div>)}</div></Panel><Panel title="如何理解这些特征？"><div className="glossary"><p><b>市场收益</b>多资产当日对数收益的横截面均值。</p><p><b>年化波动率</b>市场收益在 20 日窗口内的标准差年化。</p><p><b>中期动量</b>各价格资产过去 60 日涨跌幅的均值。</p><p><b>资产相关性</b>60 日窗口内资产收益的成对相关性均值。</p></div></Panel></div>
    </>}

    {page === 'alerts' && <Panel title="预警记录" subtitle="高波动、相关性异常与状态切换" action={<select value={alertFilter} onChange={event => setAlertFilter(event.target.value)}><option value="all">全部级别</option><option value="high">高级别</option><option value="medium">中级别</option></select>}><AlertList alerts={filteredAlerts} /></Panel>}
  </Workspace>
}

function AlertList({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return <div className="empty">当前筛选条件下暂无预警</div>
  return <div className="alert-list">{alerts.map((item, index) => <article className="alert" key={`${item.date}-${item.rule}-${index}`}><span className={`alert-level ${item.level}`}>{item.level === 'high' ? '高' : '中'}</span><div><h3>{item.title}<small>{item.rule}</small></h3><p>{item.evidence}</p></div><time>{item.date}</time></article>)}</div>
}

export default App
