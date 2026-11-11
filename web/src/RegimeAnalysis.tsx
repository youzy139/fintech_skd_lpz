import { useMemo } from 'react'
import RegimeChart from './RegimeChart'
import Icon from './Icon'
import { chartAxis, chartColors, chartGrid } from './chartTheme'
import { directionTone, downloadCsv, numeric, percent } from './format'
import { featureNames, regimeColors } from './labels'
import { Metric, Panel } from './ui'
import type { Regime } from './types'

export default function RegimeAnalysis({ states, latest }: { states: Regime[]; latest: Regime }) {
  const regimeOption = useMemo(() => {
    const visible = states.slice(-500)
    const labels = [...new Set(visible.map(item => item.label))]
    return {
      grid: { ...chartGrid, left: 120 },
      tooltip: { trigger: 'item' as const },
      xAxis: { ...chartAxis, type: 'category' as const, data: visible.map(item => item.date) },
      yAxis: { ...chartAxis, type: 'category' as const, data: labels, splitLine: { show: true, lineStyle: { color: chartColors.grid } } },
      series: labels.map((label, index) => ({ name: label, type: 'scatter' as const, symbolSize: 7, data: visible.filter(item => item.label === label).map(item => [item.date, label]), itemStyle: { color: regimeColors[index % regimeColors.length] } })),
    }
  }, [states])
  const heatOption = useMemo(() => {
    const visible = states.slice(-120)
    const features = Object.keys(featureNames)
    const ranges = features.map(key => {
      const values = visible.map(state => state.features[key]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
      return values.length ? { min: Math.min(...values), max: Math.max(...values) } : { min: 0, max: 0 }
    })
    return {
      grid: { left: 84, right: 24, top: 20, bottom: 80 },
      tooltip: { formatter: (params: unknown) => { const point = params as { value: (string | number | null)[] }; const key = features[Number(point.value[1])]; const raw = point.value[3]; return `${point.value[0]}\n${featureNames[key]}: ${typeof raw === 'number' ? key === 'sample_count' ? raw : key === 'correlation' ? numeric(raw, 4) : percent(raw, 3) : '缺失值'}` } },
      xAxis: { ...chartAxis, type: 'category' as const, data: visible.map(item => item.date) },
      yAxis: { ...chartAxis, type: 'category' as const, data: features.map(key => featureNames[key]) },
      visualMap: { min: 0, max: 1, dimension: 2, calculable: false, orient: 'horizontal' as const, left: 'center', bottom: 5, text: ['区间内较高', '区间内较低'], textStyle: { color: chartColors.muted }, inRange: { color: ['#f6e8e8', '#ddb0b2', '#b8353c', '#74232b'] }, outOfRange: { color: ['#e0e4e3'] } },
      series: [{ type: 'heatmap' as const, data: visible.flatMap(state => features.map((key, index) => { const raw = state.features[key]; const valid = typeof raw === 'number' && Number.isFinite(raw); const { min, max } = ranges[index]; return [state.date, index, valid ? max === min ? .5 : (raw - min) / (max - min) : null, valid ? raw : null] })), itemStyle: { borderColor: '#fff', borderWidth: 1 } }],
    }
  }, [states])
  return <>
    <div className="metrics three"><Metric label="本次加载的状态日" value={states.length.toLocaleString()} detail="最近最多 2,000 日 · walk-forward" /><Metric label="当前状态" value={latest.label} detail={`训练数据截至 ${latest.trained_through}`} featured /><Metric label="当日有效资产" value={<>{numeric(latest.features.sample_count, 0)}<em>个</em></>} detail="实际参与计算的样本量" /></div>
    <Panel title="市场状态时间图谱" subtitle="最近 500 个状态日 · 颜色对应不同状态画像"><RegimeChart option={regimeOption} className="tall" label="市场状态历史时间图谱" /></Panel>
    <Panel title="状态特征热力图" subtitle="最近 120 个状态日 · 每个特征独立归一化"><RegimeChart option={heatOption} className="tall" label="六个市场特征的历史热力图" /><p className="method-note">颜色只比较同一特征在这 120 日内的相对高低，不能直接跨特征比较颜色。悬停查看原始值；灰色为缺失值，不按 0 处理。有效资产数表示当日实际参与计算的资产样本量。</p></Panel>
    <Panel title="最近状态记录" subtitle="训练切片严格排除识别当日" className="table-panel" action={<button className="text-button" onClick={() => downloadCsv('market-states.csv', [['date', 'label', 'confidence', 'model_version', 'trained_through'], ...states.map(item => [item.date, item.label, item.confidence, item.model_version, item.trained_through])])}><Icon name="download" />导出已加载状态</button>}><div className="table-wrap"><table><thead><tr><th>日期</th><th>市场状态</th><th>置信度</th><th>波动率</th><th>动量</th><th>模型版本</th></tr></thead><tbody>{states.slice(-12).reverse().map(item => <tr key={item.date}><td className="numeric">{item.date}</td><td><span className="status-dot" />{item.label}</td><td>{percent(item.confidence, 1)}</td><td>{percent(item.features.volatility)}</td><td className={directionTone(item.features.momentum)}>{percent(item.features.momentum)}</td><td className="muted">{item.model_version}</td></tr>)}</tbody></table></div></Panel>
  </>
}
