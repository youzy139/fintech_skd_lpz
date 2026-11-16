import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { FeatureCachePerformancePanel, type FeatureCachePerformanceReport } from './FeatureCachePerformancePanel'

afterEach(cleanup)

function latency(p95: number, target: number | null = 10) {
  return { sample_count: 200, latency_ms: { p50: p95 / 2, p95, p99: p95 + 1, min: 0.1, max: p95 + 2, mean: p95 / 2 }, target_p95_ms: target, p95_within_target: target === null ? null : p95 < target, result_consistent: true }
}
const checks = {
  real_redis_write_and_hit: true, authoritative_result_consistent: true, cross_service_object_hit: true,
  cache_miss_repopulation: true, ttl_expiry: true, corrupt_envelope_rejected: true,
  refused_endpoint_fallback: true, circuit_opened: true, circuit_recovery: true,
  restricted_account_forbidden: true, forbidden_before_cache_read: true,
}
const report: FeatureCachePerformanceReport = {
  report_type: 'redis_feature_cache_performance', performance_version: 'redis-feature-cache-performance-v1', generated_at: '2026-11-16T00:00:00+00:00', complete: true,
  configuration: {
    data_profile: 'synthetic-e2e', data: '3 synthetic assets, 1000 business days', measurement_path: 'MarketService.latest_features -> FeatureSnapshotCache.read -> RedisJsonCache.get',
    measurement_boundary: '仅生产服务热特征读取', http_boundary: '本机单长连接参考', rounds: 2, samples_per_round: 100, http_samples: 200, miss_samples: 20, redis_host: '127.0.0.1', redis_port: 16379,
  },
  environment: { git_revision: 'abcdef1234567890', platform: 'test', python: '3.12', redis_version: '8.0.5', redis_mode: 'standalone' },
  measurement: {
    validated_hit: { ...latency(1.234), rounds: [{ round_index: 1, ...latency(1.5) }, { round_index: 2, ...latency(1.234) }] },
    cache_miss_repopulation: latency(2.345, null), http_keep_alive: { ...latency(25.678, null), statuses: { 200: 200 } },
  },
  checks,
  target_evaluation: { primary_measurement: 'validated_hit', target_p95_ms: 10, redis_feature_p95_below_10ms: true, passes_provisional_target: true, functional_checks_all_passed: true, note: '只判定生产服务有效命中路径' },
  limitations: ['同机单 Redis 和独立合成数据', '不是多进程、多节点或公网验收'],
}

describe('FeatureCachePerformancePanel', () => {
  it('separates the Redis target from HTTP references and exposes all evidence', () => {
    render(<FeatureCachePerformancePanel report={report} error="" />)
    expect(screen.getAllByText('1.234 ms').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('通过暂定 <10ms 目标', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Redis 8.0.5')).toBeInTheDocument()
    expect(screen.getByText('完整 HTTP 长连接 · 参考')).toBeInTheDocument()
    expect(screen.getAllByText('参考项，不判定')).toHaveLength(2)
    expect(screen.getByText('25.678 ms')).toBeInTheDocument()
    fireEvent.click(screen.getByText('查看逐轮热命中与功能检查'))
    expect(screen.getByText('第 1 轮')).toBeInTheDocument()
    expect(screen.getByText('权限拒绝先于缓存读取')).toBeInTheDocument()
    expect(screen.getAllByText('通过').length).toBeGreaterThanOrEqual(11)
    fireEvent.click(screen.getByText('测量限制'))
    expect(screen.getByText('不是多进程、多节点或公网验收')).toBeInTheDocument()
  })

  it('keeps missing and failed reports free of a pass conclusion', () => {
    const { rerender } = render(<FeatureCachePerformancePanel report={null} error="尚未生成 Redis 热特征性能报告" />)
    expect(screen.getByRole('status')).toHaveTextContent('尚未生成 Redis 热特征性能报告')
    expect(screen.queryByText('通过暂定目标')).not.toBeInTheDocument()
    const failed = { ...report, measurement: { ...report.measurement, validated_hit: { ...report.measurement.validated_hit, ...latency(12.345) } }, target_evaluation: { ...report.target_evaluation, redis_feature_p95_below_10ms: false, passes_provisional_target: false } }
    rerender(<FeatureCachePerformancePanel report={failed} error="" />)
    expect(screen.getAllByText('未通过暂定目标')).toHaveLength(1)
    expect(screen.getByText('未通过暂定 <10ms 目标', { exact: false })).toBeInTheDocument()
  })
})
