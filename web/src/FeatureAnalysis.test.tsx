import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FeatureAnalysis from './FeatureAnalysis'
import type { Regime } from './types'

vi.mock('./Chart', () => ({ default: () => <div>历史图表</div> }))

const latest: Regime = { date: '2024-05-01', label: '测试', confidence: 0.8, model_version: 'test', trained_through: '2024-04-30', features: {}, contributions: [] }
const metadata = {
  feature_contract: {
    algorithm: 'market-features-v1', feature_version: 'features-test',
    input: '仅收盘价格', time_basis: '按观测行计算', visibility: '训练排除当日', missing_policy: '不填充',
    features: [{ name: 'volatility', title: '年化波动率', formula: '市场收益在 7 行窗口内计算。', window: 7, minimum_observations: 7, unit: 'annualized_ratio', model_input: true }],
  },
  model_parameters: { volatility_window: 7 }, input_version: 'input-test', data_version: 'catalog-test', state_model_version: 'test',
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('特征口径', () => {
  it('展示服务端实际窗口与输入版本', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string) => ({ ok: true, json: async () => path.endsWith('/latest') ? latest : metadata })))
    render(<FeatureAnalysis states={[latest]} latest={latest} />)
    expect(await screen.findByText('市场收益在 7 行窗口内计算。')).toBeInTheDocument()
    expect(screen.getByText(/窗口 7 行/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('查看版本与输入摘要'))
    expect(screen.getByText('input-test')).toBeVisible()
    expect(screen.queryByText(/20 日窗口/)).not.toBeInTheDocument()
  })

  it('元数据失败保留图表并支持重试', async () => {
    let failed = false
    const fetch = vi.fn(async (path: string) => {
      if (path.endsWith('/metadata') && !failed) { failed = true; return { ok: false, status: 503, json: async () => ({ detail: '特征定义暂不可用' }) } }
      return { ok: true, json: async () => path.endsWith('/latest') ? latest : metadata }
    })
    vi.stubGlobal('fetch', fetch)
    render(<FeatureAnalysis states={[latest]} latest={latest} />)
    expect(await screen.findByText('特征定义暂不可用')).toBeInTheDocument()
    expect(screen.getByText('历史图表')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    expect(await screen.findByText('市场收益在 7 行窗口内计算。')).toBeInTheDocument()
  })

  it('使用最新特征接口数值，故障时说明显示数据的日期并支持重试', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.endsWith('/latest')) return fail ? { ok: false, status: 503, json: async () => ({ detail: '特征读取失败' }) } : { ok: true, json: async () => ({ ...latest, date: '2024-05-02', features: { momentum: 0.123 } }) }
      return { ok: true, json: async () => metadata }
    }))
    render(<FeatureAnalysis states={[latest]} latest={latest} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('2024-05-01')
    expect(screen.getByText('历史图表')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    expect(await screen.findByText('12.30%')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
