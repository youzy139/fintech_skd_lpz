import { describe, expect, it } from 'vitest'
import { buildMarketWorkspaceLink, parseMarketWorkspaceLink, restrictSharedWorkspace } from './researchLinks'

const workspace = { search: '国债 & 利率', category: '债券', watchlist_only: true, watchlist: ['BOND.YIELD', 'CODE,1', '代码/?'], selected_asset: 'BOND.YIELD', visible_range: 60 as const }

describe('market research links', () => {
  it('roundtrips all workspace fields with URL encoding', () => {
    const link = buildMarketWorkspaceLink(workspace, 'http://localhost:5174/#/overview')
    expect(parseMarketWorkspaceLink(new URL(link).hash)).toEqual({ workspace })
  })

  it('uses safe defaults and rejects unsupported versions', () => {
    expect(parseMarketWorkspaceLink('#/overview?share=market-workspace-v1&range=30')).toEqual({ workspace: { search: '', category: 'all', watchlist_only: false, watchlist: [], selected_asset: 'SPX.GI', visible_range: 500 } })
    expect(parseMarketWorkspaceLink('#/overview?share=other')).toEqual({ error: '研究链接版本不受支持，已保留当前工作区' })
    expect(parseMarketWorkspaceLink('#/features?share=market-workspace-v1')).toBeNull()
    expect(parseMarketWorkspaceLink('#/overview')).toBeNull()
  })

  it('limits untrusted link fields and deduplicates watchlist entries', () => {
    const parsed = parseMarketWorkspaceLink(`#/overview?share=market-workspace-v1&q=${'x'.repeat(150)}&category=&watch=A&watch=A&watch=B`)
    expect(parsed).toEqual({ workspace: { search: 'x'.repeat(100), category: 'all', watchlist_only: false, watchlist: ['A', 'B'], selected_asset: 'SPX.GI', visible_range: 500 } })
  })

  it('prunes assets that are unavailable to the recipient without mutating the link draft', () => {
    const result = restrictSharedWorkspace({ ...workspace, watchlist: [...workspace.watchlist, 'PRIVATE'] }, [{ code: 'BOND.YIELD', category: '债券' }])
    expect(result.pruned).toBe(true)
    expect(result.workspace).toEqual({ ...workspace, watchlist: ['BOND.YIELD'] })
    expect(workspace.watchlist).toHaveLength(3)
    const fallback = restrictSharedWorkspace(workspace, [])
    expect(fallback.workspace.selected_asset).toBe('')
    expect(fallback.workspace.category).toBe('all')
  })
})
