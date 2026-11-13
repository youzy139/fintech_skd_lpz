import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { ErrorMessage } from './ui'
import type { GovernanceItem } from './SourceGovernance'

export type FileGovernanceReport = {
  data_version: string; policy_version: string
  file: { id: string; path: string; status: string; error_count: number; sheets: string[] }
  policy: Pick<GovernanceItem, 'name' | 'time_semantics' | 'restriction'>
  records: number; start_date: string | null; end_date: string | null
  undated_records: number; undated_ratio: number | null; statistics_status: string
  fields: { name: string; non_null_count: number; empty_or_absent_count: number | null; empty_or_absent_ratio: number | null }[]
  fields_truncated: boolean; limitations: string[]
  audit_registration?: {
    status: 'not_registered' | 'current' | 'stale' | 'unverifiable' | 'not_comparable'
    audited_at?: string; reason?: string
    report?: {
      audit_status: string; file: { scanned_record_count: number }
      duplicate_excess_count: number; duplicate_group_count: number
      field_inventory_count: number; preaggregated_field_comparison: { status: string; mismatch_count: number }
      dates: { undated_records: number; start_date: string | null; end_date: string | null }
    }
  }
}
const number = (value: number | null) => value === null ? '不可计算' : value.toLocaleString()
const ratio = (value: number | null) => value === null ? '不可计算' : `${(value * 100).toFixed(2)}%`

export default function FileGovernance({ sourceId, onClose }: { sourceId: string; onClose: () => void }) {
  const panel = useRef<HTMLElement>(null)
  const [report, setReport] = useState<FileGovernanceReport | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => { panel.current?.scrollIntoView?.({ block: 'start' }) }, [sourceId])
  useEffect(() => {
    const controller = new AbortController()
    setReport(null); setError('')
    api<FileGovernanceReport>(`/api/data/files/${encodeURIComponent(sourceId)}/governance`, controller.signal)
      .then(result => { if (!controller.signal.aborted) setReport(result) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
    return () => controller.abort()
  }, [sourceId, attempt])
  return <section ref={panel} className="file-governance governance-card" aria-label="文件质量证据">
    <header><h3>文件质量证据</h3><button className="text-button" onClick={onClose}>关闭文件质量证据</button></header>
    {error && <ErrorMessage message={error} onRetry={() => setAttempt(value => value + 1)} retryLabel="重试文件质量证据" />}
    {!report && !error && <p role="status">正在读取文件质量证据…</p>}
    {report && <>
      <p className="file-quality-path">{report.file.path}</p>
      <dl>
        <div><dt>入库状态</dt><dd>{report.file.status === 'imported' ? '已入库' : report.file.status} · 文件级导入错误 {number(report.file.error_count)}</dd></div>
        <div><dt>逻辑记录</dt><dd>{number(report.records)} 条 · {report.file.sheets.length} 个 Sheet</dd></div>
        <div><dt>时间覆盖</dt><dd>{report.start_date ? `${report.start_date} 至 ${report.end_date}` : '暂无有日期的记录'}</dd></div>
        <div><dt>无日期记录</dt><dd>{number(report.undated_records)} 条 · {ratio(report.undated_ratio)}</dd></div>
        <div><dt>统计范围核对</dt><dd>{report.statistics_status === 'consistent' ? '已通过数值范围检查' : report.statistics_status === 'unavailable' ? '导入未完成，比例不可计算' : '预聚合统计不一致，比例不可计算'}</dd></div>
        <div><dt>重复 / 语义异常</dt><dd>未评估 / 未评估</dd></div>
      </dl>
      <section className="source-audit-registration" aria-label="离线逐文件审计">
        <h4>离线逐文件审计</h4>
        {!report.audit_registration || report.audit_registration.status === 'not_registered'
          ? <p>尚无已登记的快照审计报告</p>
          : report.audit_registration.status === 'not_comparable'
            ? <p>当前为 ClickHouse active 数据；尚无可比的逐文件内容摘要，SQLite 暂存审计不会附加到此处。</p>
            : report.audit_registration.status !== 'current'
              ? <p role="status">审计报告已过期或无法验证，请对当前 SQLite 快照重新审计并登记。</p>
              : <>
                <p>当前报告 · 审计时间 {report.audit_registration.audited_at}</p>
                <dl>
                  <div><dt>扫描记录</dt><dd>{number(report.audit_registration.report?.file.scanned_record_count ?? null)} 条</dd></div>
                  <div><dt>完整记录重复</dt><dd>{number(report.audit_registration.report?.duplicate_excess_count ?? null)} 条余量 · {number(report.audit_registration.report?.duplicate_group_count ?? null)} 组</dd></div>
                  <div><dt>字段目录复核</dt><dd>{number(report.audit_registration.report?.field_inventory_count ?? null)} 个字段 · {number(report.audit_registration.report?.preaggregated_field_comparison.mismatch_count ?? null)} 项差异</dd></div>
                  <div><dt>审计日期覆盖</dt><dd>{report.audit_registration.report?.dates.start_date ?? '无日期'} 至 {report.audit_registration.report?.dates.end_date ?? '无日期'} · 无日期 {number(report.audit_registration.report?.dates.undated_records ?? null)} 条</dd></div>
                </dl>
              </>}
      </section>
      <p>{report.policy.time_semantics}；{report.policy.restriction}</p>
      <h4>字段非空与空缺证据</h4>
      <p className="catalog-note">空缺包含空字符串、null 和未出现字段，不等于必填字段缺失。多 Sheet 按文件合并统计。</p>
      {report.records > 0 && report.statistics_status === 'consistent' && <p className="catalog-note">本次展示 {report.fields.length} 个字段，其中 {report.fields.filter(field => field.non_null_count === 0).length} 个全空。字段目录来自已解析记录，空文件表头与历史未回填字段可能未登记。</p>}
      {report.fields.length ? <div className="table-wrap"><table><thead><tr><th>原始字段</th><th>非空（条）</th><th>空缺（条）</th><th>空缺比例</th></tr></thead><tbody>{report.fields.map(field => <tr key={field.name}><td>{field.name}</td><td>{number(field.non_null_count)}</td><td>{number(field.empty_or_absent_count)}</td><td>{ratio(field.empty_or_absent_ratio)}</td></tr>)}</tbody></table></div> : <p>暂无已登记字段证据</p>}
      {report.fields_truncated && <p>字段超过 100 项，仅展示前 100 项。</p>}
      <details><summary>统计口径与限制</summary><ul>{report.limitations.map(item => <li key={item}>{item}</li>)}</ul><p className="governance-version">目录版本：{report.data_version}<br />政策版本：{report.policy_version}</p></details>
    </>}
  </section>
}
