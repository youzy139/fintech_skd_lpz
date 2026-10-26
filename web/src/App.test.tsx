import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(responses[path]) })))
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    Object.defineProperty(window, 'scrollY', { value: 0, writable: true, configurable: true })
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
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
  it('animates scrolling and finishes at exact scrollTop zero', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let nextId = 0
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { frames.set(++nextId, callback); return nextId }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => frames.delete(id)))
    vi.spyOn(performance, 'now').mockReturnValue(0)
    render(<App />)
    document.documentElement.scrollTop = 600
    Object.defineProperty(window, 'scrollY', { value: 600, writable: true })
    fireEvent.scroll(window)
    const button = screen.getByRole('button', { name: '回到顶部' })
    expect(button.className).toContain('visible')
    fireEvent.click(button)
    expect(document.documentElement.style.scrollBehavior).toBe('auto')
    let now = 0
    while (frames.size) {
      const callbacks = [...frames.values()]
      frames.clear()
      callbacks.forEach(callback => callback(now))
      now += 200
    }
    expect(document.documentElement.scrollTop).toBe(0)
    expect(document.body.scrollTop).toBe(0)
    expect(document.documentElement.style.scrollBehavior).toBe('')
  })
})
