import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RegimeStability from './RegimeStability'
import type { StabilityReport, StabilityRun } from './types'

function run(id: string, reference = false): StabilityRun {
  const period = {
    state_days: 100, first_state: '2022-01-03', last_state: '2024-12-31', switch_count: 8,
    switches_per_100_state_days: 8, refit_boundary_count: 4, refit_boundary_switch_count: 2,
    refit_boundary_switch_share: .25, refit_boundary_switch_rate: .5, episode_count: 9,
    median_duration_days: 8, p90_duration_days: 20, max_duration_days: 30, semantic_distribution: { 震荡平衡: 100 },
  }
  return {
    run_id: id, training_window: reference ? 756 : 504, refit_interval: 63, random_seed: reference ? 42 : 2026,
    is_reference: reference,
    periods: {
      all: period, development: period, validation: period,
      holdout: { ...period, state_days: 0, first_state: null, last_state: null, switches_per_100_state_days: null, refit_boundary_switch_share: null, median_duration_days: null, p90_duration_days: null },
    },
  }
}

const report: StabilityReport = {
  schema_version: 1, report_type: 'regime_stability', evaluation_version: 'stability-v1', evaluation_id: 'stability-test',
  protocol_version: 'evaluation-v1-draft', protocol_status: 'draft_pending_team_review', reference_run_id: 'w756-r63-s42',
  generated_at: '2026-11-15T00:00:00+00:00', input_version: 'input-test', feature_version: 'features-test', feature_sha256: 'feature-digest', feature_days: 500,
  loaded_assets: 3, model_parameters: {}, fixed: { minimum_history: 504, cluster_count: 3, regime_identity: 'centroid-alignment-v1' },
  grid: { training_windows: [504, 756], refit_intervals: [63], random_seeds: [42, 2026], run_count: 2 },
  period_definitions: {
    all: { label: '全部历史', start: null, end: null }, development: { label: '开发区间', start: '2017-01-01', end: '2021-12-31' },
    validation: { label: '验证区间', start: '2022-01-01', end: '2024-12-31' }, holdout: { label: '操作留出区间', start: '2025-01-01', end: '2026-04-30' },
  },
  runs: [run('w756-r63-s42', true), run('w504-r63-s2026')],
  comparisons: [{
    period: 'all', left_run_id: 'w756-r63-s42', right_run_id: 'w504-r63-s2026', common_state_days: 100,
    common_start: '2022-01-03', common_end: '2024-12-31', adjusted_rand_index: .8123, semantic_agreement: .9125,
  }, {
    period: 'holdout', left_run_id: 'w756-r63-s42', right_run_id: 'w504-r63-s2026', common_state_days: 0,
    common_start: null, common_end: null, adjusted_rand_index: null, semantic_agreement: null,
  }],
  summary: {
    all: { pair_count: 1, common_state_days: { min: 100, median: 100, max: 100 }, adjusted_rand_index: { min: .8123, median: .8123, max: .8123 }, semantic_agreement: { min: .9125, median: .9125, max: .9125 } },
    development: { pair_count: 0, common_state_days: { min: null, median: null, max: null }, adjusted_rand_index: { min: null, median: null, max: null }, semantic_agreement: { min: null, median: null, max: null } },
    validation: { pair_count: 0, common_state_days: { min: null, median: null, max: null }, adjusted_rand_index: { min: null, median: null, max: null }, semantic_agreement: { min: null, median: null, max: null } },
    holdout: { pair_count: 1, common_state_days: { min: 0, median: 0, max: 0 }, adjusted_rand_index: { min: null, median: null, max: null }, semantic_agreement: { min: null, median: null, max: null } },
  },
  metric_definitions: { adjusted_rand_index: 'ARI 说明', semantic_agreement: '语义说明' }, limitations: ['不能当作预测准确率。'], source_sha256: { 'evaluation.py': 'digest' },
}

describe('RegimeStability', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: async () => report }))) })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('shows the complete grid and changes period without hiding missing results', async () => {
    render(<RegimeStability />)
    expect(await screen.findByRole('heading', { name: '实验概览' })).toBeInTheDocument()
    expect(screen.getAllByRole('row', { name: /w756-r63-s42/ }).length).toBeGreaterThan(0)
    expect(screen.getByText('0.8123')).toBeInTheDocument()
    expect(screen.getAllByText('91.25%')).toHaveLength(2)
    expect(screen.getByText('稳定性不是预测准确率。')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '评估区间' }), { target: { value: 'holdout' } })
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('0.8123')).not.toBeInTheDocument()
  })

  it('surfaces missing reports and retries the read', async () => {
    vi.mocked(fetch).mockImplementationOnce(() => Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '尚未生成模型稳定性报告' }) } as Response))
    render(<RegimeStability />)
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未生成模型稳定性报告')
    fireEvent.click(screen.getByRole('button', { name: '重新读取报告' }))
    expect(await screen.findByRole('heading', { name: '实验概览' })).toBeInTheDocument()
  })
})
