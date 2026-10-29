import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReplayCenter from './ReplayCenter'
import type { ReplaySession } from './types'

const session: ReplaySession = { id: 'replay-1', mode: 'local', start_date: '2024-03-04', end_date: '2024-03-06', status: 'running', speed: 1, processed_days: 0, total_days: 3, current_date: null, progress: 0, error: null, event_stats: { produced_events: 3, consumed_events: 0, duplicate_events: 0, retry_count: 0, commit_count: 0 }, latest_result: null }
const result = {
  event_time: '2024-03-06', replay_time: '2024-03-06T10:00:00Z', input_start: '2024-01-01', input_end: '2024-03-06', input_records: 2, observed_assets: ['A', 'B'],
  features: { market_return: 0.01, volatility: 0.2, momentum: 0.05, correlation: 0.3, trend: 0.02, sample_count: 2 },
  state: { date: '2024-03-06', label: '趋势上涨 · C0', confidence: 0.82, model_version: 'walk-forward-20240305', trained_through: '2024-03-05', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 2 }, contributions: [] },
  alerts: [], model_version: 'walk-forward-20240305',
}

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) { MockWebSocket.instances.push(this) }
  close() { this.onclose?.() }
  emit(message: unknown) { this.onmessage?.({ data: JSON.stringify(message) }) }
}

describe('ReplayCenter', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('fetch', vi.fn((path: string, init?: RequestInit) => {
      let body: unknown = null
      if (path === '/api/replay/calendar') body = { min_date: '2024-01-01', max_date: '2024-03-06', suggested_start: '2024-03-04', suggested_end: '2024-03-06' }
      if (path === '/api/kafka/status') body = { enabled: true, bootstrap_servers: '127.0.0.1:9092', topic: 'test.replay.days', topic_partitions: 1, connection: 'on-demand' }
      if (path === '/api/replay/sessions' && init?.method === 'POST') body = { ...session, status: 'pending', mode: JSON.parse(String(init.body)).mode }
      if (path.endsWith('/start') || path.endsWith('/resume')) body = session
      if (path.endsWith('/pause')) body = { ...session, status: 'paused', processed_days: 1, current_date: '2024-03-04', progress: 1 / 3 }
      if (path.endsWith('/speed')) body = { ...session, speed: 2 }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

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

    const completed = { ...session, status: 'completed', processed_days: 3, current_date: '2024-03-06', progress: 1, latest_result: result }
    act(() => socket.emit({ type: 'replay_day', session: completed, result }))
    expect(screen.getByText('趋势上涨 · C0')).toBeInTheDocument()
    expect(screen.getByText('2 条 · 2 个资产')).toBeInTheDocument()
    expect(screen.getByText('2024-01-01 至 2024-03-06')).toBeInTheDocument()
    expect(screen.getByText('walk-forward-20240305')).toBeInTheDocument()
    expect(screen.getByText('3 / 3 个交易日')).toBeInTheDocument()
    expect(screen.getByText('当前事件日没有新增预警')).toBeInTheDocument()
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
})
