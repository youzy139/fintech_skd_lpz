import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SystemStatus } from './SystemStatus'

const report = {
  status: 'degraded', generated_at: '2026-11-09T00:00:00+00:00',
  checks: [{ name: 'redis', status: 'unavailable', latency_ms: 12.3, probe: 'PING', error_type: 'ConnectionError' }, { name: 'kafka', status: 'disabled', latency_ms: null }],
  governance: { mode: 'redis', circuit: { state: 'open', consecutive_failures: 3, short_circuits: 8, recovery_timeout_seconds: 5 } },
}
function mockDependencies(payload: unknown = report) {
  return vi.fn((path: RequestInfo | URL) => Promise.resolve(String(path).includes('computation-performance')
    ? { ok: false, status: 404, json: async () => ({ detail: '尚未生成单日计算性能报告，请先运行只读基准脚本' }) }
    : { ok: true, json: async () => payload }))
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('shows real dependency and circuit states and supports a new probe', async () => {
  const fetcher = mockDependencies()
  vi.stubGlobal('fetch', fetcher)
  render(<SystemStatus />)
  expect(await screen.findByText('存在不可用依赖', { exact: false })).toBeInTheDocument()
  expect(screen.getByText('熔断中')).toBeInTheDocument()
  expect(screen.getByText('ConnectionError')).toBeInTheDocument()
  expect(screen.getByText('未启用')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新探测' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4))
})

it('shows monitoring failures without inventing healthy dependencies', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 503, json: async () => ({ error: { message: '监控暂时不可用' } }) })))
  render(<SystemStatus />)
  expect(await screen.findByRole('alert')).toHaveTextContent('监控暂时不可用')
  expect(screen.queryByText('已启用依赖均正常', { exact: false })).not.toBeInTheDocument()
})

it('separates local and Redis cache responsibilities using data-service statistics', async () => {
  const cachedReport = { ...report, catalog_cache: { hits: 7, misses: 3, errors: 1, circuit: report.governance.circuit, local: { enabled: true, hits: 12, misses: 4, entries: 8, max_entries: 128, evictions: 2, expirations: 1 }, shared: { enabled: true, hits: 7, misses: 3, errors: 1 } } }
  vi.stubGlobal('fetch', mockDependencies(cachedReport))
  render(<SystemStatus />)
  expect(await screen.findByText('目录缓存分工')).toBeInTheDocument()
  expect(screen.getByText('进程内一级缓存')).toBeInTheDocument()
  expect(screen.getByText('Redis 二级缓存')).toBeInTheDocument()
  expect(screen.getByText('8/128 项 · 淘汰 2 · 过期 1')).toBeInTheDocument()
})

it('shows local-only cache without inventing a Redis circuit', async () => {
  const localReport = { ...report, catalog_cache: { hits: 0, misses: 0, errors: 0, circuit: null, local: { enabled: true, hits: 12, misses: 4, entries: 8, max_entries: 128, evictions: 2, expirations: 1 }, shared: { enabled: false } } }
  vi.stubGlobal('fetch', mockDependencies(localReport))
  render(<SystemStatus />)
  expect(await screen.findByText('未启用共享缓存')).toBeInTheDocument()
  expect(screen.getByText('当前仅启用进程内目录缓存，未命中回源显式主存储，不返回伪造结果。', { exact: false })).toBeInTheDocument()
  expect(screen.queryByText('目录缓存熔断')).not.toBeInTheDocument()
})

it('shows validated feature-cache hits and authoritative fallback separately', async () => {
  const feature_cache = { enabled: true, date: '2024-05-01', validated_hits: 9, fallbacks: 3, rejected: 1, shared: { errors: 2, ttl_seconds: 60, circuit: report.governance.circuit } }
  vi.stubGlobal('fetch', mockDependencies({ ...report, feature_cache }))
  render(<SystemStatus />)
  expect(await screen.findByText('热特征缓存')).toBeInTheDocument()
  expect(screen.getByText('有效命中')).toBeInTheDocument()
  expect(screen.getByText('无效缓存 1 次')).toBeInTheDocument()
  expect(screen.getByText('TTL 60s')).toBeInTheDocument()
})

it('shows missing computation reports without a pass conclusion', async () => {
  vi.stubGlobal('fetch', mockDependencies())
  render(<SystemStatus />)
  expect(await screen.findByText('尚未生成单日计算性能报告，请先运行只读基准脚本')).toBeInTheDocument()
  expect(screen.queryByText('通过暂定目标')).not.toBeInTheDocument()
})

it('shows sample counts, measured thresholds and empty groups separately', async () => {
  const summary = (count: number, p95: number | null, target: number) => ({ sample_count: count, latency_ms: { p50: p95, p95, p99: p95, min: p95, max: p95, mean: p95 }, target_p95_ms: target, p95_within_target: p95 === null ? null : p95 < target })
  const performance = {
    report_type: 'model_computation_performance', performance_version: 'model-computation-performance-v1', generated_at: '2026-11-15T00:00:00+00:00', complete: true, result_consistent: true, targets_conclusive: true,
    configuration: { event_start: '2026-01-01', event_end: '2026-04-30', event_days_per_run: 63, runs: 3, loaded_assets: 39, data_profile: 'real-competition-read-only', measurement_boundary: '单日真实计算', temperature_boundary: '同进程新 engine' },
    environment: { git_revision: '1234567890abcdef', platform: 'test', python: '3.12' },
    summary: { features: summary(189, 20, 50), regime_non_refit: summary(186, 1200, 1000), regime_refit: summary(0, null, 1000), regime_all: summary(189, 1100, 1000) },
  }
  vi.stubGlobal('fetch', vi.fn((path: RequestInfo | URL) => Promise.resolve(String(path).includes('computation-performance')
    ? { ok: true, json: async () => performance }
    : { ok: true, json: async () => report })))
  render(<SystemStatus />)
  expect(await screen.findByText('状态识别 · 重训日')).toBeInTheDocument()
  expect(screen.getByText('通过暂定目标')).toBeInTheDocument()
  expect(screen.getByText('未通过暂定目标')).toBeInTheDocument()
  expect(screen.getByText('未测量')).toBeInTheDocument()
  expect(screen.getByText('1234567890ab')).toBeInTheDocument()
  expect(screen.getByText('2026-01-01 ～ 2026-04-30')).toBeInTheDocument()
})
