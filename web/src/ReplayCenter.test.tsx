import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReplayCenter from './ReplayCenter'
import type { ReplaySession } from './types'

const session: ReplaySession = {
  id: 'replay-1', run_id: 'run-1', mode: 'local', start_date: '2024-03-04', end_date: '2024-03-06', status: 'running', speed: 1, processed_days: 0, total_days: 3, current_date: null, progress: 0, error: null,
  event_stats: { produced_events: 3, consumed_events: 0, duplicate_events: 0, retry_count: 0, commit_count: 0 },
  timing: { engine_start_ms: 12.3, pipeline_start_ms: 4.2, last_day: { event_date: '2024-03-04', input_ms: 3.1, model_ms: 45.6, ack_ms: 0.8, total_ms: 49.5 }, processed_days: 1, total_day_ms: 49.5, average_day_ms: 49.5, max_day_ms: 49.5, pipeline: {} },
  latest_result: null,
}
const result = {
  event_time: '2024-03-06', replay_time: '2024-03-06T10:00:00Z', input_start: '2024-01-01', input_end: '2024-03-06', input_records: 2, observed_assets: ['A', 'B'],
  features: { market_return: 0.01, volatility: 0.2, momentum: 0.05, correlation: 0.3, trend: 0.02, sample_count: 2 },
  state: { date: '2024-03-06', label: '趋势上涨 · C0', confidence: 0.82, model_version: 'walk-forward-20240305', trained_through: '2024-03-05', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 2 }, contributions: [] },
  alerts: [], model_version: 'walk-forward-20240305',
}
let backfillResults: { sequence: number; event_date: string; result: typeof result }[] = []

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) { MockWebSocket.instances.push(this) }
  close() { this.onclose?.({ code: 1000, reason: '' }) }
  emit(message: unknown) { this.onmessage?.({ data: JSON.stringify(message) }) }
}

describe('ReplayCenter', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    backfillResults = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('fetch', vi.fn((path: string, init?: RequestInit) => {
      let body: unknown = null
      if (path === '/api/replay/calendar') body = { min_date: '2024-01-01', max_date: '2024-03-06', suggested_start: '2024-03-04', suggested_end: '2024-03-06' }
      if (path === '/api/kafka/status') body = { enabled: true, bootstrap_servers: '127.0.0.1:9092', topic: 'test.replay.days', topic_partitions: 1, connection: 'on-demand' }
      if (path === '/api/flink/status') body = { enabled: true, rest_url: 'http://127.0.0.1:8081', output_topic: 'test.features.days', late_topic: 'test.late.days', checkpoint_interval_ms: 2000, connection: 'on-demand' }
      if (path === '/api/replay/sessions' && init?.method === 'POST') body = { ...session, status: 'pending', mode: JSON.parse(String(init.body)).mode }
      if (path.includes('/results?')) body = { session_id: 'replay-1', results: backfillResults, next_sequence: backfillResults.at(-1)?.sequence ?? 0, has_more: false }
      if (path.endsWith('/start') || path.endsWith('/resume')) body = session
      if (path.endsWith('/pause')) body = { ...session, status: 'paused', processed_days: 1, current_date: '2024-03-04', progress: 1 / 3 }
      if (path.endsWith('/speed')) body = { ...session, speed: 2 }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('retains a rejected pending session and retries without creating another', async () => {
    const originalFetch = vi.mocked(fetch).getMockImplementation()!
    let rejected = true
    vi.mocked(fetch).mockImplementation((...args) => {
      if (String(args[0]).endsWith('/start') && rejected) return Promise.resolve({ ok: false, status: 429, json: async () => ({ detail: '回放计算已达并发上限，请暂停其他回放后重试' }) } as Response)
      return originalFetch(...args)
    })
    render(<ReplayCenter />)
    const start = await screen.findByRole('button', { name: '开始回放' })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    expect(await screen.findByRole('alert')).toHaveTextContent('并发上限')
    expect(screen.getByText('待开始')).toBeInTheDocument()
    rejected = false
    fireEvent.click(screen.getByRole('button', { name: '启动此会话' }))
    expect(await screen.findByRole('button', { name: '暂停' })).toBeInTheDocument()
    expect(vi.mocked(fetch).mock.calls.filter(([path]) => path === '/api/replay/sessions')).toHaveLength(1)
  })

  it.each([
    [4429, 'connection_limit', '订阅连接已达并发上限，请关闭其他回放页面后刷新重试'],
    [1013, 'connection_lease_unavailable', '订阅服务暂时不可用，请稍后刷新重试；回放结果仍可在恢复后补拉'],
  ])('explains subscription rejection %s and stops reconnecting', async (code, reason, message) => {
    render(<ReplayCenter />)
    const start = await screen.findByRole('button', { name: '开始回放' })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    const timer = vi.spyOn(globalThis, 'setTimeout')
    act(() => MockWebSocket.instances[0].onclose?.({ code, reason }))
    expect(screen.getByRole('alert')).toHaveTextContent(message)
    expect(timer).not.toHaveBeenCalled()
  })

  it('controls a replay and renders daily calculated results from websocket messages', async () => {
    render(<ReplayCenter />)
    const start = await screen.findByRole('button', { name: '开始回放' })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    const socket = MockWebSocket.instances[0]
    expect(socket.url).toContain('/ws/replay/replay-1')
    act(() => { socket.onopen?.(); socket.emit({ type: 'replay_snapshot', session }) })
    expect(screen.getByText('结果推送已连接')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('combobox', { name: '回放速度' }), { target: { value: '2' } })
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/replay/sessions/replay-1/speed', expect.objectContaining({ method: 'POST' })))
    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    expect(await screen.findByRole('button', { name: '继续' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/replay/sessions/replay-1/resume', expect.objectContaining({ method: 'POST' })))

    const completed = { ...session, status: 'completed', processed_days: 3, current_date: '2024-03-06', progress: 1, latest_sequence: 3, latest_result: result }
    act(() => socket.emit({ type: 'replay_day', sequence: 3, session: completed, result }))
    expect(screen.getByText('趋势上涨 · C0')).toBeInTheDocument()
    expect(screen.getByText('2 条 · 2 个资产')).toBeInTheDocument()
    expect(screen.getByText('2024-01-01 至 2024-03-06')).toBeInTheDocument()
    expect(screen.getByText('walk-forward-20240305')).toBeInTheDocument()
    expect(screen.getByText('3 / 3 个交易日')).toBeInTheDocument()
    expect(screen.getByText('当前事件日没有新增预警')).toBeInTheDocument()
    expect(screen.getByText('运行追踪与阶段耗时')).toBeInTheDocument()
    expect(screen.getByText('run-1')).toBeInTheDocument()
    expect(screen.getByText('模型计算')).toBeInTheDocument()
    expect(screen.getByText('45.6 ms')).toBeInTheDocument()
  })

  it('creates a Kafka-mode replay when the event channel is selected', async () => {
    render(<ReplayCenter />)
    const channel = await screen.findByRole('combobox', { name: '回放通道' })
    await waitFor(() => expect(channel).toBeEnabled())
    fireEvent.change(channel, { target: { value: 'kafka' } })
    expect(screen.getByText('Kafka 事件传输 · 非实时行情')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '开始回放' }))
    await waitFor(() => {
      const creation = vi.mocked(fetch).mock.calls.find(([path]) => path === '/api/replay/sessions')
      expect(creation).toBeDefined()
      expect(JSON.parse(String(creation?.[1]?.body))).toMatchObject({ mode: 'kafka', start_date: '2024-03-04', end_date: '2024-03-06' })
    })
  })

  it('creates a Flink-mode replay when the window channel is selected', async () => {
    render(<ReplayCenter />)
    const channel = await screen.findByRole('combobox', { name: '回放通道' })
    await waitFor(() => expect(channel).toBeEnabled())
    fireEvent.change(channel, { target: { value: 'flink' } })
    expect(screen.getByText('Flink 事件时间窗口 · 非实时行情')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '开始回放' }))
    await waitFor(() => {
      const creation = vi.mocked(fetch).mock.calls.find(([path]) => path === '/api/replay/sessions')
      expect(creation).toBeDefined()
      expect(JSON.parse(String(creation?.[1]?.body))).toMatchObject({ mode: 'flink', start_date: '2024-03-04', end_date: '2024-03-06' })
    })
    act(() => MockWebSocket.instances[0].emit({
      type: 'replay_status',
      session: { ...session, mode: 'flink', flink_job_id: 'job-1', savepoint_path: 'file:///savepoints/savepoint-1', timing: { ...session.timing, pipeline: { job_start_ms: 5000, job_stop_ms: 1200 } } },
    }))
    expect(screen.getByText('Flink 作业 ID')).toBeInTheDocument()
    expect(screen.getByText('job-1')).toBeInTheDocument()
    expect(screen.getByText('file:///savepoints/savepoint-1')).toBeInTheDocument()
    expect(screen.getByText('作业与首检查点就绪')).toBeInTheDocument()
    expect(screen.getByText('Savepoint 停止')).toBeInTheDocument()
  })

  it('backfills missed results and ignores stale sequences', async () => {
    backfillResults = [{ sequence: 3, event_date: result.event_time, result }]
    render(<ReplayCenter />)
    const start = await screen.findByRole('button', { name: '开始回放' })
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    const socket = MockWebSocket.instances[0]
    act(() => socket.onopen?.())
    expect(await screen.findByText('趋势上涨 · C0')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/replay/sessions/replay-1/results?after=0&limit=100', expect.anything())
    expect(screen.getByText('结果序列').nextElementSibling?.textContent).toBe('3')

    const stale = { ...result, state: { ...result.state, label: '旧结果' } }
    act(() => socket.emit({ type: 'replay_day', sequence: 2, session: { ...session, latest_sequence: 2, latest_result: stale }, result: stale }))
    expect(screen.queryByText('旧结果')).not.toBeInTheDocument()
    expect(screen.getByText('趋势上涨 · C0')).toBeInTheDocument()

    act(() => socket.emit({ type: 'replay_reset', session: { ...session, status: 'pending', processed_days: 0, latest_sequence: 0, latest_result: null } }))
    act(() => socket.emit({ type: 'replay_day', sequence: 1, session: { ...session, latest_sequence: 1, latest_result: result }, result }))
    expect(screen.getByText('结果序列').nextElementSibling?.textContent).toBe('1')
    expect(screen.getByText('趋势上涨 · C0')).toBeInTheDocument()
  })
})
