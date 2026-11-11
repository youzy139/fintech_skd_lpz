import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { useAuth } from './Auth'
import { directionTone, percent } from './format'
import { featureNames } from './labels'
import { AlertList, ErrorMessage, Metric, Panel } from './ui'
import type { FlinkStatus, KafkaStatus, ReplayCalendar, ReplayResultsPage, ReplaySession } from './types'

const statusNames = { pending: '待开始', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败' }
const recoveryNames = { none: '无需恢复', paused: '可恢复暂停', rebuilding: '正在重建模型', completed: '恢复完成', failed: '恢复失败' }
const speeds = [0.5, 1, 2, 5, 10]
const pipelineNames: Record<string, string> = { consumer_start_ms: '消费连接启动', producer_start_ms: '生产连接启动', production_ms: '事件生产', control_ms: '控制事件发送', consumer_wait_ms: '消费与窗口等待', commit_ms: '位点提交累计', stale_job_stop_ms: '遗留作业清理', job_start_ms: '作业与首检查点就绪', job_stop_ms: 'Savepoint 停止' }
type ReplayMessage = { type: string; sequence?: number; session: ReplaySession }
function post<T>(path: string, body?: unknown) { return api<T>(path, undefined, { method: 'POST', headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }) }
function featureValue(key: string, value: number | null) { return value === null ? '—' : key === 'correlation' ? value.toFixed(3) : key === 'sample_count' ? value.toFixed(0) : percent(value) }
function milliseconds(value: number | null | undefined) { return value === null || value === undefined ? '—' : `${value.toFixed(value >= 100 ? 0 : 1)} ms` }

export default function ReplayCenter() {
  const { user } = useAuth()
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
  const [initializing, setInitializing] = useState(true)
  const [initializeAttempt, setInitializeAttempt] = useState(0)
  const lastSequence = useRef(0)
  const replayGeneration = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    setInitializing(true); setError('')
    Promise.all([api<ReplayCalendar>('/api/replay/calendar', controller.signal), api<ReplaySession | null>('/api/replay/sessions/current', controller.signal), api<KafkaStatus>('/api/kafka/status', controller.signal), api<FlinkStatus>('/api/flink/status', controller.signal)])
      .then(([range, current, kafka, flink]) => {
        if (controller.signal.aborted) return
        setCalendar(range); setKafkaStatus(kafka); setFlinkStatus(flink)
        setStartDate(current?.start_date ?? range.suggested_start); setEndDate(current?.end_date ?? range.suggested_end)
        setSession(current); setSpeed(current?.speed ?? 1); setMode(current?.mode ?? 'local')
      })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法加载回放日历') })
      .finally(() => { if (!controller.signal.aborted) setInitializing(false) })
    return () => controller.abort()
  }, [initializeAttempt])
  useEffect(() => {
    if (!session) return
    const sessionId = session.id
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    let disposed = false
    let socket: WebSocket | null = null
    let reconnect: ReturnType<typeof setTimeout> | undefined
    lastSequence.current = 0; replayGeneration.current += 1
    const generation = replayGeneration.current
    setConnected(false)
    async function backfill() {
      try {
        let after = lastSequence.current
        while (!disposed && generation === replayGeneration.current) {
          const page = await api<ReplayResultsPage>(`/api/replay/sessions/${sessionId}/results?after=${after}&limit=100`)
          for (const item of page.results) {
            if (item.sequence <= lastSequence.current || generation !== replayGeneration.current) continue
            lastSequence.current = item.sequence
            setSession(current => current?.id === sessionId ? { ...current, latest_sequence: item.sequence, latest_result: item.result, processed_days: Math.max(current.processed_days, item.sequence), current_date: item.event_date, progress: item.sequence / current.total_days } : current)
          }
          if (!page.has_more) break
          after = page.next_sequence
        }
      } catch (reason) { if (!disposed) setError(reason instanceof Error ? reason.message : '回放结果补拉失败') }
    }
    function connect() {
      if (disposed) return
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/replay/${sessionId}`)
      socket.onopen = () => { if (disposed) return; setConnected(true); void backfill() }
      socket.onmessage = event => {
        const message = JSON.parse(event.data) as ReplayMessage
        if (message.type === 'replay_reset') { replayGeneration.current += 1; lastSequence.current = 0 }
        if (message.type === 'replay_day') {
          const sequence = message.sequence ?? message.session.latest_sequence ?? 0
          if (sequence && sequence <= lastSequence.current) return
          if (sequence) lastSequence.current = sequence
        }
        setSession(message.session)
      }
      socket.onclose = event => {
        if (disposed) return
        setConnected(false)
        if (event.code === 4401) { window.dispatchEvent(new Event('marketlens:unauthorized')); return }
        if (event.code === 4403 || event.code === 4404) { setError(event.code === 4403 ? '没有订阅此回放的权限' : '回放会话不存在'); return }
        if (event.code === 4429) { setError(event.reason === 'connection_limit' ? '订阅连接已达并发上限，请关闭其他回放页面后刷新重试' : '订阅请求过于频繁，请稍后刷新重试'); return }
        if (event.code === 1013) { setError('订阅服务暂时不可用，请稍后刷新重试；回放结果仍可在恢复后补拉'); return }
        reconnect = setTimeout(connect, 1000)
      }
      socket.onerror = () => setError('回放推送连接中断，将自动重连并补拉结果')
    }
    connect()
    return () => { disposed = true; replayGeneration.current += 1; if (reconnect) clearTimeout(reconnect); socket?.close() }
  }, [session?.id])
  async function perform(action: () => Promise<ReplaySession>) {
    if (!user.can_control_replay) { setError('当前账号仅可查看回放，请联系管理员授予分析员权限'); return }
    setBusy(true); setError('')
    try { setSession(await action()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '回放操作失败') }
    finally { setBusy(false) }
  }
  async function createAndStart() {
    await perform(async () => {
      const created = await post<ReplaySession>('/api/replay/sessions', { start_date: startDate, end_date: endDate, speed, mode })
      setSession(created)
      return post<ReplaySession>(`/api/replay/sessions/${created.id}/start`)
    })
  }
  async function changeSpeed(value: number) { setSpeed(value); if (session) await perform(() => post<ReplaySession>(`/api/replay/sessions/${session.id}/speed`, { speed: value })) }
  const result = session?.latest_result
  const state = result?.state
  const status = session?.status ?? 'pending'
  return <>
    <div className="replay-intro"><div><span>EVENT-TIME REPLAY</span><h2>让历史按原来的时间顺序重新到达</h2><p>每天只追加当日可见行情，再计算特征、状态和预警；播放速度不改变计算结果。</p></div><b>{mode === 'flink' ? 'Flink 事件时间窗口' : mode === 'kafka' ? 'Kafka 事件传输' : '本地真实计算'} · 非实时行情</b></div>
    {error && <ErrorMessage message={error} onRetry={!calendar ? () => setInitializeAttempt(value => value + 1) : undefined} retryLabel="重新加载回放配置" />}
    {initializing && <p role="status">正在加载回放日历与已有会话…</p>}
    {!user.can_control_replay && <p className="method-note">观察者模式：可查看结果和推送，不能创建、暂停或重新开始回放。</p>}
    <fieldset className="replay-permission" disabled={initializing || !calendar || !user.can_control_replay}><section className="replay-controls" aria-label="历史回放控制"><div className="replay-range"><label>开始日期<input aria-label="回放开始日期" type="date" min={calendar?.min_date} max={calendar?.max_date} value={startDate} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setStartDate(event.target.value)} /></label><span>至</span><label>结束日期<input aria-label="回放结束日期" type="date" min={calendar?.min_date} max={calendar?.max_date} value={endDate} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setEndDate(event.target.value)} /></label></div><label>事件通道<select aria-label="回放通道" value={mode} disabled={busy || status === 'running' || status === 'paused'} onChange={event => setMode(event.target.value as 'local' | 'kafka' | 'flink')}><option value="local">本地直连</option><option value="kafka" disabled={!kafkaStatus?.enabled}>Kafka 事件{kafkaStatus?.enabled ? '' : '（未启用）'}</option><option value="flink" disabled={!kafkaStatus?.enabled || !flinkStatus?.enabled}>Flink 窗口{kafkaStatus?.enabled && flinkStatus?.enabled ? '' : '（未启用）'}</option></select></label><label className="replay-speed">播放速度<select aria-label="回放速度" value={speed} disabled={busy} onChange={event => void changeSpeed(Number(event.target.value))}>{speeds.map(value => <option key={value} value={value}>{value}×</option>)}</select></label><div className="replay-buttons">{status !== 'running' && status !== 'paused' && <button className="replay-primary" disabled={busy || !startDate || !endDate} onClick={() => session?.status === 'pending' ? void perform(() => post(`/api/replay/sessions/${session.id}/start`)) : void createAndStart()}>{session?.status === 'pending' ? '启动此会话' : '开始回放'}</button>}{status === 'running' && <button className="replay-primary" disabled={busy} onClick={() => session && void perform(() => post(`/api/replay/sessions/${session.id}/pause`))}>暂停</button>}{status === 'paused' && <button className="replay-primary" disabled={busy} onClick={() => session && void perform(() => post(`/api/replay/sessions/${session.id}/resume`))}>继续</button>}{session && <button disabled={busy} onClick={() => void perform(() => post(`/api/replay/sessions/${session.id}/restart`))}>从头重开</button>}</div></section></fieldset>
    <section className="replay-progress" aria-live="polite"><div className="replay-progress-head"><div><span className={`replay-status ${status}`}>{statusNames[status]}</span><strong>{session?.current_date ?? '尚未开始'}</strong><small>{connected ? '结果推送已连接' : '等待结果推送连接'}</small></div><b>{session ? `${session.processed_days} / ${session.total_days} 个交易日` : '请选择回放范围'}</b></div><div className="replay-track"><i style={{ width: `${(session?.progress ?? 0) * 100}%` }} /></div><p>事件日期表示数据原本发生的日期；计算名额由服务端统一控制，断线按结果序列补拉。</p></section>
    {session?.error && <ErrorMessage message={session.error} />}
    {session && <div className="replay-event-stats"><span>通道 <b>{session.mode === 'flink' ? 'Flink' : session.mode === 'kafka' ? 'Kafka' : '本地直连'}</b></span><span>已生产 <b>{session.event_stats.produced_events}</b></span><span>已消费 <b>{session.event_stats.consumed_events}</b></span><span>重复跳过 <b>{session.event_stats.duplicate_events}</b></span><span>消费重试 <b>{session.event_stats.retry_count}</b></span><span>位点提交 <b>{session.event_stats.commit_count}</b></span>{session.mode === 'flink' && <span title="只清理由本系统识别、且属于当前会话和运行的旧作业">遗留作业清理 <b>{session.event_stats.stale_jobs_stopped ?? 0}</b></span>}{session.mode === 'flink' && flinkStatus ? <small title={flinkStatus.rest_url}>{flinkStatus.output_topic} · 检查点 {flinkStatus.checkpoint_interval_ms}ms</small> : session.mode === 'kafka' && kafkaStatus ? <small title={kafkaStatus.bootstrap_servers}>{kafkaStatus.topic} · {kafkaStatus.topic_partitions} 个分区</small> : null}</div>}
    {result ? <>
      <div className="metrics"><Metric label="当日市场状态" value={state?.label ?? '历史特征准备中'} detail={state ? `模型置信度 ${percent(state.confidence)}` : '有效历史不足时不强行识别'} featured /><Metric label="年化波动率" value={result.features.volatility === undefined ? '—' : percent(result.features.volatility)} detail="仅使用当前可见历史" /><Metric label="中期动量" value={result.features.momentum === undefined ? '—' : percent(result.features.momentum)} tone={directionTone(result.features.momentum)} detail="当日滚动窗口更新" /><Metric label="当日新增预警" value={result.alerts.length} detail="由确定性规则产生" /></div>
      <div className="grid equal"><Panel title="当日输入与模型证据" subtitle="结果可追溯到事件日期、输入范围和模型版本"><dl className="replay-facts"><div><dt>事件时间</dt><dd>{result.event_time}</dd></div><div><dt>可见输入范围</dt><dd>{result.input_start} 至 {result.input_end}</dd></div><div><dt>当日新增行情</dt><dd>{result.input_records} 条 · {result.observed_assets.length} 个资产</dd></div><div><dt>模型版本</dt><dd>{result.model_version}</dd></div><div><dt>训练数据截至</dt><dd>{state?.trained_through ?? '尚未进入识别阶段'}</dd></div><div><dt>实际处理时间</dt><dd>{new Date(result.replay_time).toLocaleString('zh-CN')}</dd></div></dl></Panel><Panel title="当日特征" subtitle="特征在追加当日输入后重新计算；“—”表示历史窗口不足或无法计算，不代表 0"><div className="replay-features">{Object.entries(result.features).map(([key, value]) => <div key={key}><span>{featureNames[key] ?? key}</span><strong title={value === null ? '当前可见历史不足，暂无法计算' : undefined}>{featureValue(key, value)}</strong></div>)}</div></Panel></div>
      <Panel title="当日新增预警" subtitle="只显示当前事件日新触发的规则" className="table-panel">{result.alerts.length ? <AlertList alerts={result.alerts} compact /> : <div className="empty">当前事件日没有新增预警</div>}</Panel>
    </> : <div className="replay-empty"><h3>等待第一批历史数据</h3><p>开始后会在这里展示逐日计算结果。切换页面不会终止后端会话，返回时可重新接上结果推送。</p></div>}
    {session?.timing && <details className="panel replay-details"><summary><span><strong>运行追踪与阶段耗时</strong><small>真实处理过程 · 不含人为播放间隔</small></span></summary><div className="panel-body"><dl className="replay-facts"><div><dt>会话 ID</dt><dd>{session.id}</dd></div><div><dt>运行 ID</dt><dd>{session.run_id ?? '待分配'}</dd></div><div><dt>结果序列</dt><dd>{session.latest_sequence ?? 0}</dd></div>{session.recovery && session.recovery.state !== 'none' && <><div><dt>恢复状态</dt><dd>{recoveryNames[session.recovery.state]} · 第 {session.recovery.count} 次</dd></div><div><dt>模型重建耗时</dt><dd>{milliseconds(session.recovery.rebuild_ms)}</dd></div></>}{session.mode === 'flink' && <><div><dt>Flink 作业 ID</dt><dd>{session.flink_job_id ?? '待分配'}</dd></div><div><dt>Savepoint</dt><dd>{session.savepoint_path ?? '运行停止后生成'}</dd></div></>}<div><dt>模型初始化</dt><dd>{milliseconds(session.timing.engine_start_ms)}</dd></div><div><dt>通道初始化</dt><dd>{milliseconds(session.timing.pipeline_start_ms)}</dd></div><div><dt>最近一日总耗时</dt><dd>{milliseconds(session.timing.last_day?.total_ms)}</dd></div><div><dt>逐日平均耗时</dt><dd>{milliseconds(session.timing.average_day_ms)}</dd></div></dl>{session.timing.last_day ? <div className="replay-event-stats" aria-label="最近一日阶段耗时"><span>输入等待 <b>{milliseconds(session.timing.last_day.input_ms)}</b></span><span>模型计算 <b>{milliseconds(session.timing.last_day.model_ms)}</b></span><span>结果确认 <b>{milliseconds(session.timing.last_day.ack_ms)}</b></span><span>事件日期 <b>{session.timing.last_day.event_date}</b></span></div> : <div className="empty">尚未产生逐日计时</div>}{Object.keys(session.timing.pipeline).length > 0 && <div className="replay-event-stats" aria-label="通道累计耗时">{Object.entries(session.timing.pipeline).map(([key, value]) => <span key={key}>{pipelineNames[key] ?? key} <b>{milliseconds(value)}</b></span>)}</div>}</div></details>}
  </>
}
