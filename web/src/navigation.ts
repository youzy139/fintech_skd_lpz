export const pages = [
  ['home', '网站首页', 'home', 'PRODUCT'],
  ['overview', '市场总览', 'overview', 'OVERVIEW'],
  ['regimes', '状态分析', 'regimes', 'MARKET REGIMES'],
  ['features', '特征分析', 'features', 'FEATURE EXPLORER'],
  ['alerts', '预警中心', 'alerts', 'RISK & EVIDENCE'],
  ['replay', '历史回放', 'replay', 'HISTORICAL REPLAY'],
  ['data', '数据中心', 'data', 'DATA CATALOG'],
] as const

export type Page = typeof pages[number][0]

export function allowedPages(domains: string[]): Page[] {
  return pages.filter(([id]) => id === 'data' ? domains.includes('catalog') : id === 'home' || id === 'replay' ? domains.includes('market') && domains.includes('catalog') : domains.includes('market')).map(([id]) => id)
}

export function resolvePage(hash: string, domains: string[]): Page {
  const allowed = allowedPages(domains)
  const requested = hash.replace(/^#\/?/, '') as Page
  return allowed.includes(requested) ? requested : allowed[0] ?? 'data'
}
