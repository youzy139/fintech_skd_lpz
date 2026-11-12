import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SourceGovernance from './SourceGovernance'
import type { GovernanceReport } from './SourceGovernance'

const report = (name = '社交媒体'): GovernanceReport => ({
  schema: 'source-governance-v1', policy_version: 'source-policy-v1', data_version: 'catalog-version', scope: 'source-kind',
  limitations: ['按类型统计，不是逐文件审计'],
  items: [{ kind: 'social', name, usage: 'catalog_only', time_semantics: '发布时间未核实', restriction: '不得进入模型',
    files: 1, records: 3, start_date: '2024-01-01', end_date: '2024-01-01', undated_records: 2, undated_ratio: 2 / 3,
    statistics_status: 'consistent', duplicate_records: null, invalid_records: null,
    fields: [{ name: 'text', non_null_count: 2 }], field_inventory_may_be_truncated: false,
    lifecycle: { raw: '原始只读', online: '在线保留', archive: '手动核对', recompute: '隔离重算', delete: '没有删除执行器', automatic_delete: false },
  }],
})
const response = (value: unknown) => ({ ok: true, json: () => Promise.resolve(value) })
function openReport(container: HTMLElement) {
  const details = container.querySelector('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('loads only after opening and keeps unmeasured values distinct from zero', async () => {
  const fetch = vi.fn().mockResolvedValue(response(report()))
  vi.stubGlobal('fetch', fetch)
  const { container } = render(<SourceGovernance kind="social" />)
  expect(fetch).not.toHaveBeenCalled()
  openReport(container)
  await screen.findByRole('heading', { name: '社交媒体' })
  expect(fetch.mock.calls[0][0]).toBe('/api/data/governance?kind=social')
  expect(screen.getByText('未评估 / 未评估')).toBeInTheDocument()
  expect(screen.getByText('2 条 · 66.67%')).toBeInTheDocument()
  expect(screen.getByText('自动删除未启用；保留期限待团队确认')).toBeInTheDocument()
})

it('shows an independent retry and preserves the selected source', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error('报告暂时不可用')).mockResolvedValue(response(report('新闻')))
  vi.stubGlobal('fetch', fetch)
  const { container } = render(<SourceGovernance kind="news" />)
  openReport(container)
  await screen.findByText('报告暂时不可用')
  fireEvent.click(screen.getByRole('button', { name: '重试来源治理报告' }))
  await screen.findByRole('heading', { name: '新闻' })
  expect(fetch.mock.calls.every(([path]) => path === '/api/data/governance?kind=news')).toBe(true)
})

it('aborts the old source report and ignores a late response after selection changes', async () => {
  let resolveOld!: (value: unknown) => void
  const fetch = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue(response(report('新闻')))
  vi.stubGlobal('fetch', fetch)
  const { container, rerender } = render(<SourceGovernance kind="social" />)
  openReport(container)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  rerender(<SourceGovernance kind="news" />)
  await screen.findByRole('heading', { name: '新闻' })
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
  resolveOld(response(report()))
  await waitFor(() => expect(screen.queryByRole('heading', { name: '社交媒体' })).not.toBeInTheDocument())
})

it('shows empty denominators and the field inventory limit without inventing quality scores', async () => {
  const empty = report()
  Object.assign(empty.items[0], { records: 0, undated_records: 0, undated_ratio: null, start_date: null, end_date: null, fields: [], field_inventory_may_be_truncated: true })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(empty)))
  const { container } = render(<SourceGovernance kind="" />)
  openReport(container)
  await screen.findByRole('heading', { name: '社交媒体' })
  expect(screen.getByText('0 条 · 比例不可计算')).toBeInTheDocument()
  expect(screen.getByText(/已达到 100 项展示上限/)).toBeInTheDocument()
})
