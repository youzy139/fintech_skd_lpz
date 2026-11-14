import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import Accounts from './Accounts'

vi.mock('./Auth', () => ({ useAuth: () => ({ user: { username: 'admin' } }) }))

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('submits explicit asset and source scopes when creating an account', async () => {
  const fetcher = vi.fn((_: string, init?: RequestInit) => Promise.resolve({
    ok: true,
    status: 200,
    headers: new Headers(),
    json: async () => init?.method === 'POST' ? { ok: true } : [],
  }))
  vi.stubGlobal('fetch', fetcher)
  render(<Accounts />)
  fireEvent.change(await screen.findByLabelText('资产 ID'), { target: { value: 'SPX, TEST' } })
  fireEvent.change(screen.getByLabelText('来源 ID'), { target: { value: 'calendar-1' } })
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'researcher' } })
  fireEvent.change(screen.getByLabelText('初始密码'), { target: { value: 'test-only-password-123' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))

  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/auth/users', expect.objectContaining({ method: 'POST' })))
  const payload = JSON.parse(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body as string)
  expect(payload.assets).toEqual(['SPX', 'TEST'])
  expect(payload.sources).toEqual(['calendar-1'])
})
