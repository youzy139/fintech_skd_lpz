import { percent } from './format'
import { ruleNames } from './labels'
import { Panel } from './ui'
import type { CoverageSensitivity, StabilityPeriod } from './types'

export default function CoverageSensitivityPanel({ data, period }: { data: CoverageSensitivity; period: StabilityPeriod }) {
  return <Panel title="覆盖敏感性消融" subtitle={`${data.coverage_sensitivity_version} · 仅过滤既有输出，不重训模型`} className="table-panel">
    <div className="table-wrap"><table className="coverage-sensitivity-table"><thead><tr><th>最少有效收益资产</th><th>保留状态日</th><th>排除状态日</th><th>保留比例</th>{Object.keys(ruleNames).filter(rule => ['HIGH_VOLATILITY', 'HIGH_CORRELATION', 'REGIME_CHANGE'].includes(rule)).map(rule => <th key={rule}>{ruleNames[rule]}<small>保留 / 原始（排除）</small></th>)}</tr></thead><tbody>{data.periods[period].map(row => <tr key={row.minimum_sample_count}><td><strong>≥ {row.minimum_sample_count} 个</strong></td><td>{row.eligible_days.toLocaleString()} / {row.state_days.toLocaleString()}</td><td>{row.excluded_days.toLocaleString()}</td><td>{percent(row.eligible_share, 2)}</td>{Object.entries(row.alerts).map(([rule, counts]) => <td key={rule}>{counts.retained} / {counts.original}<small className="table-subtitle">排除 {counts.excluded}</small></td>)}</tr>)}</tbody></table></div>
    <p className="method-note">{data.limitations} 规则参数：{JSON.stringify(data.alert_settings)} 预警按事件日过滤，区间首日切换可能相对区间外前一状态日产生，因此可与仅统计区间内相邻状态的切换数不同。</p>
  </Panel>
}
