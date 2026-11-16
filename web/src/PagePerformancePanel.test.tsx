import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PagePerformancePanel, type PagePerformanceReport } from './PagePerformancePanel'

afterEach(cleanup)

function group(p95: number, target: number | null = 2000) {
  return { attempt_count: 6, successful_count: 6, failed_count: 0, sample_count: 6, latency_ms: { p50: p95 / 2, p95, p99: p95 + 1, min: 10, max: p95 + 2, mean: p95 / 2 }, target_p95_ms: target, p95_within_target: target === null ? null : p95 < target }
}
const report: PagePerformanceReport = {
  report_type: 'browser_page_performance', performance_version: 'browser-page-performance-v1', generated_at: '2026-11-16T00:00:00+00:00', complete: true,
  configuration: {
    data_profile: 'synthetic-e2e', pages: 2, rounds_per_page: 3, slow_4g_rounds_per_page: 1, viewport: { width: 1440, height: 1000 },
    measurement_boundary: '从 goto/reload 到页面可用', cold_definition: '新上下文、空 HTTP 缓存', hot_definition: '预热后同上下文 reload', slow_4g_definition: '150ms RTT、下行 1.6Mbps',
  },
  environment: { platform: 'test', node: '22.0.0', git_revision: 'abcdef1234567890', browser: { name: 'chromium', version: '142.0', channel: 'chrome', headless: true } },
  measurement: { cold_empty_context: group(1200), hot_repeat_reload: group(500), slow_4g_reference: group(3500, null) },
  page_results: {
    home: { label: '终端首页', cold_p95_ms: 900, hot_p95_ms: 400, slow_4g_p95_ms: 2500, cold_samples: '3/3', hot_samples: '3/3', slow_4g_samples: '1/1', passes_provisional_target: true },
    overview: { label: '市场总览', cold_p95_ms: 1200, hot_p95_ms: 500, slow_4g_p95_ms: 3500, cold_samples: '3/3', hot_samples: '3/3', slow_4g_samples: '1/1', passes_provisional_target: true },
  },
  target_evaluation: { target_p95_ms: 2000, primary_profiles: ['cold_empty_context', 'hot_repeat_reload'], all_primary_samples_successful: true, all_pages_below_2s: true, passes_provisional_target: true, note: '只判定桌面本机合成服务' },
  limitations: ['不是公网或生产构建性能', 'Slow 4G 为网络模拟'],
}

describe('PagePerformancePanel', () => {
  it('shows cold, hot and slow-network evidence separately for every page', () => {
    render(<PagePerformancePanel report={report} error="" />)
    expect(screen.getAllByText('1200.000 ms').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('500.000 ms').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('全部通过')).toBeInTheDocument()
    expect(screen.getByText('终端首页')).toBeInTheDocument()
    expect(screen.getByText('市场总览')).toBeInTheDocument()
    expect(screen.getByText('3500.000 ms')).toBeInTheDocument()
    expect(screen.getAllByText('通过暂定目标')).toHaveLength(2)
    expect(screen.getByText('150ms RTT、下行 1.6Mbps', { exact: false })).toBeInTheDocument()
  })

  it('keeps missing and failed reports free of a pass conclusion', () => {
    const { rerender } = render(<PagePerformancePanel report={null} error="尚未生成页面加载性能报告" />)
    expect(screen.getByRole('status')).toHaveTextContent('尚未生成页面加载性能报告')
    expect(screen.queryByText('全部通过')).not.toBeInTheDocument()
    const failed = { ...report, target_evaluation: { ...report.target_evaluation, all_pages_below_2s: false, passes_provisional_target: false }, page_results: { ...report.page_results, overview: { ...report.page_results.overview, cold_p95_ms: 2400, passes_provisional_target: false } } }
    rerender(<PagePerformancePanel report={failed} error="" />)
    expect(screen.getByText('未全部通过')).toBeInTheDocument()
    expect(screen.getByText('未通过暂定目标')).toBeInTheDocument()
  })
})
