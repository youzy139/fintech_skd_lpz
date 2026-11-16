import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MarketOverview from './MarketOverview'
import type { ResearchWorkspace } from './types'

vi.mock('./Chart', () => ({ default: ({ option }: { option: { series: { data: number[] }[] } }) => <div data-testid="chart" data-count={option.series[0].data.length} /> }))
const latest = { date: '2026-04-30', label: '震荡平衡 · C1', confidence: 0.82, model_version: 'test', trained_through: '2026-04-29', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 30 }, contributions: [] }
const assets = [
  { code: 'SPX.GI', name: '标普500', category: '全球权益', field: 'close', start: '2020-01-01', end: '2026-04-30', rows: 100 },
  { code: 'BOND.YIELD', name: '示例国债', category: '债券', field: 'yield', start: '2020-01-01', end: '2026-04-30', rows: 100 },
]
const points = Array.from({ length: 100 }, (_, index) => ({ date: `2026-01-${String(index % 28 + 1).padStart(2, '0')}`, value: index + 1 }))
const defaultWorkspace: ResearchWorkspace = { workspace_version: 'market-workspace-v1', search: '', category: 'all', watchlist_only: false, watchlist: [], selected_asset: 'SPX.GI', visible_range: 500, revision: 0, updated_at: null }
let storedWorkspace: ResearchWorkspace
let failSave: boolean

const props = { assets, latest, alerts: [], loading: false, onRefresh: vi.fn(), onNavigate: vi.fn() }

describe('MarketOverview asset browser', () => {
  beforeEach(() => {
    storedWorkspace = { ...defaultWorkspace, watchlist: [] }
    failSave = false
    vi.stubGlobal('fetch', vi.fn((path: string, init?: RequestInit) => {
      if (path === '/api/research/workspace') {
        if (init?.method === 'PUT') {
          if (failSave) return Promise.resolve({ ok: false, status: 503, json: async () => ({ detail: 'save offline' }) })
          const draft = JSON.parse(String(init.body)) as Partial<ResearchWorkspace>
          storedWorkspace = { ...storedWorkspace, ...draft, revision: storedWorkspace.revision + 1, updated_at: 1_800_000_000 }
        }
        return Promise.resolve({ ok: true, json: async () => storedWorkspace })
      }
      const code = path.includes('BOND.YIELD') ? 'BOND.YIELD' : 'SPX.GI'
      return Promise.resolve({ ok: true, json: async () => ({ code, name: code, field: code === 'BOND.YIELD' ? 'yield' : 'close', unit: 'source', points }) })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('filters assets, loads the selected series and changes the visible range', async () => {
    render(<MarketOverview {...props} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/assets/SPX.GI/series?limit=500', expect.anything()))
    expect(await screen.findByTestId('chart')).toHaveAttribute('data-count', '100')
    fireEvent.change(screen.getByLabelText('搜索资产'), { target: { value: '国债' } })
    expect(screen.queryByRole('button', { name: /标普500 SPX.GI/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /示例国债 BOND.YIELD/ }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/assets/BOND.YIELD/series?limit=500', expect.anything()))
    fireEvent.click(screen.getByRole('button', { name: '60 日' }))
    expect(await screen.findByTestId('chart')).toHaveAttribute('data-count', '60')
    expect(screen.getByText(/收益率（非价格）/)).toBeInTheDocument()
  })

  it('saves and restores the watchlist, selected asset and visible range', async () => {
    const first = render(<MarketOverview {...props} />)
    await screen.findByTestId('chart')
    fireEvent.click(screen.getByRole('button', { name: '将示例国债加入观察列表' }))
    fireEvent.click(screen.getByRole('button', { name: '只看观察列表 · 1' }))
    fireEvent.click(screen.getByRole('button', { name: '60 日' }))
    await screen.findByTestId('chart')
    fireEvent.click(screen.getByRole('button', { name: '保存工作区' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已保存'))
    const write = vi.mocked(fetch).mock.calls.find(([path, init]) => path === '/api/research/workspace' && (init as RequestInit | undefined)?.method === 'PUT')
    expect(JSON.parse(String(write?.[1]?.body))).toMatchObject({ watchlist: ['BOND.YIELD'], watchlist_only: true, selected_asset: 'BOND.YIELD', visible_range: 60 })
    first.unmount()
    render(<MarketOverview {...props} />)
    await waitFor(() => expect(screen.getByLabelText('搜索资产')).toBeEnabled())
    expect(screen.getByRole('button', { name: '查看全部资产 · 1' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /示例国债 BOND.YIELD/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: /标普500 SPX.GI/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '60 日' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByTestId('chart')).toHaveAttribute('data-count', '60')
  })

  it('keeps unsaved changes visible after a failure and retries explicitly', async () => {
    failSave = true
    render(<MarketOverview {...props} />)
    await screen.findByTestId('chart')
    fireEvent.click(screen.getByRole('button', { name: '将示例国债加入观察列表' }))
    fireEvent.click(screen.getByRole('button', { name: '保存工作区' }))
    expect(await screen.findByText('save offline')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('保存未完成')
    expect(screen.getByRole('button', { name: '保存工作区' })).toBeEnabled()
    failSave = false
    fireEvent.click(screen.getByRole('button', { name: '保存工作区' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已保存'))
    expect(storedWorkspace.watchlist).toEqual(['BOND.YIELD'])
  })
})
