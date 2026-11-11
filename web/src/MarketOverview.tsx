import { useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import Icon from './Icon'
import { api } from './api'
import { chartAxis, chartColors, chartGrid } from './chartTheme'
import { directionTone, downloadCsv, numeric, percent } from './format'
import { featureNames } from './labels'
import { AlertList, ErrorMessage, Loading, Metric, Panel } from './ui'
import type { Alert, Asset, AssetSeries, Regime } from './types'
import type { Page } from './navigation'

export default function MarketOverview({ assets, latest, alerts, loading, onRefresh, onNavigate }: { assets: Asset[]; latest: Regime; alerts: Alert[]; loading: boolean; onRefresh: () => void; onNavigate: (page: Page) => void }) {
  const [selectedAsset, setSelectedAsset] = useState('SPX.GI')
  const [assetCategory, setAssetCategory] = useState('all')
  const [assetSearch, setAssetSearch] = useState('')
  const [series, setSeries] = useState<AssetSeries | null>(null)
  const [seriesError, setSeriesError] = useState('')
  const [seriesLoading, setSeriesLoading] = useState(false)
  const [seriesAttempt, setSeriesAttempt] = useState(0)
  const [range, setRange] = useState(500)
  const filteredAssets = useMemo(() => assets.filter(item => (assetCategory === 'all' || item.category === assetCategory) && `${item.name} ${item.code}`.toLowerCase().includes(assetSearch.trim().toLowerCase())), [assets, assetCategory, assetSearch])
  useEffect(() => {
    if (!filteredAssets.some(item => item.code === selectedAsset)) setSelectedAsset(filteredAssets[0]?.code ?? '')
  }, [filteredAssets, selectedAsset])
  useEffect(() => {
    if (!selectedAsset) { setSeries(null); return }
    const controller = new AbortController()
    setSeries(null); setSeriesLoading(true); setSeriesError('')
    api<AssetSeries>(`/api/assets/${encodeURIComponent(selectedAsset)}/series?limit=500`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setSeries(result) })
      .catch(reason => { if (!controller.signal.aborted) setSeriesError(reason instanceof Error ? reason.message : '资产序列加载失败') })
      .finally(() => { if (!controller.signal.aborted) setSeriesLoading(false) })
    return () => controller.abort()
  }, [selectedAsset, seriesAttempt])
  const selected = assets.find(item => item.code === selectedAsset)
  const currentSeries = series?.code === selectedAsset ? series : null
  const visiblePoints = currentSeries?.points.slice(-range) ?? []
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
        <div className="asset-controls"><input aria-label="搜索资产" placeholder="名称或代码" value={assetSearch} onChange={event => setAssetSearch(event.target.value)} /><select aria-label="资产类别" value={assetCategory} onChange={event => setAssetCategory(event.target.value)}><option value="all">全部类别</option>{[...new Set(assets.map(item => item.category))].map(category => <option key={category}>{category}</option>)}</select></div>
        <div className="asset-list">{filteredAssets.map(item => <button key={item.code} className={`asset-item ${item.code === selectedAsset ? 'active' : ''}`} aria-pressed={item.code === selectedAsset} onClick={() => setSelectedAsset(item.code)}><span><strong>{item.name}</strong><small>{item.code} · {item.category}</small></span><em>{item.field === 'yield' ? '收益率' : '收盘价'}</em></button>)}{!filteredAssets.length && <div className="empty">无匹配资产</div>}</div>
        <p className="method-note">资产目录不提供实时报价；选择后加载真实历史序列。</p>
      </Panel>
      <Panel title="资产走势" subtitle={`${selected?.name ?? '请选择资产'} · ${selected?.code ?? '—'} · ${selected?.field === 'yield' ? '收益率（非价格）' : '收盘价'}`} className="asset-chart-panel" action={<div className="segmented" aria-label="观测范围">{[[60, '60 日'], [250, '250 日'], [500, '500 日']].map(([value, label]) => <button key={value} aria-pressed={range === value} className={range === value ? 'active' : ''} onClick={() => setRange(Number(value))}>{label}</button>)}</div>}>
        {seriesError ? <ErrorMessage message={seriesError} onRetry={() => setSeriesAttempt(value => value + 1)} retryLabel="重试走势查询" /> : seriesLoading ? <Loading>正在加载资产序列…</Loading> : !visiblePoints.length ? <div className="chart empty">当前资产没有可用观测值</div> : <Chart option={priceOption} label={`${selected?.name}历史走势`} />}
        <div className="chart-foot"><span>{visiblePoints.length ? `${visiblePoints[0].date} — ${visiblePoints.at(-1)?.date} · ${visiblePoints.length} 个观测值 · ${currentSeries?.unit ?? ''}` : '不同资产保留原始交易日历'}</span><button className="text-button" disabled={!visiblePoints.length} onClick={() => downloadCsv(`${selectedAsset}-${range}.csv`, [['date', 'value', 'field', 'unit'], ...visiblePoints.map(point => [point.date, point.value, currentSeries?.field, currentSeries?.unit])])}><Icon name="download" />导出 CSV</button></div>
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
