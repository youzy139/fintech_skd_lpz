export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string, public readonly requestId?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function api<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    if (response.status === 401 && !['/api/auth/login', '/api/auth/bootstrap', '/api/auth/status'].includes(path)) window.dispatchEvent(new Event('marketlens:unauthorized'))
    const message = body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}）`)
    throw new ApiError(message, response.status, body?.error?.code, body?.error?.request_id ?? response.headers?.get('X-Request-ID') ?? undefined)
  }
  return response.json() as Promise<T>
}
