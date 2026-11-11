import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import Landing from './Landing'
import Icon from './Icon'
import Workspace from './Workspace'
import { api } from './api'
import { useAuth } from './Auth'
import { allowedPages, pages, resolvePage, type Page } from './navigation'
import { ErrorMessage, Loading } from './ui'
import type { Alert, Asset, HomeSummary, Regime } from './types'

const MarketOverview = lazy(() => import('./MarketOverview'))
const RegimeAnalysis = lazy(() => import('./RegimeAnalysis'))
const FeatureAnalysis = lazy(() => import('./FeatureAnalysis'))
const SourceCatalog = lazy(() => import('./SourceCatalog'))
const ReplayCenter = lazy(() => import('./ReplayCenter'))
const AlertCenter = lazy(() => import('./AlertCenter'))
const Accounts = lazy(() => import('./Accounts'))
const Audit = lazy(() => import('./Audit').then(module => ({ default: module.Audit })))
const SystemStatus = lazy(() => import('./SystemStatus').then(module => ({ default: module.SystemStatus })))
type DashboardData = { assets: Asset[]; latest: Regime; states: Regime[]; alerts: Alert[] }
const marketPages: Page[] = ['overview', 'regimes', 'features', 'alerts']

export default function App() {
  const { user } = useAuth()
  const [page, setPage] = useState<Page>(() => resolvePage(window.location.hash, user.domains, user.role))
  const [homeData, setHomeData] = useState<HomeSummary | null>(null)
  const [homeError, setHomeError] = useState('')
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const loadingRef = useRef(false)
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
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接数据服务') }
    finally { loadingRef.current = false; setLoading(false) }
  }, [])
  const navigate = useCallback((next: Page) => { window.location.hash = `/${next}`; setPage(next) }, [])
  useEffect(() => {
    const sync = () => setPage(resolvePage(window.location.hash, user.domains, user.role))
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [user.domains, user.role])
  useEffect(() => { if (user.domains.includes('market') && user.domains.includes('catalog')) void loadHome() }, [loadHome, user.domains])
  useEffect(() => { if (user.domains.includes('market') && marketPages.includes(page) && !data && !error) void loadMarket() }, [page, data, error, loadMarket, user.domains])
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior }); document.title = `${pages.find(item => item[0] === page)?.[1]} · MarketLens` }, [page])
  if (!allowedPages(user.domains, user.role).length) return <main className="connection-state"><Icon name="alerts" /><h1>暂无可访问的数据范围</h1><p>请联系管理员授予市场分析或数据目录权限。</p></main>
  const latest = data?.latest ?? homeData?.latest
  const alertCount = data?.alerts.length ?? homeData?.alert_count ?? 0
  let content: React.ReactNode
  if (page === 'home') content = <Landing data={homeData} error={homeError} onRetry={() => void loadHome()} onEnter={() => navigate('overview')} onNavigate={navigate} />
  else if (page === 'replay') content = <ReplayCenter />
  else if (page === 'data') content = <SourceCatalog />
  else if (page === 'accounts') content = <Accounts />
  else if (page === 'audit') content = <Audit />
  else if (page === 'system') content = <SystemStatus />
  else if (!data) content = <section className="connection-state">{error ? <><Icon name="alerts" /><h2>分析数据暂不可用</h2><ErrorMessage message={error} onRetry={() => void loadMarket()} retryLabel="重新连接" />{user.domains.includes('catalog') && <button className="quiet" onClick={() => navigate('data')}>查看数据中心</button>}</> : <Loading>正在加载市场状态与分析结果…</Loading>}</section>
  else {
    const refresh = () => { void loadMarket() }
    content = <>
      {error && <ErrorMessage message={error} onRetry={refresh} />}
      {page === 'overview' && <MarketOverview assets={data.assets} latest={data.latest} alerts={data.alerts} loading={loading} onRefresh={refresh} onNavigate={navigate} />}
      {page === 'regimes' && <RegimeAnalysis states={data.states} latest={data.latest} />}
      {page === 'features' && <FeatureAnalysis states={data.states} latest={data.latest} />}
      {page === 'alerts' && <AlertCenter alerts={data.alerts} onChanged={() => { refresh(); if (user.domains.includes('catalog')) void loadHome() }} />}
    </>
  }
  return <Workspace page={page} onNavigate={navigate} latest={latest} alertCount={alertCount}><Suspense fallback={<Loading>正在加载分析模块…</Loading>}>{content}</Suspense></Workspace>
}
