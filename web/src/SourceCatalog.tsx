import { FormEvent, useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import { api } from './api'

type Summary = { total_files: number; imported_files: number; total_records: number; errors: number; groups: { kind: string; files: number; records: number }[] }
type Overview = { kind: string | null; files: number; records: number; start_date: string | null; end_date: string | null; undated_records: number; granularity: 'day' | 'month' | 'year'; trend: { period: string; count: number }[]; fields: { name: string; non_null_count: number }[] }
type SourceFile = { id: string; kind: string; path: string; status: string; record_count: number; error_count: number; sheets: string[]; error?: string; size: number }
type SourceRecord = { source_id: string; source_path: string; kind: string; record_index: number; event_date: string | null; title: string; payload: Record<string, unknown>; tags: string[] }
type TagItem = { tag: string; records: number }
type Page<T> = { total: number; offset: number; limit: number; items: T[] }

const kindNames: Record<string, string> = { asset: '资产行情', calendar: '宏观日历', commodity: '商品成交', indicator: '脱敏指标', news: '新闻', publication: '公众号', research: '研究摘要', social: '社交媒体' }
const kindDescriptions: Record<string, string> = {
  asset: '股票、债券、商品和汇率的历史行情，用于计算收益、波动、动量与资产联动。',
  calendar: '宏观指标的公布时间、前值、预测值与实际值；记录量不代表经济好坏。',
  commodity: '商品期货日成交额，单位为万亿元，用于观察市场活跃程度。',
  indicator: 'X01–X31 脱敏指标，保留原始 Sheet、日期和序列，不推断未知业务含义。',
  news: '新闻标题与正文的时间序列。当前展示接入结果，尚未计算情绪或市场影响。',
  publication: '公众号文章索引，可按日期、相关方和原文链接追溯。',
  research: '机构研究摘要，包含主要观点、事实依据和关键数据等文本内容。',
  social: '社交媒体帖子及互动信息。当前展示真实帖子，尚未计算情绪倾向。',
}
const fieldNames: Record<string, string> = {
  _sheet: '来源 Sheet', date: '日期', close: '收盘价', yield: '收益率（%）', created_at_twitter: '发帖时间', text: '帖子正文',
  content: '正文内容', institution: '机构', title: '标题', 日期: '日期', 文章标题: '文章标题', 相关方: '相关方', 链接: '原文链接',
  IndicatorName: '指标名称', OccurDate: '公布日期', OccurTime: '公布时间', HomeCountry: '国家编码', IndicatorFormer: '前值', IndicatorForecast: '预测值', IndicatorFact: '实际值',
  '成交额（万亿元）': '成交额（万亿元）',
}
const granularityNames = { day: '按日', month: '按月', year: '按年' }

function fieldName(name: string) {
  const match = /^column_(\d+)$/.exec(name)
  return match ? `原始第 ${match[1]} 列` : fieldNames[name] ?? name
}

function fieldValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function plainText(value: unknown) {
  const raw = fieldValue(value)
  if (raw === '—') return ''
  const document = new DOMParser().parseFromString(raw, 'text/html')
  return (document.body.textContent ?? '').replace(/\s+/g, ' ').trim()
}

function safeUrl(value: unknown) {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : null
  } catch { return null }
}

function isAbort(reason: unknown) {
  return reason instanceof DOMException && reason.name === 'AbortError'
}

function RecordCard({ record }: { record: SourceRecord }) {
  const [expanded, setExpanded] = useState(false)
  const payload = record.payload
  let title = record.title
  let text = ''
  let fields: [string, unknown][] = []
  let link: string | null = null
  if (record.kind === 'news') {
    title = fieldValue(payload.column_2) || record.title
    text = plainText(payload.column_3)
  } else if (record.kind === 'social') {
    title = '社交媒体帖子'
    text = plainText(payload.text)
  } else if (record.kind === 'research') {
    text = plainText(payload.content)
    fields = [['institution', payload.institution]]
  } else if (record.kind === 'publication') {
    text = plainText(payload.文章标题)
    fields = [['相关方', payload.相关方]]
    link = safeUrl(payload.链接)
  } else {
    fields = Object.entries(payload).filter(([, value]) => typeof value !== 'object').slice(0, 8)
  }
  const shortText = text.length > 320 ? `${text.slice(0, 320)}…` : text
  return <article className="content-record">
    <header><div><span className="record-kind">{kindNames[record.kind] ?? record.kind}</span><h3>{title || '未命名记录'}</h3></div><time>{record.event_date ?? '无日期'}</time></header>
    <small className="record-source" title={record.source_path}>{record.source_path}</small>
    {record.tags.length > 0 && <div className="record-tags">{record.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}
    {text && <p className="record-summary">{expanded ? text : shortText}</p>}
    {text.length > 320 && <button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? '收起正文' : '展开正文'}</button>}
    {fields.length > 0 && <dl className="record-inline">{fields.map(([name, value]) => <div key={name}><dt>{fieldName(name)}</dt><dd>{fieldValue(value)}</dd></div>)}</dl>}
    {link && <a className="record-link" href={link} target="_blank" rel="noreferrer">打开原文 ↗</a>}
    <details className="raw-fields"><summary>核对原始字段</summary><dl className="record-fields">{Object.entries(payload).map(([name, value]) => <div key={name}><dt>{fieldName(name)}</dt><dd>{fieldValue(value)}</dd></div>)}</dl></details>
  </article>
}

export default function SourceCatalog() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [files, setFiles] = useState<Page<SourceFile> | null>(null)
  const [records, setRecords] = useState<Page<SourceRecord> | null>(null)
  const [tags, setTags] = useState<TagItem[]>([])
  const [selectedTag, setSelectedTag] = useState('')
  const [kind, setKind] = useState('')
  const [selectedFile, setSelectedFile] = useState<SourceFile | null>(null)
  const [fileInput, setFileInput] = useState('')
  const [fileQuery, setFileQuery] = useState('')
  const [recordInput, setRecordInput] = useState('')
  const [recordQuery, setRecordQuery] = useState('')
  const [dateInput, setDateInput] = useState('')
  const [dateQuery, setDateQuery] = useState('')
  const [fileOffset, setFileOffset] = useState(0)
  const [recordOffset, setRecordOffset] = useState(0)
  const [rawOpen, setRawOpen] = useState(false)
  const [error, setError] = useState('')
  const limit = 20

  useEffect(() => {
    const controller = new AbortController()
    api<Summary>('/api/data/summary', controller.signal).then(setSummary).catch(reason => { if (!isAbort(reason)) setError(reason.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setOverview(null)
    const params = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    api<Overview>(`/api/data/overview${params}`, controller.signal).then(setOverview).catch(reason => { if (!isAbort(reason)) setError(reason.message) })
    return () => controller.abort()
  }, [kind])

  useEffect(() => {
    const controller = new AbortController()
    setTags([])
    const params = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    api<TagItem[]>(`/api/data/tags${params}`, controller.signal).then(setTags).catch(reason => { if (!isAbort(reason)) setError(reason.message) })
    return () => controller.abort()
  }, [kind])

  useEffect(() => {
    if (!rawOpen) return
    const controller = new AbortController()
    const params = new URLSearchParams({ offset: String(fileOffset), limit: String(limit) })
    if (kind) params.set('kind', kind)
    if (fileQuery) params.set('query', fileQuery)
    api<Page<SourceFile>>(`/api/data/files?${params}`, controller.signal).then(setFiles).catch(reason => { if (!isAbort(reason)) setError(reason.message) })
    return () => controller.abort()
  }, [kind, fileQuery, fileOffset, rawOpen])

  useEffect(() => {
    const controller = new AbortController()
    setRecords(null)
    const params = new URLSearchParams({ offset: String(recordOffset), limit: String(limit) })
    if (recordQuery) params.set('query', recordQuery)
    if (dateQuery) params.set('date', dateQuery)
    if (selectedTag) params.set('tag', selectedTag)
    const endpoint = selectedFile ? `/api/data/files/${selectedFile.id}/records` : '/api/data/records'
    if (!selectedFile && kind) params.set('kind', kind)
    api<Page<SourceRecord>>(`${endpoint}?${params}`, controller.signal).then(setRecords).catch(reason => { if (!isAbort(reason)) setError(reason.message) })
    return () => controller.abort()
  }, [kind, selectedFile, recordQuery, dateQuery, selectedTag, recordOffset])

  const trendOption = useMemo(() => ({
    grid: { left: 60, right: 22, top: 24, bottom: 42 },
    tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'category' as const, data: overview?.trend.map(point => point.period) ?? [], axisLabel: { color: '#78909f', hideOverlap: true }, axisLine: { lineStyle: { color: '#304353' } } },
    yAxis: { type: 'value' as const, splitLine: { lineStyle: { color: '#1d303d' } }, axisLabel: { color: '#78909f' } },
    series: [{ type: 'line' as const, data: overview?.trend.map(point => point.count) ?? [], showSymbol: false, lineStyle: { color: '#47d7ac', width: 2 }, areaStyle: { color: 'rgba(71,215,172,.08)' } }],
  }), [overview])

  const selectKind = (next: string) => {
    setKind(next); setSelectedFile(null); setSelectedTag(''); setFileOffset(0); setRecordOffset(0)
    setRecordInput(''); setRecordQuery(''); setDateInput(''); setDateQuery(''); setFileQuery(''); setFileInput('')
  }
  const selectTag = (tag: string) => { setSelectedTag(current => current === tag ? '' : tag); setRecordOffset(0) }
  const searchRecords = (event: FormEvent) => { event.preventDefault(); setRecordOffset(0); setRecordQuery(recordInput); setDateQuery(dateInput) }
  const searchFiles = (event: FormEvent) => { event.preventDefault(); setFileOffset(0); setFileQuery(fileInput) }
  const dateRange = overview?.start_date ? `${overview.start_date} 至 ${overview.end_date}` : '暂无有日期的记录'
  const activeName = selectedFile ? selectedFile.path : kindNames[kind] ?? '全部数据'

  return <div className="source-catalog">
    {error && <div className="error">{error}<button onClick={() => setError('')}>关闭</button></div>}
    <div className="metrics">
      <div className="metric"><span>数据包文件</span><strong>{summary?.total_files.toLocaleString() ?? '—'}</strong><small>全部原始输入文件</small></div>
      <div className="metric"><span>已入库文件</span><strong>{summary?.imported_files.toLocaleString() ?? '—'}</strong><small>本地 SQLite 持久化</small></div>
      <div className="metric"><span>逻辑记录</span><strong>{summary?.total_records.toLocaleString() ?? '—'}</strong><small>文件中的数据行，不是物理行数</small></div>
      <div className="metric"><span>导入异常</span><strong>{summary?.errors ?? '—'}</strong><small>文件级导入错误</small></div>
    </div>
    <p className="catalog-note">文件是存储单位，记录是文件中的数据行。页面只加载当前概览和当前页，不会把整库发送到浏览器。</p>
    <div className="source-groups"><button className={!kind ? 'active' : ''} onClick={() => selectKind('')}><span>全部类型</span><b>{summary?.total_files.toLocaleString() ?? '—'} 个文件</b><small>{summary?.total_records.toLocaleString() ?? '—'} 条记录</small></button>{summary?.groups.map(group => <button key={group.kind} className={kind === group.kind ? 'active' : ''} onClick={() => selectKind(group.kind)}><span>{kindNames[group.kind] ?? group.kind}</span><b>{group.files.toLocaleString()} 个文件</b><small>{group.records.toLocaleString()} 条记录</small></button>)}</div>

    <section className="dataset-heading"><div><span>DATASET OVERVIEW</span><h2>{kindNames[kind] ?? '全部数据'}</h2><p>{kindDescriptions[kind] ?? '统一查看八类数据的覆盖范围与内容。记录量用于核对数据接入，不代表市场涨跌或风险水平。'}</p></div><b>按需查询</b></section>
    <div className="metrics dataset-metrics">
      <div className="metric"><span>当前记录</span><strong>{overview?.records.toLocaleString() ?? '—'}</strong><small>当前筛选类型</small></div>
      <div className="metric"><span>来源文件</span><strong>{overview?.files.toLocaleString() ?? '—'}</strong><small>独立原始文件</small></div>
      <div className="metric"><span>时间覆盖</span><strong className="date-range">{dateRange}</strong><small>按数据自身事件日期</small></div>
      <div className="metric"><span>无日期记录</span><strong>{overview?.undated_records.toLocaleString() ?? '—'}</strong><small>不参与日期趋势统计</small></div>
    </div>
    <section className="panel">
      <div className="panel-head"><div><h2>数据记录量趋势</h2><p>{granularityNames[overview?.granularity ?? 'month']}聚合 · 仅表示入库记录数量，不是金融指标</p></div></div>
      {overview && overview.trend.length > 0 ? <Chart option={trendOption} className="dataset-chart" /> : <div className="empty">{overview ? '当前类型暂无日期趋势' : '正在读取预聚合概览…'}</div>}
      {overview && <details className="field-catalog"><summary>查看字段目录（{overview.fields.length}）</summary><div>{overview.fields.map(field => <span key={field.name}><b>{fieldName(field.name)}</b><small>{field.non_null_count.toLocaleString()} 条非空</small></span>)}</div></details>}
    </section>

    {tags.length > 0 && <section className="panel tag-panel"><div className="panel-head"><div><h2>标签筛选</h2><p>标签来自确定性关键词与已有字段，仅用于检索，不代表情绪或投资判断</p></div>{selectedTag && <button className="clear-tag" onClick={() => { setSelectedTag(''); setRecordOffset(0) }}>清除标签</button>}</div><div className="tag-filters">{tags.map(item => <button key={item.tag} className={selectedTag === item.tag ? 'active' : ''} aria-pressed={selectedTag === item.tag} onClick={() => selectTag(item.tag)}><b>{item.tag}</b><span>{item.records.toLocaleString()} 条</span></button>)}</div></section>}

    <section className="panel">
      <div className="panel-head"><div><h2>最新内容</h2><p>{activeName} · 共 {records?.total.toLocaleString() ?? '—'} 条匹配记录，每页 20 条</p></div><form className="record-search" onSubmit={searchRecords}><input value={recordInput} onChange={event => setRecordInput(event.target.value)} placeholder="搜索标题" /><input type="date" value={dateInput} onChange={event => setDateInput(event.target.value)} aria-label="按日期筛选" /><button type="submit">筛选</button></form></div>
      {selectedFile && <div className="active-filter">正在只看文件：{selectedFile.path}<button onClick={() => { setSelectedFile(null); setRecordOffset(0) }}>清除文件筛选</button></div>}
      {selectedTag && <div className="active-filter">当前标签：{selectedTag}<button onClick={() => { setSelectedTag(''); setRecordOffset(0) }}>清除标签筛选</button></div>}
      {!records ? <div className="empty">正在读取当前页…</div> : records.items.length === 0 ? <div className="empty">当前筛选条件下暂无记录</div> : <div className="content-records">{records.items.map(record => <RecordCard key={`${record.source_id}-${record.record_index}`} record={record} />)}</div>}
      {records && <div className="pagination"><span>第 {Math.floor(recordOffset / limit) + 1} / {Math.max(1, Math.ceil(records.total / limit))} 页</span><div><button aria-label="上一页记录" disabled={recordOffset === 0} onClick={() => setRecordOffset(Math.max(0, recordOffset - limit))}>上一页</button><button aria-label="下一页记录" disabled={recordOffset + limit >= records.total} onClick={() => setRecordOffset(recordOffset + limit)}>下一页</button></div></div>}
    </section>

    <details className="panel raw-files" onToggle={event => setRawOpen(event.currentTarget.open)}><summary>来源文件与入库核对</summary>
      <div className="panel-head"><div><h2>原始文件目录</h2><p>仅在展开此区域后加载，每页 20 个文件</p></div><form className="catalog-search" onSubmit={searchFiles}><input value={fileInput} onChange={event => setFileInput(event.target.value)} placeholder="搜索文件名或路径" /><button type="submit">搜索</button></form></div>
      <div className="table-wrap"><table><thead><tr><th>类型</th><th>来源文件</th><th>状态</th><th>记录数（条）</th><th>Sheet 数</th><th>操作</th></tr></thead><tbody>{files?.items.map(file => <tr key={file.id}><td>{kindNames[file.kind] ?? file.kind}</td><td className="source-path" title={file.path}>{file.path}</td><td><span className={`import-status ${file.status}`}>{file.status === 'imported' ? '已入库' : file.status}</span></td><td>{file.record_count.toLocaleString()}</td><td>{file.sheets.length || '—'}</td><td><button className="text-button" onClick={() => { setSelectedFile(file); setRecordOffset(0); setRecordQuery(''); setRecordInput(''); setDateQuery(''); setDateInput('') }}>只看此文件</button></td></tr>)}</tbody></table></div>
      {rawOpen && !files && <div className="empty">正在读取文件目录…</div>}
      {files && <div className="pagination"><span>第 {Math.floor(fileOffset / limit) + 1} / {Math.max(1, Math.ceil(files.total / limit))} 页</span><div><button disabled={fileOffset === 0} onClick={() => setFileOffset(Math.max(0, fileOffset - limit))}>上一页</button><button disabled={fileOffset + limit >= files.total} onClick={() => setFileOffset(fileOffset + limit)}>下一页</button></div></div>}
    </details>
  </div>
}
