import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import FileGovernance from './FileGovernance'
import type { FileGovernanceReport } from './FileGovernance'

const report = (path = 'social.csv'): FileGovernanceReport => ({
  data_version: 'catalog-version', policy_version: 'source-policy-v1',
  file: { id: 'one', path, status: 'imported', error_count: 0, sheets: [] },
  policy: { name: '社交媒体', time_semantics: '发布时间未核实', restriction: '不得进入模型' },
  records: 3, start_date: '2024-01-01', end_date: '2024-01-01', undated_records: 2, undated_ratio: 2 / 3,
  statistics_status: 'consistent', fields_truncated: false,
  fields: [{ name: 'text', non_null_count: 2, empty_or_absent_count: 1, empty_or_absent_ratio: 1 / 3 }],
  limitations: ['历史统计可能未登记全空字段'],
})
const response = (value: unknown) => ({ ok: true, json: () => Promise.resolve(value) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('reads the selected file and shows field evidence without interpreting raw HTML', async () => {
  const value = report('<img src=x onerror=alert(1)>')
  value.fields[0].name = '<script>unsafe</script>'
  const fetch = vi.fn().mockResolvedValue(response(value))
  const close = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const { container } = render(<FileGovernance sourceId="id with space" onClose={close} />)
  await screen.findByText(value.file.path)
  expect(fetch.mock.calls[0][0]).toBe('/api/data/files/id%20with%20space/governance')
  expect(screen.getByText('2 条 · 66.67%')).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: '33.33%' })).toBeInTheDocument()
  expect(screen.getByText('未评估 / 未评估')).toBeInTheDocument()
  expect(container.querySelector('img,script')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭文件质量证据' }))
  expect(close).toHaveBeenCalledOnce()
})

it('retries a missing or unavailable file independently', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({ detail: '来源文件不存在' }) })
    .mockResolvedValue(response(report()))
  vi.stubGlobal('fetch', fetch)
  render(<FileGovernance sourceId="one" onClose={() => {}} />)
  await screen.findByText('来源文件不存在')
  fireEvent.click(screen.getByRole('button', { name: '重试文件质量证据' }))
  await screen.findByText('social.csv')
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('aborts old file requests and ignores late responses on selection and unmount', async () => {
  let resolveOld!: (value: unknown) => void
  const fetch = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue(response(report('new.csv')))
  vi.stubGlobal('fetch', fetch)
  const { rerender, unmount } = render(<FileGovernance sourceId="old" onClose={() => {}} />)
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  rerender(<FileGovernance sourceId="new" onClose={() => {}} />)
  await screen.findByText('new.csv')
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
  resolveOld(response(report('old.csv')))
  await waitFor(() => expect(screen.queryByText('old.csv')).not.toBeInTheDocument())
  unmount()
  expect(fetch.mock.calls[1][1].signal.aborted).toBe(true)
})

it('shows inconsistent counts and empty denominators without false percentages', async () => {
  const value = report()
  Object.assign(value, { statistics_status: 'inconsistent', undated_records: -1, undated_ratio: null, fields_truncated: true })
  Object.assign(value.fields[0], { empty_or_absent_count: null, empty_or_absent_ratio: null })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(value)))
  render(<FileGovernance sourceId="one" onClose={() => {}} />)
  await screen.findByText('预聚合统计不一致，比例不可计算')
  expect(screen.getAllByRole('cell', { name: '不可计算' })).toHaveLength(2)
  expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
  expect(screen.getByText('字段超过 100 项，仅展示前 100 项。')).toBeInTheDocument()
})

it('includes an entirely empty observed field without treating it as a required-field failure', async () => {
  const value = report()
  value.fields.push({ name: 'optional', non_null_count: 0, empty_or_absent_count: 3, empty_or_absent_ratio: 1 })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(value)))
  render(<FileGovernance sourceId="one" onClose={() => {}} />)
  await screen.findByRole('cell', { name: 'optional' })
  expect(screen.getByText(/本次展示 2 个字段，其中 1 个全空/)).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: '100.00%' })).toBeInTheDocument()
})
