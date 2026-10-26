export type Asset = { code: string; name: string; category: string; field: string; start: string; end: string; rows: number }
export type AssetSeries = { code: string; name: string; field: string; unit: string; points: { date: string; value: number }[] }
export type Contribution = { feature: string; value: number; standardized: number }
export type Regime = { date: string; label: string; confidence: number; model_version: string; trained_through: string; features: Record<string, number>; contributions: Contribution[] }
export type Alert = { date: string; rule: string; level: string; title: string; evidence: string; value?: number; threshold?: number }
export type Quality = { catalog_records: number; available_assets: number; loaded_assets: number; duplicate_dates: number; invalid_rows: number; total_rows: number; missing_assets: string[] }
export type HomeSummary = { latest: Regime; alert_count: number; loaded_assets: number; total_rows: number; state_count: number }
