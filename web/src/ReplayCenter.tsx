import { useEffect, useState } from 'react'
import { api } from './api'
import type { FlinkStatus, KafkaStatus, ReplayCalendar, ReplaySession } from './types'

const statusNames = { pending: '待开始', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败' }
const featureNames: Record<string, string> = { market_return: '市场收益', volatility: '年化波动率', momentum: '中期动量', correlation: '资产相关性', trend: '短期趋势', sample_count: '有效资产数' }
const speeds = [0.5, 1, 2, 5, 10]
const pipelineNames: Record<string, string> = { consumer_start_ms: '消费连接启动', producer_start_ms: '生产连接启动', production_ms: '事件生产', control_ms: '控制事件发送', consumer_wait_ms: '消费与窗口等待', commit_ms: '位点提交累计', job_start_ms: '作业与首检查点就绪', job_stop_ms: 'Savepoint 停止' }

type ReplayMessage = { type: string; session: ReplaySession }

function post<T>(path: string, body?: unknown) {
  return api<T>(path, undefined, { method: 'POST', headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
}

function percent(value: number) { return `${(value * 100).toFixed(2)}%` }
function milliseconds(value: number | null | undefined) { return value === null || value === undefined ? '—' : `${value.toFixed(value >= 100 ? 0 : 1)} ms` }

export default function ReplayCenter() {
  const [calendar, setCalendar] = useState<ReplayCalendar | null>(null)
  const [kafkaStatus, setKafkaStatus] = useState<KafkaStatus | null>(null)
  const [flinkStatus, setFlinkStatus] = useState<FlinkStatus | null>(null)
  const [session, setSession] = useState<ReplaySession | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [speed, setSpeed] = useState(1)
  const [mode, setMode] = useState<'local' | 'kafka' | 'flink'>('local')
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api<ReplayCalendar>('/api/replay/calendar'), api<ReplaySession | null>('/api/replay/sessions/current'), api<KafkaStatus>('/api/kafka/status'), api<FlinkStatus>('/api/flink/status')])
      .then(([range, current, kafka, flink]) => {
        setCalendar(range)
        setKafkaStatus(kafka)
        setFlinkStatus(flink)
        setStartDate(current?.start_date ?? range.suggested_start)
        setEndDate(current?.end_date ?? range.suggested_end)
        setSession(current)
        setSpeed(current?.speed ?? 1)
        setMode(current?.mode ?? 'local')
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : '无法加载回放日历'))
  }, [])

  useEffect(() => {
    if (!session) return
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/replay/${session.id}`)
    socket.onopen = () => setConnected(true)
    socket.onmessage = event => {
      const message = JSON.parse(event.data) as ReplayMessage
      setSession(message.session)
    }
    socket.onclose = () => setConnected(false)
    socket.onerror = () => setError('回放推送连接中断，控制接口仍可使用')
    return () => socket.close()
  }, [session?.id])

  async function perform(action: () => Promise<ReplaySession>) {
    setBusy(true)
    setError('')
    try { setSession(await action()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '回放操作失败') }
    finally { setBusy(false) }
  }

  async function createAndStart() {
    await perform(async () => {
      const created = await post<ReplaySession>('/api/replay/sessions', { start_date: startDate, end_date: endDate, speed, mode })
      return post<ReplaySession>(`/api/replay/sessions/${created.id}/start`)
    })
  }

  async function changeSpeed(value: number) {
    setSpeed(value)
    if (session) await perform(() => post<ReplaySession>(`/api/replay/sessions/${session.id}/speed`, { speed: value }))
  }

  const result = session?.latest_result
  const state = result?.state
  const status = session?.status ?? 'pending'

  return <>
    <div className="replay-intro"><div><span>EVENT-TIME REPLAY</span><h2>让历史按原来的时间顺序重新到达</h2><p>每天只把当日行情追加到可见历史，再计算特征、状态和预警。完整历史仍在档案库中，但不会提前进入模型。</p></div><b>{mode === 'flink' ? 'Flink 事件时间窗口' : mode === 'kafka' ? 'Kafka 事件传输' : '本地真实计算'} · 非实时行情</b></div>
    {error && <div className="error" role="alert">{error}</div>}
    <section className="replay-controls" aria-label="历史回放控制">
      <div className="replay-range"><label>开始日期<input aria-label="回放开始日期" type="date" min={calendar?.min_date} max={calendar?.max_date} value={startDate} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setStartDate(event.target.value)} /></label><span>至</span><label>结束日期<input aria-label="回放结束日期" type="date" min={calendar?.min_date} max={calendar?.max_date} value={endDate} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setEndDate(event.target.value)} /></label></div>
      <label>事件通道<select aria-label="回放通道" value={mode} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setMode(event.target.value as 'local' | 'kafka' | 'flink')}><option value="local">本地直连</option><option value="kafka" disabled={!kafkaStatus?.enabled}>Kafka 事件{kafkaStatus?.enabled ? '' : '（未启用）'}</option><option value="flink" disabled={!kafkaStatus?.enabled || !flinkStatus?.enabled}>Flink 窗口{kafkaStatus?.enabled && flinkStatus?.enabled ? '' : '（未启用）'}</option></select></label>
      <label className="replay-speed">播放速度<select aria-label="回放速度" value={speed} disabled={busy} onChange={event => void changeSpeed(Number(event.target.value))}>{speeds.map(value => <option key={value} value={value}>{value}×</option>)}</select></label>
      <div className="replay-buttons">
        {status !== 'running' && status !== 'paused' && <button className="replay-primary" disabled={busy || !startDate || !endDate} onClick={() => void createAndStart()}>开始回放</button>}
        {status === 'running' && <button className="replay-primary" disabled={busy} onClick={() => session && void perform(() => post(`/api/replay/sessions/${session.id}/pause`))}>暂停</button>}
        {status === 'paused' && <button className="replay-primary" disabled={busy} onClick={() => session && void perform(() => post(`/api/replay/sessions/${session.id}/resume`))}>继续</button>}
        {session && <button disabled={busy} onClick={() => void perform(() => post(`/api/replay/sessions/${session.id}/restart`))}>从头重开</button>}
      </div>
    </section>
    <section className="replay-progress" aria-live="polite">
      <div className="replay-progress-head"><div><span className={`replay-status ${status}`}>{statusNames[status]}</span><strong>{session?.current_date ?? '尚未开始'}</strong><small>{connected ? '结果推送已连接' : '等待结果推送连接'}</small></div><b>{session ? `${session.processed_days} / ${session.total_days} 个交易日` : '请选择回放范围'}</b></div>
      <div className="replay-track"><i style={{ width: `${(session?.progress ?? 0) * 100}%` }} /></div>
      <p>事件日期表示数据原本发生的日期；播放速度只改变到达间隔，不改变窗口、训练数据或计算结果。</p>
    </section>
    {session && <div className="replay-event-stats"><span>通道 <b>{session.mode === 'flink' ? 'Flink' : session.mode === 'kafka' ? 'Kafka' : '本地直连'}</b></span><span>已生产 <b>{session.event_stats.produced_events}</b></span><span>已消费 <b>{session.event_stats.consumed_events}</b></span><span>重复跳过 <b>{session.event_stats.duplicate_events}</b></span><span>消费重试 <b>{session.event_stats.retry_count}</b></span><span>位点提交 <b>{session.event_stats.commit_count}</b></span>{session.mode === 'flink' && flinkStatus ? <small title={flinkStatus.rest_url}>{flinkStatus.output_topic} · 检查点 {flinkStatus.checkpoint_interval_ms}ms</small> : session.mode === 'kafka' && kafkaStatus ? <small title={kafkaStatus.bootstrap_servers}>{kafkaStatus.topic} · {kafkaStatus.topic_partitions} 个分区</small> : null}</div>}
    {session?.timing && <section className="panel replay-timing-panel"><div className="panel-head"><div><h2>运行追踪与阶段耗时</h2><p>来自真实处理过程；逐日耗时不包含人为设置的播放间隔</p></div></div><dl className="replay-facts"><div><dt>会话 ID</dt><dd>{session.id}</dd></div><div><dt>运行 ID</dt><dd>{session.run_id ?? '待分配'}</dd></div>{session.mode === 'flink' && <><div><dt>Flink 作业 ID</dt><dd>{session.flink_job_id ?? '待分配'}</dd></div><div><dt>Savepoint</dt><dd>{session.savepoint_path ?? '运行停止后生成'}</dd></div></>}<div><dt>模型初始化</dt><dd>{milliseconds(session.timing.engine_start_ms)}</dd></div><div><dt>通道初始化</dt><dd>{milliseconds(session.timing.pipeline_start_ms)}</dd></div><div><dt>最近一日总耗时</dt><dd>{milliseconds(session.timing.last_day?.total_ms)}</dd></div><div><dt>逐日平均耗时</dt><dd>{milliseconds(session.timing.average_day_ms)}</dd></div></dl>{session.timing.last_day ? <div className="replay-event-stats" aria-label="最近一日阶段耗时"><span>输入等待 <b>{milliseconds(session.timing.last_day.input_ms)}</b></span><span>模型计算 <b>{milliseconds(session.timing.last_day.model_ms)}</b></span><span>结果确认 <b>{milliseconds(session.timing.last_day.ack_ms)}</b></span><span>事件日期 <b>{session.timing.last_day.event_date}</b></span></div> : <div className="empty">尚未产生逐日计时</div>}{Object.keys(session.timing.pipeline).length > 0 && <div className="replay-event-stats" aria-label="通道累计耗时">{Object.entries(session.timing.pipeline).map(([key, value]) => <span key={key}>{pipelineNames[key] ?? key} <b>{milliseconds(value)}</b></span>)}</div>}</section>}
    {result ? <>
      <div className="metrics">
        <div className="metric featured"><span>当日市场状态</span><strong>{state?.label ?? '历史特征准备中'}</strong><small>{state ? `模型置信度 ${percent(state.confidence)}` : '有效历史不足时不强行识别'}</small></div>
        <div className="metric"><span>年化波动率</span><strong>{result.features.volatility === undefined ? '—' : percent(result.features.volatility)}</strong><small>仅使用当前可见历史</small></div>
        <div className="metric"><span>中期动量</span><strong>{result.features.momentum === undefined ? '—' : percent(result.features.momentum)}</strong><small>当日滚动窗口更新</small></div>
        <div className="metric"><span>当日新增预警</span><strong>{result.alerts.length}</strong><small>由确定性规则产生</small></div>
      </div>
      <div className="grid equal">
        <section className="panel"><div className="panel-head"><div><h2>当日输入与模型证据</h2><p>结果可追溯到事件日期、输入范围和模型版本</p></div></div><dl className="replay-facts"><div><dt>事件时间</dt><dd>{result.event_time}</dd></div><div><dt>可见输入范围</dt><dd>{result.input_start} 至 {result.input_end}</dd></div><div><dt>当日新增行情</dt><dd>{result.input_records} 条 · {result.observed_assets.length} 个资产</dd></div><div><dt>模型版本</dt><dd>{result.model_version}</dd></div><div><dt>训练数据截至</dt><dd>{state?.trained_through ?? '尚未进入识别阶段'}</dd></div><div><dt>实际处理时间</dt><dd>{new Date(result.replay_time).toLocaleString('zh-CN')}</dd></div></dl></section>
        <section className="panel"><div className="panel-head"><div><h2>当日特征</h2><p>特征在追加当日输入后重新计算</p></div></div><div className="replay-features">{Object.entries(result.features).map(([key, value]) => <div key={key}><span>{featureNames[key] ?? key}</span><strong>{key === 'correlation' ? value.toFixed(3) : key === 'sample_count' ? value.toFixed(0) : percent(value)}</strong></div>)}</div></section>
      </div>
      <section className="panel"><div className="panel-head"><div><h2>当日新增预警</h2><p>只显示当前事件日新触发的规则</p></div></div>{result.alerts.length ? <div className="alert-list">{result.alerts.map((item, index) => <article className="alert" key={`${item.rule}-${index}`}><span className={`alert-level ${item.level}`}>{item.level === 'high' ? '高' : '中'}</span><div><h3>{item.title}<small>{item.rule}</small></h3><p>{item.evidence}</p></div><time>{item.date}</time></article>)}</div> : <div className="empty">当前事件日没有新增预警</div>}</section>
    </> : <div className="replay-empty"><h3>等待第一批历史数据</h3><p>开始后会在这里展示逐日计算结果。切换页面不会终止后端会话，返回时可重新接上结果推送。</p></div>}
  </>
}
