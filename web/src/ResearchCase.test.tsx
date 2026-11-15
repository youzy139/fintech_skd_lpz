import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchCase from './ResearchCase'
import type { ResearchCase as Case } from './types'

vi.mock('./Auth', () => ({ useAuth: () => ({ user: { domains: ['market', 'catalog'] } }) }))

const item: Case = {
  case_version: 'research-case-v1', case_id: 'case-test', selection_policy: 'latest_regime_change_else_latest_alert', title: '市场状态切换复核 · 2024-02-01', event_time: '2024-02-01', is_financial_event_label: false,
  feature_changes: [
    { feature: 'volatility', current: .3, previous: .15, delta: .15 },
    { feature: 'momentum', current: -.05, previous: null, delta: null },
    { feature: 'sample_count', current: 20, previous: 25, delta: -5 },
  ],
  replay: { mode: 'local', start_date: '2024-01-31', end_date: '2024-02-01', url: '#/replay?start=2024-01-31&end=2024-02-01&mode=local', description: '只带入日期，由用户决定启动。' },
  conclusion: { observation: '震荡平衡 · C0 → 高波动避险 · C1', statistical_evidence: '规则与模型版本可追溯', validation: '通过真实回放复核', coverage_note: '有效收益资产从 25 个变为 20 个（-5）；不能忽略覆盖变化。', limitations: '不是金融事件标注或买卖建议' },
  evidence: {
    event_time: '2024-02-01', rule: 'REGIME_CHANGE', rule_version: 'rules-test',
    alert: { date: '2024-02-01', rule: 'REGIME_CHANGE', level: 'high', title: '市场状态切换', evidence: '状态切换' },
    state: { date: '2024-02-01', label: '高波动避险 · C1', confidence: .8, model_version: 'model-test', trained_through: '2024-01-31', features: {}, contributions: [] },
    previous_state: { date: '2024-01-31', label: '震荡平衡 · C0', confidence: .7, model_version: 'model-old', trained_through: '2024-01-30', features: {}, contributions: [] },
    history_days: 60, parameters: {}, evidence_links: [],
    context: { cutoff_date: '2024-01-31', status: 'ok', description: '只读取此前公开背景', sources: [{ kind: 'calendar', status: 'ok', total: 1, items: [{ record_id: 'calendar:1', kind: 'calendar', title: '<b>背景</b>', source_path: '日历.xlsx', source_date: '2024-01-31', source_time: '09:30', source_timestamp: null, time_basis: '来源时间' }] }], excluded: [{ kind: 'news', reason: '时间字段未确认' }] },
  },
}

describe('ResearchCase', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: async () => item }))) })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('links real evidence to a two-day replay without treating HTML as markup', async () => {
    render(<ResearchCase />)
    expect(await screen.findByRole('heading', { name: '01 · 发现状态变化' })).toBeInTheDocument()
    expect(screen.getByText('15.000%')).toBeInTheDocument()
    expect(screen.getByText('-5')).toBeInTheDocument()
    expect(screen.getByText('<b>背景</b>')).toBeInTheDocument()
    expect(screen.queryByText('背景', { selector: 'b' })).toBeNull()
    expect(screen.getByRole('link', { name: '带入案例日期，前往历史回放 →' })).toHaveAttribute('href', '#/replay?start=2024-01-31&end=2024-02-01&mode=local')
    expect(screen.getByText('不是金融事件标注或买卖建议')).toBeInTheDocument()
  })

  it('surfaces a missing case and retries', async () => {
    vi.mocked(fetch).mockImplementationOnce(() => Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: '当前没有可用于研究案例的历史预警' }) } as Response))
    render(<ResearchCase />)
    expect(await screen.findByRole('alert')).toHaveTextContent('当前没有可用于研究案例的历史预警')
    fireEvent.click(screen.getByRole('button', { name: '重新读取案例' }))
    expect(await screen.findByRole('heading', { name: '01 · 发现状态变化' })).toBeInTheDocument()
  })
})
