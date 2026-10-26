import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./Chart', () => ({ default: () => <div data-testid="chart" /> }))

const latest = { date: '2026-04-30', label: '震荡平衡 · C1', confidence: 0.82, model_version: 'test', trained_through: '2026-04-29', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 30 }, contributions: [{ feature: 'volatility', value: 0.2, standardized: 1.2 }] }
const socialRecord = { source_id: 'source', source_path: '科技.csv', kind: 'social', record_index: 0, event_date: '2024-01-02', title: '<b>原文</b>', payload: { created_at_twitter: '2024-01-02', text: '<b>原文</b>' } }
const responses: Record<string, unknown> = {
  '/api/home/summary': { latest, alert_count: 0, loaded_assets: 39, total_rows: 314318, state_count: 3340 },
  '/api/assets': [{ code: 'SPX.GI', name: '标普500', category: '全球权益', field: 'close', start: '1970-01-02', end: '2026-04-30', rows: 100 }],
  '/api/regimes/latest': latest,
  '/api/regimes?limit=2000': [latest],
  '/api/alerts?limit=100': [],
  '/api/assets/SPX.GI/series?limit=500': { points: [] },
  '/api/data/summary': { total_files: 1046, imported_files: 1046, total_records: 1556492, errors: 0, groups: [{ kind: 'social', files: 1, records: 42 }] },
  '/api/data/overview': { kind: null, files: 1046, records: 1556492, start_date: '1970-01-02', end_date: '2026-04-30', undated_records: 0, granularity: 'year', trend: [{ period: '2024', count: 2 }], fields: [{ name: 'text', non_null_count: 42 }] },
  '/api/data/overview?kind=social': { kind: 'social', files: 1, records: 42, start_date: '2024-01-01', end_date: '2024-01-02', undated_records: 0, granularity: 'day', trend: [{ period: '2024-01-02', count: 42 }], fields: [{ name: 'text', non_null_count: 42 }] },
  '/api/data/records?offset=0&limit=20': { total: 1556492, offset: 0, limit: 20, items: [socialRecord] },
  '/api/data/records?offset=0&limit=20&kind=social': { total: 42, offset: 0, limit: 20, items: [socialRecord] },
  '/api/data/records?offset=20&limit=20&kind=social': { total: 42, offset: 20, limit: 20, items: [{ ...socialRecord, record_index: 20, text: '第二页正文', payload: { text: '第二页正文' } }] },
  '/api/data/files?offset=0&limit=20&kind=social': { total: 1, offset: 0, limit: 20, items: [{ id: 'source', kind: 'social', path: '科技.csv', status: 'imported', record_count: 42, error_count: 0, sheets: [], size: 100 }] },
  '/api/data/files/source/records?offset=0&limit=20': { total: 42, offset: 0, limit: 20, items: [socialRecord] },
}

async function openDataCenter() {
  render(<App />)
  await waitFor(() => expect(screen.getByText('震荡平衡 · C1')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /进入市场工作台/ }))
  await waitFor(() => expect(screen.getByRole('heading', { name: '市场总览' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /数据中心/ }))
  await waitFor(() => expect(screen.getByRole('heading', { name: '全部数据' })).toBeInTheDocument())
}

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(responses[path]) })))
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    Object.defineProperty(window, 'scrollY', { value: 0, writable: true, configurable: true })
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('loads a small home summary and preserves dashboard navigation', async () => {
    render(<App />)
    expect(screen.getByText('读懂市场状态，')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('震荡平衡 · C1')).toBeInTheDocument())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('/api/home/summary', { signal: undefined })
    fireEvent.click(screen.getByRole('button', { name: /进入市场工作台/ }))
    await waitFor(() => expect(screen.getByRole('heading', { name: '市场总览' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /网站首页/ }))
    expect(screen.getByText('从一个更清晰的视角，观察市场。')).toBeInTheDocument()
  })

  it('loads data pages without repeating market requests and renders safe readable content', async () => {
    await openDataCenter()
    vi.mocked(fetch).mockClear()
    fireEvent.click(screen.getByRole('button', { name: /社交媒体/ }))
    await waitFor(() => expect(screen.getByRole('heading', { name: '社交媒体' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('原文', { selector: 'p' })).toBeInTheDocument())
    const paths = vi.mocked(fetch).mock.calls.map(call => call[0])
    expect(paths).toContain('/api/data/overview?kind=social')
    expect(paths).toContain('/api/data/records?offset=0&limit=20&kind=social')
    expect(paths).not.toContain('/api/regimes?limit=2000')
    expect(paths).not.toContain('/api/assets/SPX.GI/series?limit=500')
    expect(screen.getByText('1 个文件')).toBeInTheDocument()
    expect(screen.getByText('42 条记录')).toBeInTheDocument()
    expect(screen.getByText('帖子正文', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.queryByText('原文', { selector: 'b' })).toBeNull()
  })

  it('paginates records on the server and loads source files only on demand', async () => {
    await openDataCenter()
    fireEvent.click(screen.getByRole('button', { name: /社交媒体/ }))
    await waitFor(() => expect(screen.getByText('原文', { selector: 'p' })).toBeInTheDocument())
    expect(vi.mocked(fetch).mock.calls.map(call => call[0])).not.toContain('/api/data/files?offset=0&limit=20&kind=social')
    fireEvent.click(screen.getByRole('button', { name: '下一页记录' }))
    await waitFor(() => expect(screen.getByText('第二页正文', { selector: 'p' })).toBeInTheDocument())
    expect(fetch).toHaveBeenCalledWith('/api/data/records?offset=20&limit=20&kind=social', expect.anything())
    fireEvent.click(screen.getByText('来源文件与入库核对'))
    await waitFor(() => expect(screen.getByRole('button', { name: '只看此文件' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '只看此文件' }))
    await waitFor(() => expect(screen.getByText(/正在只看文件：科技.csv/)).toBeInTheDocument())
    expect(fetch).toHaveBeenCalledWith('/api/data/files/source/records?offset=0&limit=20', expect.anything())
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
