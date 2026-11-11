import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Landing from './Landing'
import Icon from './Icon'
import { api } from './api'
import { useAuth } from './Auth'
import { allowedPages, pages, resolvePage, type Page } from './navigation'
import { downloadCsv, numeric, percent } from './format'
import type { Alert, Asset, AssetSeries, HomeSummary, Regime } from './types'

const Chart = lazy(() => import('./Chart'))
const SourceCatalog = lazy(() => import('./SourceCatalog'))
const ReplayCenter = lazy(() => import('./ReplayCenter'))
const AlertCenter = lazy(() => import('./AlertCenter'))
type DashboardData = { assets: Asset[]; latest: Regime; states: Regime[]; alerts: Alert[] }
const featureNames: Record<string, string> = { market_return: '市场收益', volatility: '年化波动率', momentum: '中期动量', correlation: '资产相关性', trend: '短期趋势', sample_count: '有效资产数' }
const regimeColors = ['#267a66', '#cb8336', '#d06458', '#557db3', '#9272aa']
const axis = { axisLabel: { color: '#7b8586', fontSize: 10 }, axisLine: { lineStyle: { color: '#dfe5e1' } }, axisTick: { show: false } }
const grid = { left: 58, right: 24, top: 28, bottom: 38 }

function Panel({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="panel"><div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}

function Workspace({ page, onNavigate, latestDate, alertCount, children }: { page: Page; onNavigate: (page: Page) => void; latestDate?: string; alertCount: number; children: React.ReactNode }) {
  const { user } = useAuth()
  const [menu, setMenu] = useState(false)
  const current = pages.find(item => item[0] === page)!
  const allowed = allowedPages(user.domains)
  return <div className="shell">
    <a className="skip-link" href="#workspace-content" onClick={event => { event.preventDefault(); document.getElementById('workspace-content')?.focus() }}>跳转到主要内容</a>
    {menu && <button className="nav-scrim" aria-label="关闭导航" onClick={() => setMenu(false)} />}
    <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
      <a className="brand" href={`#/${allowed[0]}`} onClick={event => { event.preventDefault(); onNavigate(allowed[0]); setMenu(false) }}><span className="brand-mark">M<span>·</span></span><div>MarketLens<small>市场状态研究平台</small></div></a>
      <p className="nav-caption">RESEARCH WORKSPACE</p>
      <nav aria-label="主要导航">{pages.filter(([id]) => allowed.includes(id)).map(([id, label, icon]) => <button key={id} className={page === id ? 'active' : ''} aria-current={page === id ? 'page' : undefined} onClick={() => { onNavigate(id); setMenu(false) }}><Icon name={icon} /><span>{label}</span>{id === 'alerts' && alertCount > 0 && <b>{alertCount}</b>}</button>)}</nav>
      <div className="sidebar-note"><Icon name="regimes" /><strong>以证据理解市场</strong><p>数学模型识别状态<br />确定性规则生成预警</p></div>
      <div className="sidebar-foot"><span className="history-dot" />历史数据研究环境<small>事件时间驱动 · 可追溯分析</small></div>
    </aside>
    <main className="main" id="workspace-content" tabIndex={-1}>
      <div className="workspace-topline"><button className="mobile-menu" aria-label="打开导航" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="menu" /></button><span>工作台 <i>/</i> {current[1]}</span><span className="environment-label">HISTORICAL RESEARCH</span></div>
      <header className="page-header"><div><p className="eyebrow">{current[3]}</p><h1>{current[1]}<span className="heading-period" aria-hidden="true">.</span></h1><p className="page-description">{({ overview: '从市场全貌出发，发现状态变化与风险线索。', regimes: '沿时间观察市场状态，复核每一次模型判断。', features: '把价格变化转化为可比较、可解释的研究指标。', alerts: '从触发信号到原始证据，让每一次提示都有据可查。', replay: '回到当时可见的数据，重现状态与预警的形成过程。', data: '统一检索多源数据，追溯原始字段与事件时间。' } as Record<string, string>)[page]}</p></div><div className="asof"><span>最新市场观测日</span><strong>{latestDate ?? '等待查询'}</strong><small>历史观测 · 非实时行情</small></div></header>
      <Suspense fallback={<div className="page-loading" role="status"><span className="loader" />正在加载分析模块…</div>}>{children}</Suspense>
      <footer><span>MarketLens <b>研究始于证据</b></span><span>市场状态用于研究辅助，不构成投资建议</span></footer>
    </main>
  </div>
}

export default function App() {
  const { user } = useAuth()
  const [page, setPage] = useState<Page>(() => resolvePage(window.location.hash, user.domains))
  const [homeData, setHomeData] = useState<HomeSummary | null>(null)
  const [homeError, setHomeError] = useState('')
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const loadingRef = useRef(false)
  const [selectedAsset, setSelectedAsset] = useState('SPX.GI')
  const [assetCategory, setAssetCategory] = useState('all')
  const [assetSearch, setAssetSearch] = useState('')
  const [series, setSeries] = useState<AssetSeries | null>(null)
  const [seriesError, setSeriesError] = useState('')
  const [seriesLoading, setSeriesLoading] = useState(false)
  const [seriesAttempt, setSeriesAttempt] = useState(0)
  const [range, setRange] = useState(500)
  const [feature, setFeature] = useState('volatility')

  const loadHome = useCallback(async () => {
    setHomeError('')
    try { setHomeData(await api<HomeSummary>('/api/home/summary')) }
    catch (reason) { setHomeError(reason instanceof Error ? reason.message : '市场摘要暂不可用') }
  }, [])
  const loadMarket = useCallback(async () => {
    if (loadingRef.current) return
    loadingRef.current = true; setLoading(true); setError('')
    try {
      const [assets, latest, states, alerts] = await Promise.all([
        api<Asset[]>('/api/assets'), api<Regime>('/api/regimes/latest'), api<Regime[]>('/api/regimes?limit=2000'), api<Alert[]>('/api/alerts?limit=100'),
      ])
      setData({ assets, latest, states, alerts })
      setSelectedAsset(current => assets.some(item => item.code === current) ? current : assets[0]?.code ?? '')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接数据服务') }
    finally { loadingRef.current = false; setLoading(false) }
  }, [])
  const navigate = useCallback((next: Page) => { window.location.hash = `/${next}`; setPage(next) }, [])
  useEffect(() => {
    const sync = () => setPage(resolvePage(window.location.hash, user.domains))
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [user.domains])
  useEffect(() => { if (user.domains.includes('market') && user.domains.includes('catalog')) void loadHome() }, [loadHome, user.domains])
  useEffect(() => { if (user.domains.includes('market') && !['home', 'data', 'replay'].includes(page) && !data && !error) void loadMarket() }, [page, data, error, loadMarket, user.domains])
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior }); document.title = `${pages.find(item => item[0] === page)?.[1]} · MarketLens` }, [page])
  useEffect(() => {
    if (page !== 'overview' || !data || !selectedAsset) return
    const controller = new AbortController()
    setSeries(null); setSeriesLoading(true); setSeriesError('')
    api<AssetSeries>(`/api/assets/${encodeURIComponent(selectedAsset)}/series?limit=500`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setSeries(result) })
      .catch(reason => { if (!controller.signal.aborted) setSeriesError(reason instanceof Error ? reason.message : '资产序列加载失败') })
      .finally(() => { if (!controller.signal.aborted) setSeriesLoading(false) })
    return () => controller.abort()
  }, [page, data, selectedAsset, seriesAttempt])

  const filteredAssets = useMemo(() => data?.assets.filter(item => (assetCategory === 'all' || item.category === assetCategory) && `${item.name} ${item.code}`.toLowerCase().includes(assetSearch.toLowerCase())) ?? [], [data, assetCategory, assetSearch])
  useEffect(() => {
    if (data && !filteredAssets.some(item => item.code === selectedAsset)) setSelectedAsset(filteredAssets[0]?.code ?? '')
  }, [data, filteredAssets, selectedAsset])
  const currentSeries = series?.code === selectedAsset ? series : null
  const visiblePoints = currentSeries?.points.slice(-range) ?? []
  const priceOption = useMemo(() => ({ grid, tooltip: { trigger: 'axis' as const },
    xAxis: { ...axis, type: 'category' as const, data: series?.points.slice(-range).map(point => point.date) ?? [], boundaryGap: false },
    yAxis: { ...axis, type: 'value' as const, scale: true, splitLine: { lineStyle: { color: '#edf0ed', type: 'dashed' as const } } },
    series: [{ name: series?.name ?? '观测值', type: 'line' as const, data: series?.points.slice(-range).map(point => point.value) ?? [], showSymbol: false, lineStyle: { color: '#267a66', width: 2.5 }, areaStyle: { color: { type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#267a662b' }, { offset: 1, color: '#267a6600' }] } } }],
  }), [series, range])
  const regimeOption = useMemo(() => {
    const states = data?.states.slice(-500) ?? []
    const labels = [...new Set(states.map(item => item.label))]
    return { grid: { ...grid, left: 110 }, tooltip: { trigger: 'item' as const }, xAxis: { ...axis, type: 'category' as const, data: states.map(item => item.date) }, yAxis: { ...axis, type: 'category' as const, data: labels, splitLine: { show: true, lineStyle: { color: '#edf0ed' } } },
      series: labels.map((label, index) => ({ name: label, type: 'scatter' as const, symbolSize: 7, data: states.filter(item => item.label === label).map(item => [item.date, label]), itemStyle: { color: regimeColors[index % regimeColors.length] } })),
    }
  }, [data])
  const heatOption = useMemo(() => {
    const states = data?.states.slice(-120) ?? []
    const features = Object.keys(featureNames)
    const ranges = features.map(key => { const values = states.map(state => state.features[key]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value)); return { min: Math.min(...values), max: Math.max(...values) } })
    return { grid: { left: 84, right: 24, top: 20, bottom: 80 },
      tooltip: { formatter: (params: unknown) => { const point = params as { value: (string | number | null)[] }; const key = features[Number(point.value[1])]; const raw = point.value[3]; return `${point.value[0]}\n${featureNames[key]}: ${typeof raw === 'number' ? key === 'sample_count' ? raw : key === 'correlation' ? numeric(raw, 4) : percent(raw, 3) : '缺失值'}` } },
      xAxis: { ...axis, type: 'category' as const, data: states.map(item => item.date) }, yAxis: { ...axis, type: 'category' as const, data: features.map(key => featureNames[key]) },
      visualMap: { min: 0, max: 1, dimension: 2, calculable: false, orient: 'horizontal' as const, left: 'center', bottom: 5, text: ['区间内较高', '区间内较低'], textStyle: { color: '#7b8586' }, inRange: { color: ['#edf4eb', '#a7cec0', '#267a66', '#d99a60'] }, outOfRange: { color: ['#e0e4e3'] } },
      series: [{ type: 'heatmap' as const, data: states.flatMap(state => features.map((key, index) => { const raw = state.features[key]; const valid = typeof raw === 'number' && Number.isFinite(raw); const { min, max } = ranges[index]; return [state.date, index, valid ? max === min ? .5 : (raw - min) / (max - min) : null, valid ? raw : null] })), itemStyle: { borderColor: '#fff', borderWidth: 1 } }],
    }
  }, [data])
  const featureOption = useMemo(() => ({ grid, tooltip: { trigger: 'axis' as const }, xAxis: { ...axis, type: 'category' as const, data: data?.states.slice(-500).map(item => item.date) ?? [] }, yAxis: { ...axis, type: 'value' as const, scale: true, splitLine: { lineStyle: { color: '#edf0ed' } } }, series: [{ name: featureNames[feature], type: 'line' as const, showSymbol: false, connectNulls: false, data: data?.states.slice(-500).map(item => item.features[feature]) ?? [], lineStyle: { width: 2, color: '#cb8336' } }] }), [data, feature])

  if (!allowedPages(user.domains).length) return <main className="connection-state"><Icon name="alerts" /><h1>暂无可访问的数据范围</h1><p>请联系管理员授予市场分析或数据目录权限。</p></main>
  if (page === 'home') return <Landing data={homeData} error={homeError} onRetry={() => void loadHome()} onEnter={() => navigate('overview')} onNavigate={navigate} />
  const latestDate = data?.latest.date ?? homeData?.latest.date
  const alertCount = data?.alerts.length ?? homeData?.alert_count ?? 0
  let content: React.ReactNode
  if (page === 'replay') content = <ReplayCenter />
  else if (page === 'data') content = <SourceCatalog />
  else if (!data) content = error ? <section className="connection-state" role="alert"><Icon name="alerts" /><h2>分析数据暂不可用</h2><p>{error}</p><button onClick={() => void loadMarket()}>重新连接</button>{user.domains.includes('catalog') && <button className="quiet" onClick={() => navigate('data')}>查看数据中心</button>}</section> : <div className="page-loading" role="status"><span className="loader" />正在加载市场状态与分析结果…</div>
  else {
    const { latest, states, alerts, assets } = data
    const selected = assets.find(item => item.code === selectedAsset)
    content = <>
      {error && <div className="error" role="alert">{error}<button onClick={() => void loadMarket()}>重试</button></div>}
      <div className="analysis-toolbar"><span><span className="status-dot" />训练数据截至 <b>{latest.trained_through}</b></span><button className="quiet" disabled={loading} onClick={() => void loadMarket()}><Icon name="refresh" />{loading ? '正在刷新…' : '刷新数据'}</button></div>
      {page === 'overview' && <>
        <div className="metrics"><div className="metric featured"><span>当前市场状态 <Icon name="regimes" /></span><strong>{latest.label}</strong><small>模型置信度 {percent(latest.confidence, 1)}</small></div><div className="metric"><span>年化波动率 <Icon name="features" /></span><strong>{percent(latest.features.volatility)}</strong><small>20 日滚动窗口 · 年化</small></div><div className="metric"><span>中期动量 <Icon name="overview" /></span><strong className={(latest.features.momentum ?? 0) >= 0 ? 'positive' : 'negative'}>{percent(latest.features.momentum)}</strong><small>60 日多资产涨跌幅均值</small></div><div className="metric"><span>近期预警 <Icon name="alerts" /></span><strong>{alerts.length}<em>条</em></strong><small>最近最多 100 条 <button className="text-button" onClick={() => navigate('alerts')}>查看证据 ↗</button></small></div></div>
        <div className="grid wide-left"><Panel title="资产走势" subtitle={`${selected?.name ?? '请选择资产'} · ${selected?.code ?? '—'} · ${selected?.field === 'yield' ? '收益率（非价格）' : '收盘价'}`} action={<div className="segmented" aria-label="观测范围">{[[60, '60 日'], [250, '250 日'], [500, '500 日']].map(([value, label]) => <button key={value} aria-pressed={range === value} className={range === value ? 'active' : ''} onClick={() => setRange(Number(value))}>{label}</button>)}</div>}>
          <div className="asset-controls"><input aria-label="搜索资产" placeholder="搜索资产名称或代码" value={assetSearch} onChange={event => setAssetSearch(event.target.value)} /><select aria-label="资产类别" value={assetCategory} onChange={event => setAssetCategory(event.target.value)}><option value="all">全部资产类别</option>{[...new Set(assets.map(item => item.category))].map(category => <option key={category}>{category}</option>)}</select><select aria-label="选择资产" value={filteredAssets.some(item => item.code === selectedAsset) ? selectedAsset : ''} onChange={event => setSelectedAsset(event.target.value)}>{!filteredAssets.some(item => item.code === selectedAsset) && <option value="" disabled>{filteredAssets.length ? '请选择资产' : '无匹配资产'}</option>}{filteredAssets.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}</select></div>
          {seriesError ? <div className="empty" role="alert">{seriesError}<button onClick={() => setSeriesAttempt(value => value + 1)}>重试走势查询</button></div> : seriesLoading ? <div className="chart page-loading" role="status">正在加载资产序列…</div> : !visiblePoints.length ? <div className="chart empty">当前资产没有可用观测值</div> : <Chart option={priceOption} label={`${selected?.name}历史走势`} />}
          <div className="chart-foot"><span>{visiblePoints.length ? `${visiblePoints[0].date} — ${visiblePoints.at(-1)?.date} · ${visiblePoints.length} 个观测值 · ${series?.unit ?? ''}` : '不同资产保留原始交易日历'}</span><button className="text-button" disabled={!visiblePoints.length} onClick={() => downloadCsv(`${selectedAsset}-${range}.csv`, [['date', 'value', 'field', 'unit'], ...visiblePoints.map(point => [point.date, point.value, series?.field, series?.unit])])}><Icon name="download" />导出 CSV</button></div>
        </Panel><Panel title="状态判断依据" subtitle="相对训练窗口的标准化偏离" action={<span className="tag">MODEL EVIDENCE</span>}><div className="evidence">{latest.contributions.map(item => <div key={item.feature}><span>{featureNames[item.feature] ?? item.feature}</span><div className="bar"><i style={{ width: `${Math.min(100, Math.abs(item.standardized ?? 0) * 35)}%` }} /></div><b>{numeric(item.standardized)}σ</b></div>)}</div><p className="method-note">贡献值表示当前特征相对训练窗口的标准化偏离，不代表因果关系。</p><div className="model-stamp"><span>模型版本</span><code>{latest.model_version}</code></div><button className="panel-link" onClick={() => navigate('features')}>深入探索特征 <Icon name="arrow" /></button></Panel></div>
        <Panel title="近期风险信号" subtitle="由确定性规则生成，可逐条复核触发依据" action={<button className="text-button" onClick={() => navigate('alerts')}>全部预警 <Icon name="arrow" /></button>}><AlertList alerts={alerts.slice(0, 4)} /></Panel>
        {allowedPages(user.domains).includes('replay') && <div className="research-strip"><div><span>验证，而非猜测</span><h3>将一次市场判断，放回历史中检验。</h3><p>只读取事件时间及此前的数据，逐日重现特征、状态和预警。</p></div><button onClick={() => navigate('replay')}>打开历史回放 <Icon name="arrow" /></button></div>}
      </>}
      {page === 'regimes' && <><div className="metrics three"><div className="metric"><span>本次加载的状态日</span><strong>{states.length.toLocaleString()}</strong><small>最近最多 2,000 日 · walk-forward</small></div><div className="metric featured"><span>当前状态</span><strong>{latest.label}</strong><small>训练数据截至 {latest.trained_through}</small></div><div className="metric"><span>当日有效资产</span><strong>{numeric(latest.features.sample_count, 0)}<em>个</em></strong><small>实际参与计算的样本量</small></div></div><Panel title="市场状态时间图谱" subtitle="最近 500 个状态日 · 颜色对应不同状态画像"><Chart option={regimeOption} className="tall" label="市场状态历史时间图谱" /></Panel><Panel title="状态特征热力图" subtitle="最近 120 个状态日 · 每个特征独立归一化"><Chart option={heatOption} className="tall" label="六个市场特征的历史热力图" /><p className="method-note">颜色只比较同一特征在这 120 日内的相对高低，不能直接跨特征比较颜色。悬停查看原始值；灰色为缺失值，不按 0 处理。有效资产数表示当日实际参与计算的资产样本量。</p></Panel><Panel title="最近状态记录" subtitle="训练切片严格排除识别当日" action={<button className="text-button" onClick={() => downloadCsv('market-states.csv', [['date', 'label', 'confidence', 'model_version', 'trained_through'], ...states.map(item => [item.date, item.label, item.confidence, item.model_version, item.trained_through])])}><Icon name="download" />导出已加载状态</button>}><div className="table-wrap"><table><thead><tr><th>日期</th><th>市场状态</th><th>置信度</th><th>波动率</th><th>动量</th><th>模型版本</th></tr></thead><tbody>{states.slice(-10).reverse().map(item => <tr key={item.date}><td>{item.date}</td><td><span className="status-dot" />{item.label}</td><td>{percent(item.confidence, 1)}</td><td>{percent(item.features.volatility)}</td><td>{percent(item.features.momentum)}</td><td className="muted">{item.model_version}</td></tr>)}</tbody></table></div></Panel></>}
      {page === 'features' && <><div className="metrics three">{['volatility', 'momentum', 'correlation'].map(key => <div className="metric" key={key}><span>{featureNames[key]}</span><strong>{key === 'correlation' ? numeric(latest.features[key], 3) : percent(latest.features[key])}</strong><small>最新观测日 {latest.date}</small></div>)}</div><Panel title="特征历史走势" subtitle="最近 500 个状态日 · 缺失值保持断点" action={<select aria-label="历史特征" value={feature} onChange={event => setFeature(event.target.value)}>{Object.entries(featureNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>}><Chart option={featureOption} label={`${featureNames[feature]}历史变化`} /></Panel><div className="grid equal"><Panel title="特征偏离程度" subtitle="绝对标准化值越大，偏离训练窗口中心越远"><div className="feature-list">{latest.contributions.map(item => <div className="feature-row" key={item.feature}><div><span>{featureNames[item.feature]}</span><strong>{numeric(item.standardized, 3)}σ</strong></div><div className="track"><i className={(item.standardized ?? 0) < 0 ? 'below' : ''} style={{ width: `${Math.min(100, Math.abs(item.standardized ?? 0) * 35)}%` }} /></div><small>原始值 {numeric(item.value, 4)}</small></div>)}</div></Panel><Panel title="指标口径"><div className="glossary"><p><b>市场收益</b>各价格资产当日对数收益的横截面均值。</p><p><b>年化波动率</b>市场收益在 20 日窗口内的标准差乘 √252。</p><p><b>中期动量</b>各价格资产过去 60 日涨跌幅的均值。</p><p><b>资产相关性</b>60 日窗口内资产收益成对相关系数均值。</p><p><b>短期趋势</b>价格相对 20 日均线偏离的均值，不参与当前聚类。</p></div></Panel></div></>}
      {page === 'alerts' && <AlertCenter alerts={alerts} onChanged={() => { void loadMarket(); if (user.domains.includes('catalog')) void loadHome() }} />}
    </>
  }
  return <Workspace page={page} onNavigate={navigate} latestDate={latestDate} alertCount={alertCount}>{content}</Workspace>
}

function AlertList({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return <div className="empty"><Icon name="alerts" /><p>当前查询范围内暂无预警</p></div>
  return <div className="alert-list">{alerts.map((item, index) => <article className="alert" key={`${item.date}-${item.rule}-${index}`}><span className={`alert-level ${item.level}`}>{item.level === 'high' ? '高' : '中'}</span><div><h3>{item.title}<small>{item.rule}</small></h3><p>{item.evidence}</p></div><time>{item.date}</time></article>)}</div>
}
