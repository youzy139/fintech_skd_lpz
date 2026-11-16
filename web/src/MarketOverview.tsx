import { useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import Icon from './Icon'
import { api } from './api'
import { chartAxis, chartColors, chartGrid } from './chartTheme'
import { directionTone, downloadCsv, numeric, percent } from './format'
import { featureNames } from './labels'
import { AlertList, ErrorMessage, Loading, Metric, Panel } from './ui'
import type { Alert, Asset, AssetSeries, Regime, ResearchWorkspace } from './types'
import type { Page } from './navigation'

type WorkspaceDraft = Pick<ResearchWorkspace, 'search' | 'category' | 'watchlist_only' | 'watchlist' | 'selected_asset' | 'visible_range'>
const emptyWorkspace = (): WorkspaceDraft => ({ search: '', category: 'all', watchlist_only: false, watchlist: [], selected_asset: 'SPX.GI', visible_range: 500 })
const draftOf = (result: ResearchWorkspace): WorkspaceDraft => ({ search: result.search, category: result.category, watchlist_only: result.watchlist_only, watchlist: result.watchlist, selected_asset: result.selected_asset, visible_range: result.visible_range })
const sameWorkspace = (left: WorkspaceDraft, right: WorkspaceDraft) => JSON.stringify(left) === JSON.stringify(right)

export default function MarketOverview({ assets, latest, alerts, loading, onRefresh, onNavigate }: { assets: Asset[]; latest: Regime; alerts: Alert[]; loading: boolean; onRefresh: () => void; onNavigate: (page: Page) => void }) {
  const [workspace, setWorkspace] = useState<WorkspaceDraft>(emptyWorkspace)
  const [savedWorkspace, setSavedWorkspace] = useState<WorkspaceDraft | null>(null)
  const [workspaceStatus, setWorkspaceStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [workspaceError, setWorkspaceError] = useState('')
  const [workspaceAttempt, setWorkspaceAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [series, setSeries] = useState<AssetSeries | null>(null)
  const [seriesError, setSeriesError] = useState('')
  const [seriesLoading, setSeriesLoading] = useState(false)
  const [seriesAttempt, setSeriesAttempt] = useState(0)
  const filteredAssets = useMemo(() => assets.filter(item => (!workspace.watchlist_only || workspace.watchlist.includes(item.code)) && (workspace.category === 'all' || item.category === workspace.category) && `${item.name} ${item.code}`.toLowerCase().includes(workspace.search.trim().toLowerCase())), [assets, workspace.category, workspace.search, workspace.watchlist, workspace.watchlist_only])
  const dirty = savedWorkspace !== null && !sameWorkspace(workspace, savedWorkspace)

  useEffect(() => {
    const controller = new AbortController()
    setWorkspaceStatus('loading'); setWorkspaceError(''); setSavedWorkspace(null)
    api<ResearchWorkspace>('/api/research/workspace', controller.signal).then(result => {
      if (controller.signal.aborted) return
      const draft = draftOf(result)
      setWorkspace(draft); setSavedWorkspace(draft); setSavedAt(result.updated_at); setWorkspaceStatus('ready')
    }).catch(reason => {
      if (!controller.signal.aborted) { setWorkspaceError(reason instanceof Error ? reason.message : '研究工作区加载失败'); setWorkspaceStatus('error') }
    })
    return () => controller.abort()
  }, [workspaceAttempt])

  useEffect(() => {
    if (!filteredAssets.some(item => item.code === workspace.selected_asset)) updateWorkspace({ selected_asset: filteredAssets[0]?.code ?? '' })
  }, [filteredAssets, workspace.selected_asset])

  useEffect(() => {
    if (workspaceStatus === 'loading') return
    if (!workspace.selected_asset) { setSeries(null); return }
    const controller = new AbortController()
    setSeries(null); setSeriesLoading(true); setSeriesError('')
    api<AssetSeries>(`/api/assets/${encodeURIComponent(workspace.selected_asset)}/series?limit=500`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setSeries(result) })
      .catch(reason => { if (!controller.signal.aborted) setSeriesError(reason instanceof Error ? reason.message : '资产序列加载失败') })
      .finally(() => { if (!controller.signal.aborted) setSeriesLoading(false) })
    return () => controller.abort()
  }, [workspace.selected_asset, workspaceStatus, seriesAttempt])

  function updateWorkspace(changes: Partial<WorkspaceDraft>) {
    setSaveError('')
    setWorkspace(current => ({ ...current, ...changes }))
  }

  function toggleWatchlist(code: string) {
    setSaveError('')
    setWorkspace(current => ({ ...current, watchlist: current.watchlist.includes(code) ? current.watchlist.filter(item => item !== code) : [...current.watchlist, code] }))
  }

  async function saveWorkspace() {
    if (workspaceStatus !== 'ready' || saving || !dirty) return
    const requested = { ...workspace, watchlist: [...workspace.watchlist] }
    setSaving(true); setSaveError('')
    try {
      const result = await api<ResearchWorkspace>('/api/research/workspace', undefined, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requested) })
      const saved = draftOf(result)
      setSavedWorkspace(saved); setSavedAt(result.updated_at)
      setWorkspace(current => sameWorkspace(current, requested) ? saved : current)
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : '研究工作区保存失败')
    } finally { setSaving(false) }
  }

  const selected = assets.find(item => item.code === workspace.selected_asset)
  const currentSeries = series?.code === workspace.selected_asset ? series : null
  const visiblePoints = currentSeries?.points.slice(-workspace.visible_range) ?? []
  const priceOption = useMemo(() => ({
    grid: chartGrid,
    tooltip: { trigger: 'axis' as const },
    xAxis: { ...chartAxis, type: 'category' as const, data: visiblePoints.map(point => point.date), boundaryGap: false },
    yAxis: { ...chartAxis, type: 'value' as const, scale: true, splitLine: { lineStyle: { color: chartColors.grid, type: 'dashed' as const } } },
    series: [{ name: currentSeries?.name ?? '观测值', type: 'line' as const, data: visiblePoints.map(point => point.value), showSymbol: false, lineStyle: { color: chartColors.primary, width: 2 }, areaStyle: { color: { type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#b8353c24' }, { offset: 1, color: '#b8353c00' }] } } }],
  }), [currentSeries, visiblePoints])
  return <>
    <div className="analysis-toolbar"><span><span className="status-dot" />训练数据截至 <b>{latest.trained_through}</b> · 模型 {latest.model_version}</span><button className="quiet" disabled={loading} onClick={onRefresh}><Icon name="refresh" />{loading ? '正在刷新…' : '刷新数据'}</button></div>
    <div className="metrics">
      <Metric label="当前市场状态" icon="regimes" value={latest.label} detail={`模型置信度 ${percent(latest.confidence, 1)}`} featured />
      <Metric label="年化波动率" icon="features" value={percent(latest.features.volatility)} detail="20 日滚动窗口 · 年化" />
      <Metric label="中期动量" icon="overview" value={percent(latest.features.momentum)} tone={directionTone(latest.features.momentum)} detail="60 日多资产涨跌幅均值" />
      <Metric label="近期预警" icon="alerts" value={<>{alerts.length}<em>条</em></>} detail={<>最近最多 100 条 <button className="text-button" onClick={() => onNavigate('alerts')}>查看证据 ↗</button></>} />
    </div>
    <div className="terminal-grid market-grid">
      <Panel title="资产目录" subtitle={`${filteredAssets.length} / ${assets.length} 个可用序列`} className="asset-browser">
        <div className="workspace-actions">
          <button className="quiet" aria-pressed={workspace.watchlist_only} disabled={workspaceStatus === 'loading'} onClick={() => updateWorkspace({ watchlist_only: !workspace.watchlist_only })}>{workspace.watchlist_only ? '查看全部资产' : '只看观察列表'} · {workspace.watchlist.length}</button>
          <button className="quiet" disabled={workspaceStatus !== 'ready' || saving || !dirty} onClick={() => void saveWorkspace()}><Icon name="save" />{saving ? '正在保存…' : '保存工作区'}</button>
        </div>
        <p className="workspace-status" role="status">{workspaceStatus === 'loading' ? '正在读取当前账号的研究工作区…' : workspaceStatus === 'error' ? '工作区未加载，当前修改仅保留在本页。' : saving ? '正在保存筛选、观察列表和走势范围…' : saveError ? '保存未完成，请处理后重试。' : dirty ? '有未保存的研究偏好。' : savedAt ? `已保存 · ${new Date(savedAt * 1000).toLocaleString('zh-CN')}` : '修改后可保存到当前账号。'}</p>
        {workspaceError && <ErrorMessage message={workspaceError} onRetry={() => setWorkspaceAttempt(value => value + 1)} retryLabel="重试工作区" />}
        {saveError && <div className="error" role="alert">{saveError}</div>}
        <div className="asset-controls"><input aria-label="搜索资产" placeholder="名称或代码" disabled={workspaceStatus === 'loading'} value={workspace.search} onChange={event => updateWorkspace({ search: event.target.value })} /><select aria-label="资产类别" disabled={workspaceStatus === 'loading'} value={workspace.category} onChange={event => updateWorkspace({ category: event.target.value })}><option value="all">全部类别</option>{[...new Set(assets.map(item => item.category))].map(category => <option key={category}>{category}</option>)}</select></div>
        <div className="asset-list">{filteredAssets.map(item => {
          const watched = workspace.watchlist.includes(item.code)
          return <div className="asset-row" key={item.code}><button className={`asset-item ${item.code === workspace.selected_asset ? 'active' : ''}`} disabled={workspaceStatus === 'loading'} aria-pressed={item.code === workspace.selected_asset} onClick={() => updateWorkspace({ selected_asset: item.code })}><span><strong>{item.name}</strong><small>{item.code} · {item.category}</small></span><em>{item.field === 'yield' ? '收益率' : '收盘价'}</em></button><button className={`watch-toggle ${watched ? 'active' : ''}`} disabled={workspaceStatus === 'loading'} aria-label={`将${item.name}${watched ? '移出' : '加入'}观察列表`} aria-pressed={watched} title={watched ? '移出观察列表' : '加入观察列表'} onClick={() => toggleWatchlist(item.code)}><span aria-hidden="true">{watched ? '★' : '☆'}</span></button></div>
        })}{!filteredAssets.length && <div className="empty">{workspace.watchlist_only && !workspace.watchlist.length ? '观察列表为空，请先加入资产' : '无匹配资产'}</div>}</div>
        <p className="method-note">筛选与观察列表按当前账号保存，不影响模型、预警或回放；资产目录不提供实时报价。</p>
      </Panel>
      <Panel title="资产走势" subtitle={`${selected?.name ?? '请选择资产'} · ${selected?.code ?? '—'} · ${selected?.field === 'yield' ? '收益率（非价格）' : '收盘价'}`} className="asset-chart-panel" action={<div className="segmented" aria-label="观测范围">{[[60, '60 日'], [250, '250 日'], [500, '500 日']].map(([value, label]) => <button key={value} aria-pressed={workspace.visible_range === value} className={workspace.visible_range === value ? 'active' : ''} disabled={workspaceStatus === 'loading'} onClick={() => updateWorkspace({ visible_range: Number(value) as 60 | 250 | 500 })}>{label}</button>)}</div>}>
        {seriesError ? <ErrorMessage message={seriesError} onRetry={() => setSeriesAttempt(value => value + 1)} retryLabel="重试走势查询" /> : workspaceStatus === 'loading' || seriesLoading ? <Loading>正在加载资产序列…</Loading> : !visiblePoints.length ? <div className="chart empty">当前资产没有可用观测值</div> : <Chart option={priceOption} label={`${selected?.name}历史走势`} />}
        <div className="chart-foot"><span>{visiblePoints.length ? `${visiblePoints[0].date} — ${visiblePoints.at(-1)?.date} · ${visiblePoints.length} 个观测值 · ${currentSeries?.unit ?? ''}` : '不同资产保留原始交易日历'}</span><button className="text-button" disabled={!visiblePoints.length} onClick={() => downloadCsv(`${workspace.selected_asset}-${workspace.visible_range}.csv`, [['date', 'value', 'field', 'unit'], ...visiblePoints.map(point => [point.date, point.value, currentSeries?.field, currentSeries?.unit])])}><Icon name="download" />导出 CSV</button></div>
      </Panel>
      <Panel title="状态诊断" subtitle="相对训练窗口的标准化偏离" className="regime-diagnostic" action={<span className="tag">MODEL</span>}>
        <div className="evidence">{latest.contributions.map(item => <div key={item.feature}><span>{featureNames[item.feature] ?? item.feature}</span><div className="bar"><i style={{ width: `${Math.min(100, Math.abs(item.standardized ?? 0) * 35)}%` }} /></div><b>{numeric(item.standardized)}σ</b></div>)}</div>
        <p className="method-note">贡献值表示标准化偏离，不代表因果关系；置信度不是预测正确率。</p>
        <dl className="compact-facts"><div><dt>观测日期</dt><dd>{latest.date}</dd></div><div><dt>训练截止</dt><dd>{latest.trained_through}</dd></div><div><dt>模型版本</dt><dd><code>{latest.model_version}</code></dd></div></dl>
        <button className="panel-link" onClick={() => onNavigate('features')}>深入探索特征 <Icon name="arrow" /></button>
      </Panel>
    </div>
    <Panel title="近期风险信号" subtitle="由确定性规则生成，可逐条复核触发依据" className="table-panel" action={<button className="text-button" onClick={() => onNavigate('alerts')}>全部预警 <Icon name="arrow" /></button>}><AlertList alerts={alerts.slice(0, 5)} compact /></Panel>
    <div className="research-strip"><div><span>EVENT-TIME VALIDATION</span><h3>将一次市场判断，放回历史中检验。</h3><p>只读取事件时间及此前的数据，逐日重现特征、状态和预警。</p></div><button onClick={() => onNavigate('replay')}>打开历史回放 <Icon name="arrow" /></button></div>
  </>
}
