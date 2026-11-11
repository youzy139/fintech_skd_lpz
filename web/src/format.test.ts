import { afterEach, describe, expect, it, vi } from 'vitest'
import { directionTone, downloadCsv, numeric, percent } from './format'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('research values and CSV exports', () => {
  it('distinguishes missing observations from numeric zero', () => {
    expect(numeric(null)).toBe('—')
    expect(percent(undefined)).toBe('—')
    expect(numeric(Infinity)).toBe('—')
    expect(percent(0)).toBe('0.00%')
    expect(percent(-.125)).toBe('-12.50%')
  })

  it('uses China market direction colors without coloring missing values', () => {
    expect(directionTone(.01)).toBe('positive')
    expect(directionTone(-.01)).toBe('negative')
    expect(directionTone(null)).toBe('')
    expect(directionTone(Infinity)).toBe('')
  })

  it('exports quoted UTF-8 CSV and neutralizes spreadsheet expressions', async () => {
    let exported: Blob | undefined
    const createObjectURL = vi.fn((blob: Blob) => { exported = blob; return 'blob:csv' })
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    downloadCsv('observations.csv', [['日期', 'value'], ['=HYPERLINK(1)', -2], ['  @SUM(1)', null], ['a,b', 0]])
    expect(click).toHaveBeenCalledOnce()
    const text = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(exported!) })
    expect(text).toContain("'=HYPERLINK(1)")
    expect(text).toContain("'  @SUM(1)")
    expect(text).toContain('"-2"')
    expect(text).toContain('"a,b","0"')
    expect(text).toContain(String.fromCharCode(13, 10))
    expect(exported?.type).toBe('text/csv;charset=utf-8;')
  })
})
