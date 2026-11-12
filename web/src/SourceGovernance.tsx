import { useEffect, useState } from 'react'
import { api } from './api'
import { ErrorMessage } from './ui'

export type GovernanceItem = {
  kind: string; name: string; usage: 'model' | 'background' | 'catalog_only'
  time_semantics: string; restriction: string; files: number; records: number
  start_date: string | null; end_date: string | null; undated_records: number; undated_ratio: number | null
  statistics_status: string; duplicate_records: number | null; invalid_records: number | null
  fields: { name: string; non_null_count: number }[]; field_inventory_may_be_truncated: boolean
  lifecycle: { raw: string; online: string; archive: string; recompute: string; delete: string; automatic_delete: boolean }
}
export type GovernanceReport = {
  schema: string; policy_version: string; data_version: string; scope: string
  items: GovernanceItem[]; limitations: string[]
}
const usageNames = { model: '行情模型输入', background: '仅背景证据', catalog_only: '仅目录检索' }
const count = (value: number | null) => value === null ? '未评估' : value.toLocaleString()

export default function SourceGovernance({ kind }: { kind: string }) {
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState<GovernanceReport | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setReport(null); setError('')
    const params = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    api<GovernanceReport>(`/api/data/governance${params}`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setReport(result) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
    return () => controller.abort()
  }, [open, kind, attempt])
  return <details className="panel source-governance" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>来源质量与保留策略</summary>
    <div className="governance-body">
      <p className="catalog-note">按来源类型核对日期覆盖、字段证据与使用边界。重复和异常尚未评估；保留策略不触发删除、归档或重算。</p>
      {error && <ErrorMessage message={error} onRetry={() => setAttempt(value => value + 1)} retryLabel="重试来源治理报告" />}
      {open && !report && !error && <div className="empty" role="status">正在读取来源治理报告…</div>}
      {report && <>
        <div className="governance-grid">{report.items.map(item => <article className="governance-card" key={item.kind}>
          <header><h3>{item.name}</h3><span>{usageNames[item.usage]}</span></header>
          <dl>
            <div><dt>目录规模</dt><dd>{item.files.toLocaleString()} 个文件 · {item.records.toLocaleString()} 条逻辑记录</dd></div>
            <div><dt>日期覆盖</dt><dd>{item.start_date ? `${item.start_date} 至 ${item.end_date}` : '暂无有日期的记录'}</dd></div>
            <div><dt>无日期记录</dt><dd>{item.undated_records.toLocaleString()} 条 · {item.undated_ratio === null ? '比例不可计算' : `${(item.undated_ratio * 100).toFixed(2)}%`}</dd></div>
            <div><dt>重复 / 异常记录</dt><dd>{count(item.duplicate_records)} / {count(item.invalid_records)}</dd></div>
            <div><dt>时间口径</dt><dd>{item.time_semantics}</dd></div>
            <div><dt>使用限制</dt><dd>{item.restriction}</dd></div>
          </dl>
          {item.statistics_status !== 'consistent' && <p role="alert">统计不一致，请核对目录预聚合，当前不计算比例。</p>}
          <details className="field-catalog"><summary>字段非空证据（{item.fields.length} 项）</summary><p>以该类型全部逻辑记录作参照，不是必填字段完整率。{item.field_inventory_may_be_truncated && '已达到 100 项展示上限，字段目录可能不完整。'}</p><div>{item.fields.map(field => <span key={field.name}><b>{field.name}</b><small>{field.non_null_count.toLocaleString()} 条非空</small></span>)}</div></details>
          <details className="governance-policy"><summary>保留、归档与重算策略</summary><dl>{([['原始层', item.lifecycle.raw], ['在线层', item.lifecycle.online], ['归档', item.lifecycle.archive], ['重算', item.lifecycle.recompute], ['删除', item.lifecycle.delete]] as const).map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}</dl><p>{item.lifecycle.automatic_delete ? '自动删除已启用' : '自动删除未启用；保留期限待团队确认'}</p></details>
        </article>)}</div>
        <details className="governance-policy"><summary>报告范围与版本</summary><p>本报告按来源类型聚合，不能代替逐文件质量审计。</p><ul>{report.limitations.map(item => <li key={item}>{item}</li>)}</ul><dl><div><dt>目录版本</dt><dd>{report.data_version}</dd></div><div><dt>策略版本</dt><dd>{report.policy_version}</dd></div></dl></details>
      </>}
    </div>
  </details>
}
