import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SystemStatus } from './SystemStatus'

const report = {
  status: 'degraded', generated_at: '2026-11-09T00:00:00+00:00',
  checks: [{ name: 'redis', status: 'unavailable', latency_ms: 12.3, probe: 'PING', error_type: 'ConnectionError' }, { name: 'kafka', status: 'disabled', latency_ms: null }],
  governance: { mode: 'redis', circuit: { state: 'open', consecutive_failures: 3, short_circuits: 8, recovery_timeout_seconds: 5 } },
}
function mockDependencies(payload: unknown = report) {
  return vi.fn((path: RequestInfo | URL) => {
    const target = String(path)
    if (target.includes('computation-performance')) return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '尚未生成单日计算性能报告，请先运行只读基准脚本' }) })
    if (target.includes('api-performance')) return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '尚未生成独立用户 API 性能报告，请先运行隔离基准脚本' }) })
    return Promise.resolve({ ok: true, json: async () => payload })
  })
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
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(6))
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
  expect(await screen.findByText('尚未生成独立用户 API 性能报告，请先运行隔离基准脚本')).toBeInTheDocument()
  expect(screen.queryByText('通过暂定目标')).not.toBeInTheDocument()
})

it('shows sample counts, measured thresholds and empty groups separately', async () => {
  const summary = (count: number, p95: number | null, target: number) => ({ sample_count: count, latency_ms: { p50: p95, p95, p99: p95, min: p95, max: p95, mean: p95 }, target_p95_ms: target, p95_within_target: p95 === null ? null : p95 < target })
  const performance = {
    report_type: 'model_computation_performance', performance_version: 'model-computation-performance-v1', generated_at: '2026-11-15T00:00:00+00:00', complete: true, result_consistent: true, targets_conclusive: true,
    configuration: { event_start: '2026-01-01', event_end: '2026-04-30', event_days_per_run: 63, runs: 3, loaded_assets: 39, data_profile: 'real-competition-read-only', measurement_boundary: '单日真实计算', temperature_boundary: '同进程新 engine' },
    environment: { git_revision: '1234567890abcdef', platform: 'test', python: '3.12' },
    summary: { features: summary(189, 20, 50), regime_non_refit: summary(186, 1200, 1000), regime_refit: summary(0, null, 1000), regime_all: summary(189, 1100, 1000) },
    baseline_comparison: {
      comparison_version: 'performance-baseline-comparison-v1', baseline_generated_at: '2026-11-14T00:00:00+00:00', current_generated_at: '2026-11-15T00:00:00+00:00', interpretation: '同机同区间先后观测',
      stages: {
        features: { baseline_p95_ms: 40, current_p95_ms: 20, delta_ms: -20, change_percent: -50, sample_count: 189 },
        regime_non_refit: { baseline_p95_ms: 1000, current_p95_ms: 1200, delta_ms: 200, change_percent: 20, sample_count: 186 },
        regime_refit: { baseline_p95_ms: null, current_p95_ms: null, delta_ms: null, change_percent: null, sample_count: 0 },
      },
    },
  }
  vi.stubGlobal('fetch', vi.fn((path: RequestInfo | URL) => {
    const target = String(path)
    if (target.includes('computation-performance')) return Promise.resolve({ ok: true, json: async () => performance })
    if (target.includes('api-performance')) return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '尚未生成独立用户 API 性能报告' }) })
    return Promise.resolve({ ok: true, json: async () => report })
  }))
  render(<SystemStatus />)
  expect(await screen.findAllByText('状态识别 · 重训日')).toHaveLength(2)
  expect(screen.getByText('通过暂定目标')).toBeInTheDocument()
  expect(screen.getByText('未通过暂定目标')).toBeInTheDocument()
  expect(screen.getByText('未测量')).toBeInTheDocument()
  expect(screen.getByText('1234567890ab')).toBeInTheDocument()
  expect(screen.getByText('2026-01-01 ～ 2026-04-30')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '前后同口径对照' })).toBeInTheDocument()
  expect(screen.getByText('减少 20.000 ms（50.00%）')).toBeInTheDocument()
  expect(screen.getByText('增加 200.000 ms（20.00%）')).toBeInTheDocument()
})

it('shows independent API samples, cold rounds and honest baseline changes', async () => {
  const scenarios = { latest_state: '/api/regimes/latest', catalog_summary: '/api/data/summary' }
  const group = (p95: number) => ({
    requests: 505, successful: 505, statuses: { 200: 505 }, p95_within_50ms: false,
    latency_ms: { p50: 60, p95, p99: 500, min: 8, max: 600 }, throughput_requests_per_second: 600,
    scenarios: Object.fromEntries(Object.values(scenarios).map(path => [path, { requests: 101, latency_ms: { p50: 60, p95, p99: 500, min: 8, max: 600 } }])),
    round_metrics: Array.from({ length: 5 }, (_, index) => ({ requests: 101, successful: 101, latency_ms: { p50: 60, p95: index === 0 ? 507.023 : 117.8, p99: 520, min: 8, max: 540 } })),
  })
  const apiReport = {
    report_type: 'independent_user_api_performance', performance_version: 'independent-user-api-performance-v1', generated_at: '2026-11-16T00:00:00+00:00',
    configuration: { users: 101, rounds: 5, warmup_requests: 10, timeout_seconds: 10, scenarios, server_thread_pool_size: 40 },
    identity: { unique_sessions: 101, type: 'independent_synthetic_user_jwt' }, environment: { git_revision: 'abcdef1234567890', platform: 'test', python: '3.12' },
    measurement: { new_connection_per_request: group(347.789), keep_alive_per_user: group(407.769), server_metrics: { routes: [
      { route: '/api/data/summary', sample_size: 204, p95_ms: 33.697, auth_p95_ms: 13.995, governance_p95_ms: 0.016 },
      { route: '/api/data/records', sample_size: 204, p95_ms: 33.368, auth_p95_ms: 14.394, governance_p95_ms: 0.014 },
    ] } },
    catalog_version_performance: {
      performance_version: 'catalog-version-performance-v1', source_files: 1046, samples_per_path: 200,
      legacy: { p50_ms: 1.401, p95_ms: 1.458, mean_ms: 1.411 }, cached: { p50_ms: 0.003, p95_ms: 0.006, mean_ms: 0.004 }, mean_reduction_percent: 99.717,
      limitations: '只测未变化 SQLite 数据版本查询路径，不是端到端性能结论',
    },
    target_evaluation: { independent_users_above_100: true, all_requests_successful: true, api_p95_below_50ms: false, passes_provisional_target: false, note: '同机合成读取' },
    baseline_comparison: {
      comparison_version: 'api-performance-baseline-comparison-v1', baseline_generated_at: '2026-11-15T00:00:00+00:00', baseline_git_revision: '1234567890abcdef', interpretation: '同机同配置先后测量',
      groups: {
        new_connection_per_request: { baseline_p95_ms: 433.145, current_p95_ms: 347.789, delta_ms: -85.356, change_percent: -19.706, sample_count: 505 },
        keep_alive_per_user: { baseline_p95_ms: 398.439, current_p95_ms: 407.769, delta_ms: 9.33, change_percent: 2.342, sample_count: 505 },
      },
    },
  }
  vi.stubGlobal('fetch', vi.fn((path: RequestInfo | URL) => {
    const target = String(path)
    if (target.includes('api-performance')) return Promise.resolve({ ok: true, json: async () => apiReport })
    if (target.includes('computation-performance')) return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '缺失' }) })
    return Promise.resolve({ ok: true, json: async () => report })
  }))
  render(<SystemStatus />)
  expect(await screen.findByText('101 用户 · 1010 请求')).toBeInTheDocument()
  expect(screen.getAllByText('505/505')).toHaveLength(2)
  expect(screen.getAllByText('p95 未通过暂定目标')).toHaveLength(2)
  expect(screen.getByRole('heading', { name: 'API 前后同口径对照' })).toBeInTheDocument()
  expect(screen.getByText('减少 85.356 ms（19.71%）')).toBeInTheDocument()
  expect(screen.getByText('增加 9.330 ms（2.34%）')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '目录数据版本微基准' })).toBeInTheDocument()
  expect(screen.getByText('1,046 个来源文件', { exact: false })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '服务端路由分段（进程内）' })).toBeInTheDocument()
  expect(screen.getByText('33.368 ms')).toBeInTheDocument()
  expect(screen.getByText('均值减少 99.717%', { exact: false })).toBeInTheDocument()
  expect(screen.getByText('第 1 轮 · 冷轮次保留')).toBeInTheDocument()
  expect(screen.getByText('abcdef123456')).toBeInTheDocument()
})
