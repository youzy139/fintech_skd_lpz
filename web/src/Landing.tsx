import Icon from './Icon'
import { directionTone, numeric, percent } from './format'
import type { Page } from './navigation'
import type { HomeSummary } from './types'
import { ErrorMessage, Metric, Panel } from './ui'

export default function Landing({ data, onEnter, onNavigate, error, onRetry }: { data: HomeSummary | null; onEnter: () => void; onNavigate: (page: Page) => void; error: string; onRetry: () => void }) {
  const latest = data?.latest
  return <div className="home-dashboard">
    {error && <ErrorMessage message={error} onRetry={onRetry} retryLabel="重新加载摘要" />}
    <section className="home-command"><div><p className="eyebrow">MARKET REGIME RESEARCH</p><h2>读懂市场状态，<span>让判断有据可循。</span></h2><p>把多资产行情、状态模型与风险证据放在同一视野。所有结论来自真实历史数据与可复核计算。</p><div className="hero-actions"><button className="primary-action" onClick={onEnter}>进入市场工作台 <Icon name="arrow" /></button><button className="hero-secondary" onClick={() => onNavigate('replay')}><Icon name="replay" />探索历史回放</button></div></div><dl className="home-observation"><div><dt>最新市场观测日</dt><dd>{latest?.date ?? '—'}</dd></div><div><dt>当前市场状态</dt><dd>{latest?.label ?? '—'}</dd></div><div><dt>模型置信度</dt><dd>{percent(latest?.confidence, 1)}</dd></div><div><dt>训练数据截至</dt><dd>{latest?.trained_through ?? '—'}</dd></div></dl></section>
    <div className="metrics home-metrics"><Metric label="年化波动率" value={percent(latest?.features.volatility)} detail="20 日滚动 · 年化" /><Metric label="60 日动量" value={percent(latest?.features.momentum)} tone={directionTone(latest?.features.momentum)} detail="多资产涨跌幅均值" /><Metric label="资产相关性" value={numeric(latest?.features.correlation, 3)} detail="60 日成对相关均值" /><Metric label="历史预警" value={<>{data?.alert_count.toLocaleString() ?? '—'}<em>条</em></>} detail="确定性规则生成" featured /></div>
    <div className="data-ribbon"><div><span>DATA FOUNDATION</span><p>真实数据，统一研究口径。</p></div><div><strong>{data?.loaded_assets.toLocaleString() ?? '—'}<small>个</small></strong><span>有效资产序列</span></div><div><strong>{data?.total_rows.toLocaleString() ?? '—'}</strong><span>有效行情记录</span></div><div><strong>{data?.state_count.toLocaleString() ?? '—'}</strong><span>历史状态日</span></div></div>
    <section className="home-tools"><div className="section-heading"><span>RESEARCH WORKSPACE</span><h2>从一个更清晰的视角，观察市场。</h2></div><div className="capability-grid">{[
      ['regimes', '识别市场环境', '观察状态时间图谱与特征热力图，理解波动、动量与资产联动。', 'regimes'],
      ['alerts', '追溯风险证据', '核对触发规则、历史阈值和当时已经公开的事件背景。', 'alerts'],
      ['replay', '重现历史过程', '按事件时间逐日重新计算，在当时可见的数据范围内检验判断。', 'replay'],
    ].map(([icon, title, description, page], index) => <article key={page}><div><Icon name={icon} /><span>0{index + 1}</span></div><h3>{title}</h3><p>{description}</p><button onClick={() => onNavigate(page as Page)}>打开研究工具 <Icon name="arrow" /></button></article>)}</div></section>
    <div className="home-bottom"><Panel title="可复核的方法链路"><ol className="method-steps"><li><span>01</span><div><h3>保留数据与时间</h3><p>原始字段、来源文件和事件日期可追溯。</p></div></li><li><span>02</span><div><h3>计算多资产特征</h3><p>收益、波动、动量、趋势与相关性。</p></div></li><li><span>03</span><div><h3>逐日识别与规则预警</h3><p>Walk-forward · PCA / KMeans · 历史分位阈值。</p></div></li></ol></Panel><Panel title="研究边界"><div className="research-boundary"><Icon name="alerts" /><p>当前为历史数据研究环境，不提供实时行情或买卖指令。模型置信度是聚类距离权重，不代表预测正确率。</p><button className="text-button" onClick={() => onNavigate('features')}>查看特征与计算口径 <Icon name="arrow" /></button></div></Panel></div>
  </div>
}
