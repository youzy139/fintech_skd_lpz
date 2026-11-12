import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import Chart from './Chart'
import { chartAxis, chartColors, chartGrid } from './chartTheme'
import { directionTone, numeric, percent } from './format'
import { featureNames } from './labels'
import { ErrorMessage, Loading, Metric, Panel } from './ui'
import type { FeatureMetadata, LatestFeatures, Regime } from './types'

const unitNames: Record<string, string> = { log_return: '对数收益', annualized_ratio: '年化比率', ratio: '比率', coefficient: '相关系数', assets: '个资产' }

export default function FeatureAnalysis({ states, latest }: { states: Regime[]; latest: Regime }) {
  const [feature, setFeature] = useState('volatility')
  const [metadata, setMetadata] = useState<FeatureMetadata | null>(null)
  const [current, setCurrent] = useState<LatestFeatures | null>(null)
  const [currentError, setCurrentError] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt(value => value + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    setCurrentError('')
    void api<FeatureMetadata>('/api/features/metadata', controller.signal).then(setMetadata).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '特征定义暂不可用')
    })
    void api<LatestFeatures>('/api/features/latest', controller.signal).then(setCurrent).catch(reason => {
      if (!controller.signal.aborted) setCurrentError(reason instanceof Error ? reason.message : '最新特征暂不可用')
    })
    return () => controller.abort()
  }, [attempt])
  const featureOption = useMemo(() => ({
    grid: chartGrid,
    tooltip: { trigger: 'axis' as const },
    xAxis: { ...chartAxis, type: 'category' as const, data: states.slice(-500).map(item => item.date) },
    yAxis: { ...chartAxis, type: 'value' as const, scale: true, splitLine: { lineStyle: { color: chartColors.grid } } },
    series: [{ name: featureNames[feature], type: 'line' as const, showSymbol: false, connectNulls: false, data: states.slice(-500).map(item => item.features[feature]) ?? [], lineStyle: { width: 2, color: chartColors.primary } }],
  }), [states, feature])
  const displayed = current ?? latest
  return <>
    {currentError && <ErrorMessage message={`最新特征读取失败：${currentError}。当前显示最近成功获取的数据（${displayed.date}）。`} onRetry={retry} />}
    <div className="metrics three">{['volatility', 'momentum', 'correlation'].map(key => <Metric key={key} label={featureNames[key]} value={key === 'correlation' ? numeric(displayed.features[key], 3) : percent(displayed.features[key])} tone={key === 'momentum' ? directionTone(displayed.features[key]) : ''} detail={`最新观测日 ${displayed.date}`} />)}</div>
    <div className="feature-workspace"><Panel title="特征历史走势" subtitle="最近 500 个状态日 · 缺失值保持断点" action={<select aria-label="历史特征" value={feature} onChange={event => setFeature(event.target.value)}>{Object.entries(featureNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>}><Chart option={featureOption} label={`${featureNames[feature]}历史变化`} /></Panel><Panel title="指标口径" className="feature-glossary">
      {error ? <ErrorMessage message={error} onRetry={retry} /> : !metadata ? <Loading>正在加载特征定义…</Loading> : <div className="glossary">{metadata.feature_contract.features.map(item => <p key={item.name}><b>{item.title}</b><span>{item.formula}</span><small>{item.model_input ? '参与状态模型' : '仅供展示'} · 窗口 {item.window} 行 · 最少 {item.minimum_observations} 个观测 · 单位 {unitNames[item.unit] ?? item.unit}</small></p>)}</div>}
    </Panel></div>
    {metadata && <Panel title="计算与来源" subtitle={`特征算法 ${metadata.feature_contract.algorithm}`}><p>{metadata.feature_contract.input}</p><p>{metadata.feature_contract.time_basis}</p><p>{metadata.feature_contract.visibility}</p><p>{metadata.feature_contract.missing_policy}</p><details><summary>查看版本与输入摘要</summary><dl className="contract-versions"><dt>特征版本</dt><dd>{metadata.feature_contract.feature_version}</dd><dt>行情输入摘要</dt><dd>{metadata.input_version}</dd><dt>目录数据版本</dt><dd>{metadata.data_version}</dd><dt>状态模型</dt><dd>{metadata.state_model_version ?? '暂无'}</dd><dt>当前参数</dt><dd>{JSON.stringify(metadata.model_parameters)}</dd></dl></details></Panel>}
    <Panel title="特征偏离程度" subtitle="绝对标准化值越大，偏离训练窗口中心越远"><div className="feature-list">{displayed.contributions.map(item => <div className="feature-row" key={item.feature}><div><span>{featureNames[item.feature] ?? item.feature}</span><strong>{numeric(item.standardized, 3)}σ</strong></div><div className="track"><i className={(item.standardized ?? 0) < 0 ? 'below' : ''} style={{ width: `${Math.min(100, Math.abs(item.standardized ?? 0) * 35)}%` }} /></div><small>原始值 {numeric(item.value, 4)}</small></div>)}</div><p className="method-note">偏离用于解释聚类位置，不是特征重要性、因果贡献或收益预测。</p></Panel>
  </>
}
