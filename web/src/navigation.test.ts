import { describe, expect, it } from 'vitest'
import { allowedPages, resolvePage } from './navigation'

describe('permission-aware page links', () => {
  it('resolves refresh links and rejects pages outside the account scope', () => {
    expect(resolvePage('#/features', ['market', 'catalog'])).toBe('features')
    expect(resolvePage('#/replay', ['market'])).toBe('overview')
    expect(resolvePage('#/overview', ['catalog'])).toBe('data')
    expect(resolvePage('#/unknown', ['market', 'catalog'])).toBe('home')
    expect(allowedPages([])).toEqual([])
  })
})
