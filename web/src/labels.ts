export const featureNames: Record<string, string> = {
  market_return: '市场收益',
  volatility: '年化波动率',
  momentum: '中期动量',
  correlation: '资产相关性',
  trend: '短期趋势',
  sample_count: '有效资产数',
}

export const ruleNames: Record<string, string> = {
  HIGH_VOLATILITY: '高波动',
  HIGH_CORRELATION: '相关性异常',
  REGIME_CHANGE: '状态切换',
}

export const regimeColors = ['#c43d3d', '#3478a7', '#d18a2d', '#238367', '#8563a8']
