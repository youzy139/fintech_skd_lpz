export type Asset = { code: string; name: string; category: string; field: string; start: string; end: string; rows: number }
export type AssetSeries = { code: string; name: string; field: string; unit: string; points: { date: string; value: number }[] }
export type Contribution = { feature: string; value: number | null; standardized: number | null }
export type FeatureDefinition = { name: string; title: string; unit: string; window: number; minimum_observations: number; formula: string; model_input: boolean }
export type FeatureContract = { schema_version: number; algorithm: string; feature_version: string; analysis_start: string; input: string; time_basis: string; visibility: string; missing_policy: string; features: FeatureDefinition[] }
export type FeatureMetadata = { feature_contract: FeatureContract; model_parameters: Record<string, string | number>; data_version: string; input_version: string; state_model_version: string | null }
export type LatestFeatures = Pick<Regime, 'date' | 'features' | 'contributions' | 'model_version'>
export type CalculationContract = { schema_version: number; version: string; model: Record<string, string | number>; alerts: Record<string, number>; feature_contract: FeatureContract; input_version: string; input_through: string }
export type Regime = { date: string; label: string; cluster?: number; regime_id?: number; regime_identity?: string; confidence: number | null; model_version: string; trained_through: string; features: Record<string, number | null>; contributions: Contribution[] }
export type Alert = { date: string; rule: string; level: string; title: string; evidence: string; value?: number; threshold?: number; rule_version?: string }
export type Quality = { catalog_records: number; available_assets: number; loaded_assets: number; duplicate_dates: number; invalid_rows: number; total_rows: number; missing_assets: string[] }
export type HomeSummary = { latest: Regime; alert_count: number; loaded_assets: number; total_rows: number; state_count: number }
export type ReplayCalendar = { min_date: string; max_date: string; suggested_start: string; suggested_end: string }
export type KafkaStatus = { enabled: boolean; bootstrap_servers: string; topic: string; topic_partitions: number; connection: string }
export type FlinkStatus = { enabled: boolean; rest_url: string; output_topic: string; late_topic: string; checkpoint_interval_ms: number; connection: string }
export type ReplayRegime = Omit<Regime, 'confidence' | 'features' | 'contributions'> & { confidence: number | null; features: Record<string, number | null>; contributions: { feature: string; value: number | null; standardized: number | null }[] }
export type ReplayResult = { event_time: string; replay_time: string; input_start: string; input_end: string; input_records: number; observed_assets: string[]; features: Record<string, number | null>; state: ReplayRegime | null; alerts: Alert[]; model_version: string }
export type ReplayEventStats = { produced_events: number; consumed_events: number; duplicate_events: number; retry_count: number; commit_count: number; stale_jobs_stopped?: number }
export type ReplayDayTiming = { event_date: string; input_ms: number; model_ms: number; ack_ms: number; total_ms: number }
export type ReplayTiming = { engine_start_ms: number | null; pipeline_start_ms: number | null; last_day: ReplayDayTiming | null; processed_days: number; total_day_ms: number; average_day_ms: number | null; max_day_ms: number; pipeline: Record<string, number> }
export type ReplayRecovery = { state: 'none' | 'paused' | 'rebuilding' | 'completed' | 'failed'; count: number; rebuild_ms: number | null }
export type ReplaySession = { id: string; run_id?: string | null; flink_job_id?: string | null; savepoint_path?: string | null; model_identity?: string; calculation_contract?: CalculationContract | null; lineage_status?: string; mode: 'local' | 'kafka' | 'flink'; start_date: string; end_date: string; status: 'pending' | 'running' | 'paused' | 'completed' | 'failed'; speed: number; processed_days: number; total_days: number; current_date: string | null; progress: number; error: string | null; latest_sequence?: number; recovery?: ReplayRecovery; event_stats: ReplayEventStats; timing?: ReplayTiming; latest_result: ReplayResult | null }
export type ReplayResultsPage = { session_id: string; results: { sequence: number; event_date: string; result: ReplayResult }[]; next_sequence: number; has_more: boolean }
export type StabilityPeriod = 'all' | 'development' | 'validation' | 'holdout'
export type StabilityDistribution = { min: number | null; median: number | null; max: number | null }
export type StabilityRunPeriod = {
  state_days: number; first_state: string | null; last_state: string | null
  switch_count: number; switches_per_100_state_days: number | null
  refit_boundary_count: number; refit_boundary_switch_count: number
  refit_boundary_switch_share: number | null; refit_boundary_switch_rate: number | null
  episode_count: number; median_duration_days: number | null; p90_duration_days: number | null; max_duration_days: number | null
  semantic_distribution: Record<string, number>
}
export type StabilityRun = {
  run_id: string; training_window: number; refit_interval: number; random_seed: number; is_reference: boolean
  periods: Record<StabilityPeriod, StabilityRunPeriod>
}
export type StabilityComparison = {
  period: StabilityPeriod; left_run_id: string; right_run_id: string
  common_state_days: number; common_start: string | null; common_end: string | null
  adjusted_rand_index: number | null; semantic_agreement: number | null
}
export type ModelCardAsset = {
  code: string; name: string; category: string; field: string; model_input: boolean; exclusion_reason: string | null
  declared_start: string; declared_end: string; observed_start: string | null; observed_end: string | null
  declared_rows: number; valid_rows: number; analysis_rows: number; observed_vs_declared: number | null
  positive_rows: number; nonpositive_rows: number; invalid_rows: number; duplicate_dates: number
}
export type ResearchContextItem = { record_id: string; kind: string; title: string; source_path: string; source_date: string; source_time: string | null; source_timestamp: string | null; time_basis: string }
export type ResearchEvidence = {
  event_time: string; rule: string; rule_version: string; alert: Alert; state: Regime; previous_state: Regime | null
  history_days: number; parameters: Record<string, number | boolean>; evidence_links: { type: string; url: string }[]
  context?: { cutoff_date: string | null; status: string; description: string; sources: { kind: string; status: string; total: number | null; items: ResearchContextItem[] }[]; excluded: { kind: string; reason: string }[] }
}
export type ResearchCase = {
  case_version: string; case_id: string; selection_policy: string; title: string; event_time: string; is_financial_event_label: boolean
  feature_changes: { feature: string; current: number | null; previous: number | null; delta: number | null }[]
  replay: { mode: 'local'; start_date: string; end_date: string; url: string; description: string }
  conclusion: { observation: string; statistical_evidence: string; validation: string; coverage_note: string; limitations: string }
  evidence: ResearchEvidence
}
export type ModelCard = {
  model_card_version: string; intended_use: string; out_of_scope: string
  analysis_start: string; observed_through: string | null
  loaded_series: number; price_assets: number; excluded_series: number; catalog_missing_assets: string[]
  valid_observations: number; price_observations: number; nonpositive_price_rows: number; invalid_rows: number; duplicate_dates: number
  union_price_observation_days: number; first_feature_day: string | null; last_feature_day: string | null; feature_days: number
  post_first_feature_union_days: number; covered_after_first_feature_days: number; dropped_after_first_feature_days: number; dropped_after_first_feature_dates: string[]; post_first_feature_coverage: number | null
  feature_sample_count: { min: number | null; median: number | null; max: number | null; latest: number | null }
  state_days: number; state_sample_count: { min: number | null; median: number | null; max: number | null; latest: number | null }
  state_days_below_price_assets: number; assets: ModelCardAsset[]; limitations: string[]
}
export type StabilityReport = {
  schema_version: number; report_type: 'regime_stability'; evaluation_version: string; evaluation_id: string
  protocol_version: string; protocol_status: string; reference_run_id: string
  generated_at: string; input_version: string; feature_version: string; feature_sha256: string; feature_days: number
  loaded_assets: number; model_parameters: Record<string, string | number>
  model_card?: ModelCard
  fixed: { minimum_history: number; cluster_count: number; regime_identity: string }
  grid: { training_windows: number[]; refit_intervals: number[]; random_seeds: number[]; run_count: number }
  period_definitions: Record<StabilityPeriod, { label: string; start: string | null; end: string | null }>
  runs: StabilityRun[]; comparisons: StabilityComparison[]
  summary: Record<StabilityPeriod, { pair_count: number; common_state_days: StabilityDistribution; adjusted_rand_index: StabilityDistribution; semantic_agreement: StabilityDistribution }>
  metric_definitions: Record<string, string>; limitations: string[]
  source_sha256: Record<string, string>
  daily_results?: { file: string; sha256: string; run_count: number; state_days: number }
}
