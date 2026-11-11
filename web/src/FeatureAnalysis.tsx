import { useMemo, useState } from 'react'
import Chart from './Chart'
import { chartAxis, chartColors, chartGrid } from './chartTheme'
import { directionTone, numeric, percent } from './format'
import { featureNames } from './labels'
import { Metric, Panel } from './ui'
import type { Regime } from './types'

export default function FeatureAnalysis({ states, latest }: { states: Regime[]; latest: Regime }) {
  const [feature, setFeature] = useState('volatility')
  const featureOption = useMemo(() => ({
    grid: chartGrid,
    tooltip: { trigger: 'axis' as const },
    xAxis: { ...chartAxis, type: 'category' as const, data: states.slice(-500).map(item => item.date) },
    yAxis: { ...chartAxis, type: 'value' as const, scale: true, splitLine: { lineStyle: { color: chartColors.grid } } },
    series: [{ name: featureNames[feature], type: 'line' as const, showSymbol: false, connectNulls: false, data: states.slice(-500).map(item => item.features[feature]) ?? [], lineStyle: { width: 2, color: chartColors.primary } }],
  }), [states, feature])
  return <>
    <div className="metrics three">{['volatility', 'momentum', 'correlation'].map(key => <Metric key={key} label={featureNames[key]} value={key === 'correlation' ? numeric(latest.features[key], 3) : percent(latest.features[key])} tone={key === 'momentum' ? directionTone(latest.features[key]) : ''} detail={`最新观测日 ${latest.date}`} />)}</div>
    <div className="feature-workspace"><Panel title="特征历史走势" subtitle="最近 500 个状态日 · 缺失值保持断点" action={<select aria-label="历史特征" value={feature} onChange={event => setFeature(event.target.value)}>{Object.entries(featureNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>}><Chart option={featureOption} label={`${featureNames[feature]}历史变化`} /></Panel><Panel title="指标口径" className="feature-glossary"><div className="glossary"><p><b>市场收益</b>各价格资产当日对数收益的横截面均值。</p><p><b>年化波动率</b>市场收益在 20 日窗口内的标准差乘 √252。</p><p><b>中期动量</b>各价格资产过去 60 日涨跌幅的均值。</p><p><b>资产相关性</b>60 日窗口内资产收益成对相关系数均值。</p><p><b>短期趋势</b>价格相对 20 日均线偏离的均值，不参与当前聚类。</p></div></Panel></div>
    <Panel title="特征偏离程度" subtitle="绝对标准化值越大，偏离训练窗口中心越远"><div className="feature-list">{latest.contributions.map(item => <div className="feature-row" key={item.feature}><div><span>{featureNames[item.feature] ?? item.feature}</span><strong>{numeric(item.standardized, 3)}σ</strong></div><div className="track"><i className={(item.standardized ?? 0) < 0 ? 'below' : ''} style={{ width: `${Math.min(100, Math.abs(item.standardized ?? 0) * 35)}%` }} /></div><small>原始值 {numeric(item.value, 4)}</small></div>)}</div><p className="method-note">偏离用于解释聚类位置，不是特征重要性、因果贡献或收益预测。</p></Panel>
  </>
}
