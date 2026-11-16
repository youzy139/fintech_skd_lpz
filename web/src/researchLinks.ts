import type { ResearchWorkspace } from './types'

export type MarketWorkspaceDraft = Pick<ResearchWorkspace, 'search' | 'category' | 'watchlist_only' | 'watchlist' | 'selected_asset' | 'visible_range'>
export type ParsedMarketWorkspaceLink = { workspace: MarketWorkspaceDraft; error?: never } | { workspace?: never; error: string }

export const emptyMarketWorkspace = (): MarketWorkspaceDraft => ({ search: '', category: 'all', watchlist_only: false, watchlist: [], selected_asset: 'SPX.GI', visible_range: 500 })

export function parseMarketWorkspaceLink(hash: string): ParsedMarketWorkspaceLink | null {
  const [route, query = ''] = hash.replace(/^#\/?/, '').split('?')
  if (route !== 'overview') return null
  const params = new URLSearchParams(query)
  if (!params.has('share')) return null
  if (params.get('share') !== 'market-workspace-v1') return { error: '研究链接版本不受支持，已保留当前工作区' }
  const range = Number(params.get('range'))
  const watchlist = [...new Set(params.getAll('watch').filter(code => code.length > 0 && code.length <= 200))].slice(0, 100)
  return {
    workspace: {
      search: (params.get('q') ?? '').slice(0, 100),
      category: (params.get('category') ?? 'all').slice(0, 100) || 'all',
      watchlist_only: params.get('only') === '1',
      watchlist,
      selected_asset: (params.get('selected') ?? 'SPX.GI').slice(0, 200),
      visible_range: range === 60 || range === 250 || range === 500 ? range : 500,
    },
  }
}

export function buildMarketWorkspaceLink(workspace: MarketWorkspaceDraft, base = window.location.href): string {
  const params = new URLSearchParams({ share: 'market-workspace-v1', q: workspace.search.slice(0, 100), category: workspace.category.slice(0, 100), selected: workspace.selected_asset.slice(0, 200), range: String(workspace.visible_range) })
  if (workspace.watchlist_only) params.set('only', '1')
  for (const code of workspace.watchlist.slice(0, 100)) params.append('watch', code)
  const url = new URL(base)
  url.hash = `/overview?${params.toString()}`
  return url.toString()
}

export function restrictSharedWorkspace(workspace: MarketWorkspaceDraft, assets: { code: string; category: string }[]): { workspace: MarketWorkspaceDraft; pruned: boolean } {
  const allowed = new Set(assets.map(item => item.code))
  const categories = new Set(assets.map(item => item.category))
  const watchlist = workspace.watchlist.filter(code => allowed.has(code))
  const category = workspace.category === 'all' || categories.has(workspace.category) ? workspace.category : 'all'
  const selected_asset = allowed.has(workspace.selected_asset) ? workspace.selected_asset : (assets[0]?.code ?? '')
  const restricted = { ...workspace, watchlist, category, selected_asset }
  return { workspace: restricted, pruned: JSON.stringify(restricted) !== JSON.stringify(workspace) }
}
