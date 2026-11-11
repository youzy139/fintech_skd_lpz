import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('API error contract', () => {
  it('preserves server error status, code and request ID', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 503, headers: new Headers({ 'X-Request-ID': 'request-1' }), json: async () => ({ error: { code: 'DEPENDENCY_UNAVAILABLE', message: '依赖暂不可用' } }) })))
    const request = api('/api/system/dependencies')
    await expect(request).rejects.toMatchObject({ status: 503, code: 'DEPENDENCY_UNAVAILABLE', requestId: 'request-1', message: '依赖暂不可用' })
    await request.catch(reason => expect(reason).toBeInstanceOf(ApiError))
  })

  it('notifies authentication expiry and tolerates minimal response test doubles', async () => {
    const listener = vi.fn()
    window.addEventListener('marketlens:unauthorized', listener)
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 401, json: async () => ({ detail: '登录已失效' }) })))
    await expect(api('/api/assets')).rejects.toMatchObject({ status: 401, message: '登录已失效' })
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener('marketlens:unauthorized', listener)
  })
})
