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
    if (path === '/api/alerts/HIGH_VOLATILITY/2024-03-01') return Promise.resolve({ ok: true, json: async () => ({ event_time: alert.date, rule: alert.rule, rule_version: 'rules-old', alert, state, previous_state: null, history_days: 60, parameters: settings, evidence_links: [{ type: 'market_state', url: '/api/regimes?start=2024-03-01&end=2024-03-01' }] }) })
    return Promise.resolve({ ok: false, status: 404, json: async () => ({ error: { message: 'not found' } }) })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<AlertCenter alerts={[alert]} onChanged={onChanged} />)
  await screen.findByDisplayValue('rules-old · admin · 当前')
  fireEvent.click(screen.getByRole('button', { name: '查看证据' }))
  expect(await screen.findByText('model-test')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看当日原始状态 API' })).toHaveAttribute('href', '/api/regimes?start=2024-03-01&end=2024-03-01')
  fireEvent.change(screen.getByLabelText('波动率历史分位'), { target: { value: '95' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并启用新版本' }))
  await waitFor(() => expect(onChanged).toHaveBeenCalled())
  const update = fetcher.mock.calls.find(([path, options]) => path === '/api/alert-rules' && (options as RequestInit | undefined)?.method === 'PUT')
  expect(JSON.parse(String(update?.[1]?.body))).toMatchObject({ volatility_quantile: 0.95 })
})
