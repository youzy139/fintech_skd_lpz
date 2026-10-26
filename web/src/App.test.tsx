import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./Chart', () => ({ default: () => <div data-testid="chart" /> }))

const latest = { date: '2026-04-30', label: '震荡平衡 · C1', confidence: 0.82, model_version: 'test', trained_through: '2026-04-29', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 30 }, contributions: [{ feature: 'volatility', value: 0.2, standardized: 1.2 }] }
const responses: Record<string, unknown> = {
  '/api/assets': [{ code: 'SPX.GI', name: '标普500', category: '全球权益', field: 'close', start: '1970-01-02', end: '2026-04-30', rows: 100 }],
  '/api/regimes/latest': latest,
  '/api/regimes?limit=2000': [latest],
  '/api/alerts?limit=100': [],
  '/api/data/quality': { catalog_records: 40, loaded_assets: 39, invalid_rows: 0, duplicate_dates: 0, total_rows: 314318 },
  '/api/assets/SPX.GI/series?limit=500': { points: [] },
}

describe('App', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(responses[path]) }))) })
  afterEach(() => vi.unstubAllGlobals())
  it('opens the dashboard from the landing page and returns home', async () => {
    render(<App />)
    expect(screen.getByText('读懂市场状态，')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('震荡平衡 · C1')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /进入市场工作台/ }))
    expect(screen.getByRole('heading', { name: '市场总览' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /数据中心/ }))
    expect(screen.getByText('314,318')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /网站首页/ }))
    expect(screen.getByText('从一个更清晰的视角，观察市场。')).toBeInTheDocument()
  })
})
