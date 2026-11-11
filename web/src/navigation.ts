export const pages = [
  ['home', '终端首页', 'home', 'MARKET TERMINAL', 'research'],
  ['overview', '市场总览', 'overview', 'MARKET OVERVIEW', 'research'],
  ['regimes', '状态分析', 'regimes', 'MARKET REGIMES', 'research'],
  ['features', '特征分析', 'features', 'FEATURE EXPLORER', 'research'],
  ['alerts', '预警中心', 'alerts', 'RISK & EVIDENCE', 'research'],
  ['replay', '历史回放', 'replay', 'HISTORICAL REPLAY', 'research'],
  ['data', '数据中心', 'data', 'DATA CATALOG', 'research'],
  ['accounts', '账号权限', 'accounts', 'ACCESS CONTROL', 'system'],
  ['audit', '审计记录', 'audit', 'AUDIT TRAIL', 'system'],
  ['system', '系统监控', 'system', 'SYSTEM HEALTH', 'system'],
] as const

export type Page = typeof pages[number][0]
export type Role = 'observer' | 'analyst' | 'admin'

export function allowedPages(domains: string[], role: Role = 'observer'): Page[] {
  return pages.filter(([id, , , , group]) => {
    if (group === 'system') return role === 'admin'
    if (id === 'data') return domains.includes('catalog')
    if (id === 'home' || id === 'replay') return domains.includes('market') && domains.includes('catalog')
    return domains.includes('market')
  }).map(([id]) => id)
}

export function resolvePage(hash: string, domains: string[], role: Role = 'observer'): Page {
  const allowed = allowedPages(domains, role)
  const requested = hash.replace(/^#\/?/, '') as Page
  return allowed.includes(requested) ? requested : allowed[0] ?? 'data'
}
