import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Audit } from './Audit'

const event = { id: 3, occurred: 1, actor: 'owner', action: 'login', target: 'owner', status: 200, request_id: 'trace-123' }
const archive = { id: 'abc123', first_id: 1, last_id: 2, first_occurred: 1, last_occurred: 2, record_count: 2, sha256: 'abcdef1234567890', size: 100, bucket: 'audit', object_key: 'audit/test.jsonl', created: 3, last_verified: null, verification: 'unverified' }
const overview = { enabled: true, policy: { retention_days: 90, online_min_records: 10000, batch_limit: 5000 }, online_records: 1, archives: [] }

function response(body: unknown, ok = true) { return Promise.resolve({ ok, status: ok ? 200 : 503, json: async () => body }) }
function overviewWithArchives() { return { ...overview, archives: [archive] } }

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('filters and pages audit records without showing sensitive payloads', async () => {
  const fetcher = vi.fn((path: string) => path.includes('/overview') ? response(overview) : response({ items: [event], next_before: path.includes('before=3') ? null : 3 }))
  vi.stubGlobal('fetch', fetcher)
  render(<Audit />)
  await screen.findByText('trace-123')
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('before=3'), expect.anything()))
  await waitFor(() => expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled())
  fireEvent.change(screen.getByLabelText('操作者'), { target: { value: 'owner' } })
  fireEvent.click(screen.getByRole('button', { name: '筛选' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('actor=owner'), expect.anything()))
})

it('shows a server failure and allows refresh', async () => {
  vi.stubGlobal('fetch', vi.fn(() => response({ error: { message: '限流服务暂时不可用' } }, false)))
  render(<Audit />)
  expect(await screen.findByRole('alert')).toHaveTextContent('限流服务暂时不可用')
  expect(screen.getByRole('button', { name: '刷新最新' })).toBeEnabled()
})

it('archives, verifies and reads an audit batch on demand', async () => {
  const fetcher = vi.fn((path: string, init?: RequestInit) => {
    if (path.endsWith('/verify')) return response({ id: 'abc123', verified: true, record_count: 2 })
    if (path.endsWith('/records')) return response({ items: [{ ...event, target: 'archive-target' }] })
    if (path.endsWith('/archive')) return response({ archived: 2, archive })
    if (path.includes('/overview')) return response(init?.method === 'POST' ? overview : overviewWithArchives())
    return response({ items: [event], next_before: null })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<Audit />)
  fireEvent.click(await screen.findByRole('button', { name: '归档到期记录' }))
  expect(await screen.findByRole('status')).toHaveTextContent('已归档 2 条')
  fireEvent.click(screen.getByRole('button', { name: '回读校验' }))
  await screen.findByText(/归档回读校验通过/)
  fireEvent.click(screen.getByRole('button', { name: '查看记录' }))
  expect(await screen.findByText('archive-target')).toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledWith('/api/auth/audit/archives/abc123/verify', { method: 'POST', signal: undefined })
})
