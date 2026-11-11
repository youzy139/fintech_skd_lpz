import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MarketOverview from './MarketOverview'

vi.mock('./Chart', () => ({ default: ({ option }: { option: { series: { data: number[] }[] } }) => <div data-testid="chart" data-count={option.series[0].data.length} /> }))
const latest = { date: '2026-04-30', label: '震荡平衡 · C1', confidence: 0.82, model_version: 'test', trained_through: '2026-04-29', features: { volatility: 0.2, momentum: 0.05, correlation: 0.3, sample_count: 30 }, contributions: [] }
const assets = [
  { code: 'SPX.GI', name: '标普500', category: '全球权益', field: 'close', start: '2020-01-01', end: '2026-04-30', rows: 100 },
  { code: 'BOND.YIELD', name: '示例国债', category: '债券', field: 'yield', start: '2020-01-01', end: '2026-04-30', rows: 100 },
]
const points = Array.from({ length: 100 }, (_, index) => ({ date: `2026-01-${String(index % 28 + 1).padStart(2, '0')}`, value: index + 1 }))

describe('MarketOverview asset browser', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      const code = path.includes('BOND.YIELD') ? 'BOND.YIELD' : 'SPX.GI'
      return Promise.resolve({ ok: true, json: async () => ({ code, name: code, field: code === 'BOND.YIELD' ? 'yield' : 'close', unit: 'source', points }) })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('filters assets, loads the selected series and changes the visible range', async () => {
    render(<MarketOverview assets={assets} latest={latest} alerts={[]} loading={false} onRefresh={vi.fn()} onNavigate={vi.fn()} />)
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
})
