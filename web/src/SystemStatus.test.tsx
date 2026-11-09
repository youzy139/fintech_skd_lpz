import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SystemStatus } from './SystemStatus'

const report = {
  status: 'degraded', generated_at: '2026-11-09T00:00:00+00:00',
  checks: [{ name: 'redis', status: 'unavailable', latency_ms: 12.3, probe: 'PING', error_type: 'ConnectionError' }, { name: 'kafka', status: 'disabled', latency_ms: null }],
  governance: { mode: 'redis', circuit: { state: 'open', consecutive_failures: 3, short_circuits: 8, recovery_timeout_seconds: 5 } },
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('shows real dependency and circuit states and supports a new probe', async () => {
  const fetcher = vi.fn(() => Promise.resolve({ ok: true, json: async () => report }))
  vi.stubGlobal('fetch', fetcher)
  render(<SystemStatus />)
  expect(await screen.findByText('存在不可用依赖', { exact: false })).toBeInTheDocument()
  expect(screen.getByText('熔断中')).toBeInTheDocument()
  expect(screen.getByText('ConnectionError')).toBeInTheDocument()
  expect(screen.getByText('未启用')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新探测' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
})

it('shows monitoring failures without inventing healthy dependencies', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 503, json: async () => ({ error: { message: '监控暂时不可用' } }) })))
  render(<SystemStatus />)
  expect(await screen.findByRole('alert')).toHaveTextContent('监控暂时不可用')
  expect(screen.queryByText('已启用依赖均正常', { exact: false })).not.toBeInTheDocument()
})
