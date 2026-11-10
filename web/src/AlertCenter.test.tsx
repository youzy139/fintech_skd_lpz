import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AlertCenter from './AlertCenter'

const settings = { volatility_quantile: 0.9, correlation_quantile: 0.9, minimum_history: 60, regime_change_enabled: true }
const version = { version: 'rules-old', settings, created_at: '2026-01-01', created_by: 'admin', active: true }
const alert = { date: '2024-03-01', rule: 'HIGH_VOLATILITY', level: 'high', title: '市场波动率异常', evidence: '波动率超过阈值', value: 0.8, threshold: 0.1, rule_version: 'rules-old' }
const state = { date: '2024-03-01', label: '高波动', confidence: 0.8, model_version: 'model-test', trained_through: '2024-02-28', features: { volatility: 0.8 }, contributions: [] }

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('shows rule versions, alert evidence and saves a new deterministic version', async () => {
  const onChanged = vi.fn()
  const fetcher = vi.fn((path: string, options?: RequestInit) => {
    if (path === '/api/alert-rules' && options?.method === 'PUT') return Promise.resolve({ ok: true, json: async () => ({ ...version, version: 'rules-new' }) })
    if (path === '/api/alert-rules') return Promise.resolve({ ok: true, json: async () => ({ active: version, versions: [version] }) })
    if (path === '/api/alerts/HIGH_VOLATILITY/2024-03-01') return Promise.resolve({ ok: true, json: async () => ({ event_time: alert.date, rule: alert.rule, rule_version: 'rules-old', alert, state, previous_state: null, history_days: 60, parameters: settings, evidence_links: [{ type: 'market_state', url: '/api/regimes?start=2024-03-01&end=2024-03-01' }], context: { cutoff_date: '2024-02-29', status: 'ok', description: '只读取前一状态日公开背景', sources: [{ kind: 'calendar', status: 'ok', total: 1, items: [{ record_id: 'calendar:1', kind: 'calendar', title: '此前公开的经济事件', source_path: '日历数据.xlsx', source_date: '2024-02-29', source_time: '09:30', source_timestamp: '2024-02-29T09:30', time_basis: '经济日历 OccurDate 与 OccurTime' }] }], excluded: [{ kind: 'news', reason: '时间字段未确认' }] } }) })
    return Promise.resolve({ ok: false, status: 404, json: async () => ({ error: { message: 'not found' } }) })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<AlertCenter alerts={[alert]} onChanged={onChanged} />)
  await screen.findByDisplayValue('rules-old · admin · 当前')
  const trigger = screen.getByRole('button', { name: '查看证据' })
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: /市场波动率异常/ })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('正在加载证据')
  expect(document.body.style.overflow).toBe('hidden')
  expect(await screen.findByText('model-test')).toBeInTheDocument()
  expect(screen.getByText('此前公开的经济事件')).toBeInTheDocument()
  expect(screen.getByText(/2024-02-29 09:30/)).toBeInTheDocument()
  expect(screen.getByText(/截至前一状态日的公开背景/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看当日原始状态 API' })).toHaveAttribute('href', '/api/regimes?start=2024-03-01&end=2024-03-01')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(document.body.style.overflow).toBe('')
  expect(trigger).toHaveFocus()
  fireEvent.change(screen.getByLabelText('波动率历史分位'), { target: { value: '95' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并启用新版本' }))
  await waitFor(() => expect(onChanged).toHaveBeenCalled())
  const update = fetcher.mock.calls.find(([path, options]) => path === '/api/alert-rules' && (options as RequestInit | undefined)?.method === 'PUT')
  expect(JSON.parse(String(update?.[1]?.body))).toMatchObject({ volatility_quantile: 0.95 })
})
