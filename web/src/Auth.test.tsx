import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthBoundary, useAuth } from './Auth'

function Protected() {
  const { user } = useAuth()
  return <p>{user.username} · {user.can_control_replay ? '可控制回放' : '只读回放'}</p>
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('authentication', () => {
  it('recovers an unavailable identity service without reloading the page', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ ok: true, json: async () => ({ enabled: false, setup_required: false }) })
    vi.stubGlobal('fetch', fetcher)
    render(<AuthBoundary><Protected /></AuthBoundary>)
    fireEvent.click(await screen.findByRole('button', { name: '重新连接身份服务' }))
    await screen.findByText('local-dev · 可控制回放')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('requires login, keeps credentials out of storage and clears protected content on logout', async () => {
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve({ ok: path !== '/api/auth/me', status: path === '/api/auth/me' ? 401 : 200, json: async () => path === '/api/auth/status' ? { enabled: true, setup_required: false } : path === '/api/auth/login' ? { username: 'reader', role: 'observer', domains: ['market', 'catalog'], expires_at: null, can_control_replay: false } : {} })))
    render(<AuthBoundary><Protected /></AuthBoundary>)
    await screen.findByRole('heading', { name: '登录市场工作台' })
    expect(screen.queryByText(/只读回放/)).toBeNull()
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'test-password-123' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await screen.findByText('reader · 只读回放')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(screen.queryByRole('button', { name: '账号权限' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    await screen.findByRole('heading', { name: '登录市场工作台' })
    expect(screen.queryByText(/只读回放/)).toBeNull()
  })

  it('shows bootstrap without default credentials and posts the one-time code', async () => {
    const fetcher = vi.fn((path: string) => Promise.resolve({ ok: true, json: async () => path === '/api/auth/status' ? { enabled: true, setup_required: true } : { username: 'owner', role: 'admin', domains: ['market', 'catalog'], expires_at: null, can_control_replay: true } }))
    vi.stubGlobal('fetch', fetcher)
    render(<AuthBoundary><Protected /></AuthBoundary>)
    await screen.findByRole('heading', { name: '创建首位管理员' })
    expect(screen.getByLabelText('用户名')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('初始化凭据'), { target: { value: 'test-only-bootstrap' } })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'owner' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'test-password-123' } })
    fireEvent.click(screen.getByRole('button', { name: '创建并进入' }))
    await screen.findByText('owner · 可控制回放')
    expect(fetcher).toHaveBeenCalledWith('/api/auth/bootstrap', expect.objectContaining({ method: 'POST', body: JSON.stringify({ username: 'owner', password: 'test-password-123', setup_code: 'test-only-bootstrap' }) }))
    expect(screen.getByRole('button', { name: '账号权限' })).toBeInTheDocument()
  })

  it('unmounts protected data when the session is revoked', async () => {
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve({ ok: true, json: async () => path === '/api/auth/status' ? { enabled: true, setup_required: false } : { username: 'reader', role: 'observer', domains: ['market', 'catalog'], expires_at: null, can_control_replay: false } })))
    render(<AuthBoundary><Protected /></AuthBoundary>)
    await screen.findByText('reader · 只读回放')
    window.dispatchEvent(new Event('marketlens:unauthorized'))
    await waitFor(() => expect(screen.queryByText('reader · 只读回放')).toBeNull())
    expect(screen.getByRole('heading', { name: '登录市场工作台' })).toBeInTheDocument()
  })
})
