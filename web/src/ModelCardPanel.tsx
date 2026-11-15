import { numeric, percent } from './format'
import { Panel } from './ui'
import type { ModelCard } from './types'

export default function ModelCardPanel({ card }: { card: ModelCard }) {
  const excluded = card.assets.filter(asset => !asset.model_input)
  return <Panel title="模型卡与输入覆盖" subtitle={`${card.model_card_version} · 只描述实际输入、覆盖和适用边界`} className="model-card-panel">
    <div className="model-card-purpose"><p><strong>适用：</strong>{card.intended_use}</p><p><strong>不适用：</strong>{card.out_of_scope}</p></div>
    <dl className="evaluation-facts">
      <div><dt>价格模型输入</dt><dd>{card.price_assets} / {card.loaded_series} 个已加载序列</dd></div>
      <div><dt>有效观测</dt><dd>{card.valid_observations.toLocaleString()} 条 · 其中价格 {card.price_observations.toLocaleString()}<small>非正价格 {card.nonpositive_price_rows} · 无效 {card.invalid_rows} · 重复日期 {card.duplicate_dates}</small></dd></div>
      <div><dt>首日后完整特征覆盖</dt><dd>{percent(card.post_first_feature_coverage, 2)}<small>{card.covered_after_first_feature_days} / {card.post_first_feature_union_days} 个价格并集观测日</small></dd></div>
      <div><dt>状态日有效收益资产</dt><dd>中位 {numeric(card.state_sample_count.median, 1)} · 范围 {numeric(card.state_sample_count.min, 0)}～{numeric(card.state_sample_count.max, 0)}<small>最新 {numeric(card.state_sample_count.latest, 0)} 个</small></dd></div>
    </dl>
    <div className="coverage-note">
      <p>分析起点 {card.analysis_start}，首个完整特征日 {card.first_feature_day ?? '—'}，最后特征日 {card.last_feature_day ?? '—'}。首个完整特征日之后仍有 <strong>{card.dropped_after_first_feature_days}</strong> 个并集观测日未形成完整特征。</p>
      <p>{card.state_days_below_price_assets} 个状态日的有效收益资产数少于全部 {card.price_assets} 个价格资产；这包含资产上市/观测起点差异，不直接等同于数据错误。</p>
      {card.catalog_missing_assets.length > 0 && <p>目录缺少可用行情：{card.catalog_missing_assets.join('、')}。不补造序列。</p>}
      {excluded.length > 0 && <p>未进入价格模型：{excluded.map(asset => `${asset.name}（${asset.field}）`).join('、')}。</p>}
      {card.dropped_after_first_feature_dates.length > 0 && <details className="missing-days"><summary>查看 {card.dropped_after_first_feature_dates.length} 个未形成完整特征的日期</summary><p>{card.dropped_after_first_feature_dates.join('、')}</p></details>}
    </div>
    <details className="asset-coverage"><summary>查看 {card.assets.length} 项资产覆盖明细</summary><div className="table-wrap"><table><thead><tr><th>资产</th><th>字段 / 模型输入</th><th>实际观测区间</th><th>有效 / 目录条数</th><th>条数对照</th><th>非正价格</th><th>无效行</th><th>重复日期</th></tr></thead><tbody>{card.assets.map(asset => <tr key={asset.code}><td><strong>{asset.name}</strong><small className="table-subtitle">{asset.code} · {asset.category}</small></td><td>{asset.field} / {asset.model_input ? '是' : '否'}</td><td className="numeric">{asset.observed_start ?? '—'} ～ {asset.observed_end ?? '—'}</td><td>{asset.valid_rows.toLocaleString()} / {asset.declared_rows.toLocaleString()}</td><td>{percent(asset.observed_vs_declared, 2)}</td><td>{asset.nonpositive_rows}</td><td>{asset.invalid_rows}</td><td>{asset.duplicate_dates}</td></tr>)}</tbody></table></div></details>
    <ul className="evaluation-limitations">{card.limitations.map(item => <li key={item}>{item}</li>)}</ul>
  </Panel>
}
