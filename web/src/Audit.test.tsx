import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Audit } from './Audit'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('filters and pages audit records without showing sensitive payloads', async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve({ ok: true, json: async () => ({ items: [{ id: 3, occurred: 1, actor: 'owner', action: 'login', target: 'owner', status: 200, request_id: 'trace-123' }], next_before: path.includes('before=3') ? null : 3 }) }))
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
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 503, json: async () => ({ error: { message: '限流服务暂时不可用' } }) })))
  render(<Audit />)
  expect(await screen.findByRole('alert')).toHaveTextContent('限流服务暂时不可用')
  expect(screen.getByRole('button', { name: '刷新最新' })).toBeEnabled()
})
