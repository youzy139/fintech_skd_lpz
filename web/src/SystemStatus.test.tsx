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


it('separates local and Redis cache responsibilities using data-service statistics', async () => {
  const cachedReport = { ...report, catalog_cache: { hits: 7, misses: 3, errors: 1, circuit: report.governance.circuit, local: { enabled: true, hits: 12, misses: 4, entries: 8, max_entries: 128, evictions: 2, expirations: 1 }, shared: { enabled: true, hits: 7, misses: 3, errors: 1 } } }
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: async () => cachedReport })))
  render(<SystemStatus />)
  expect(await screen.findByText('目录缓存分工')).toBeInTheDocument()
  expect(screen.getByText('进程内一级缓存')).toBeInTheDocument()
  expect(screen.getByText('Redis 二级缓存')).toBeInTheDocument()
  expect(screen.getByText('8/128 项 · 淘汰 2 · 过期 1')).toBeInTheDocument()
})

it('shows local-only cache without inventing a Redis circuit', async () => {
  const localReport = { ...report, catalog_cache: { hits: 0, misses: 0, errors: 0, circuit: null, local: { enabled: true, hits: 12, misses: 4, entries: 8, max_entries: 128, evictions: 2, expirations: 1 }, shared: { enabled: false } } }
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: async () => localReport })))
  render(<SystemStatus />)
  expect(await screen.findByText('未启用共享缓存')).toBeInTheDocument()
  expect(screen.getByText('当前仅启用进程内目录缓存，未命中回源显式主存储，不返回伪造结果。', { exact: false })).toBeInTheDocument()
  expect(screen.queryByText('目录缓存熔断')).not.toBeInTheDocument()
})


it('shows validated feature-cache hits and authoritative fallback separately', async () => {
  const feature_cache = { enabled: true, date: '2024-05-01', validated_hits: 9, fallbacks: 3, rejected: 1, shared: { errors: 2, ttl_seconds: 60, circuit: report.governance.circuit } }
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...report, feature_cache }) })))
  render(<SystemStatus />)
  expect(await screen.findByText('热特征缓存')).toBeInTheDocument()
  expect(screen.getByText('有效命中')).toBeInTheDocument()
  expect(screen.getByText('无效缓存 1 次')).toBeInTheDocument()
  expect(screen.getByText('TTL 60s')).toBeInTheDocument()
})
