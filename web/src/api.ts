export async function api<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    if (response.status === 401 && !['/api/auth/login', '/api/auth/bootstrap', '/api/auth/status'].includes(path)) window.dispatchEvent(new Event('marketlens:unauthorized'))
    throw new Error(body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}）`))
  }
  return response.json() as Promise<T>
}
