import { FormEvent, useCallback, useEffect, useState } from 'react'
import { api } from './api'

type Summary = { total_files: number; imported_files: number; total_records: number; errors: number; groups: { kind: string; files: number; records: number }[] }
type SourceFile = { id: string; kind: string; path: string; status: string; record_count: number; error_count: number; sheets: string[]; error?: string; size: number }
type SourceRecord = { record_index: number; event_date?: string; title: string; payload: Record<string, unknown> }
type Page<T> = { total: number; offset: number; limit: number; items: T[] }

const kindNames: Record<string, string> = { asset: '资产行情', calendar: '宏观日历', commodity: '商品成交', indicator: '脱敏指标', news: '新闻', publication: '公众号', research: '研究摘要', social: '社交媒体' }

export default function SourceCatalog() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [files, setFiles] = useState<Page<SourceFile> | null>(null)
  const [records, setRecords] = useState<Page<SourceRecord> | null>(null)
  const [selected, setSelected] = useState<SourceFile | null>(null)
  const [kind, setKind] = useState('')
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [recordQuery, setRecordQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')
  const limit = 20

  useEffect(() => { api<Summary>('/api/data/summary').then(setSummary).catch(reason => setError(reason.message)) }, [])
  useEffect(() => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (kind) params.set('kind', kind)
    if (query) params.set('query', query)
    api<Page<SourceFile>>(`/api/data/files?${params}`).then(setFiles).catch(reason => setError(reason.message))
  }, [kind, query, offset])

  const search = (event: FormEvent) => { event.preventDefault(); setOffset(0); setQuery(input) }
  const openRecords = useCallback(async (file: SourceFile, titleQuery = '') => {
    setSelected(file); setExpanded(false); setRecords(null)
    const params = new URLSearchParams({ limit: '5', offset: '0' })
    if (titleQuery) params.set('query', titleQuery)
    try { setRecords(await api<Page<SourceRecord>>(`/api/data/files/${file.id}/records?${params}`)) } catch (reason) { setError(reason instanceof Error ? reason.message : '记录读取失败') }
  }, [])

  return <div className="source-catalog">
    {error && <div className="error">{error}<button onClick={() => setError('')}>关闭</button></div>}
    <div className="metrics">
      <div className="metric"><span>数据包文件</span><strong>{summary?.total_files.toLocaleString() ?? '—'}</strong><small>全部原始输入文件</small></div>
      <div className="metric"><span>已入库文件</span><strong>{summary?.imported_files.toLocaleString() ?? '—'}</strong><small>本地 SQLite 持久化</small></div>
      <div className="metric"><span>逻辑记录</span><strong>{summary?.total_records.toLocaleString() ?? '—'}</strong><small>不是物理行数</small></div>
      <div className="metric"><span>导入异常</span><strong>{summary?.errors ?? '—'}</strong><small>文件级导入错误</small></div>
    </div>
    <div className="source-groups"><button className={!kind ? 'active' : ''} onClick={() => { setKind(''); setOffset(0) }}>全部类型</button>{summary?.groups.map(group => <button key={group.kind} className={kind === group.kind ? 'active' : ''} onClick={() => { setKind(group.kind); setOffset(0) }}><span>{kindNames[group.kind] ?? group.kind}</span><b>{group.files}</b><small>{group.records.toLocaleString()} 条</small></button>)}</div>
    <section className="panel">
      <div className="panel-head"><div><h2>原始文件目录</h2><p>共 {files?.total.toLocaleString() ?? '—'} 个匹配文件，按来源逐文件核对</p></div><form className="catalog-search" onSubmit={search}><input value={input} onChange={event => setInput(event.target.value)} placeholder="搜索文件名或路径" /><button type="submit">搜索</button></form></div>
      <div className="table-wrap"><table><thead><tr><th>类型</th><th>来源文件</th><th>状态</th><th>记录数</th><th>Sheet</th><th>操作</th></tr></thead><tbody>{files?.items.map(file => <tr key={file.id}><td>{kindNames[file.kind] ?? file.kind}</td><td className="source-path" title={file.path}>{file.path}</td><td><span className={`import-status ${file.status}`}>{file.status === 'imported' ? '已入库' : file.status}</span></td><td>{file.record_count.toLocaleString()}</td><td>{file.sheets.length || '—'}</td><td><button className="text-button" onClick={() => { setRecordQuery(''); void openRecords(file) }}>查看记录</button></td></tr>)}</tbody></table></div>
      {files && <div className="pagination"><span>第 {Math.floor(offset / limit) + 1} / {Math.max(1, Math.ceil(files.total / limit))} 页</span><div><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</button><button disabled={offset + limit >= files.total} onClick={() => setOffset(offset + limit)}>下一页</button></div></div>}
    </section>
    {selected && <section className={`panel record-panel ${expanded ? 'expanded' : ''}`}><div className="panel-head"><div><h2>原始记录预览</h2><p>{selected.path} · {records?.total.toLocaleString() ?? '—'} 条记录</p></div><div className="record-actions"><input value={recordQuery} onChange={event => setRecordQuery(event.target.value)} placeholder="按标题筛选" /><button onClick={() => void openRecords(selected, recordQuery)}>筛选</button><button onClick={() => setSelected(null)}>关闭</button></div></div>
      {!records ? <div className="empty">正在读取原始记录…</div> : <div className="record-list">{records.items.map(record => <article key={record.record_index}><header><b>#{record.record_index + 1} {record.title}</b><time>{record.event_date ?? '无日期'}</time></header><pre>{JSON.stringify(record.payload, null, 2)}</pre></article>)}</div>}
      {records && records.items.length > 0 && <button className="expand-button" onClick={() => setExpanded(!expanded)}>{expanded ? '收起长文本' : '展开更多内容'}</button>}
    </section>}
  </div>
}
