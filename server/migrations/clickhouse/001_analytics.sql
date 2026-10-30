CREATE TABLE IF NOT EXISTS dwd_source_files (
    id String,
    kind LowCardinality(String),
    path String,
    size UInt64,
    mtime_ns Int64,
    status LowCardinality(String),
    record_count UInt64,
    error_count UInt32,
    sheets_json String,
    error Nullable(String),
    updated_at DateTime64(6),
    transformation_version String
) ENGINE = ReplacingMergeTree
ORDER BY id;

CREATE TABLE IF NOT EXISTS dwd_source_records (
    source_id String,
    record_index UInt32,
    kind LowCardinality(String),
    source_path String,
    import_batch_id UInt64,
    event_date Nullable(Date32),
    title String,
    payload_json String,
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(coalesce(event_date, toDate32('1900-01-01')))
ORDER BY (source_id, record_index);

CREATE TABLE IF NOT EXISTS dwd_source_record_tags (
    source_id String,
    record_index UInt32,
    kind LowCardinality(String),
    tag String,
    event_date Nullable(Date32),
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(coalesce(event_date, toDate32('1900-01-01')))
ORDER BY (source_id, record_index, tag);

CREATE TABLE IF NOT EXISTS dws_source_daily_stats (
    source_id String,
    event_date Date32,
    record_count UInt64,
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (source_id, event_date);

CREATE TABLE IF NOT EXISTS dws_source_fields (
    source_id String,
    name String,
    field_position UInt32,
    non_null_count UInt64,
    transformation_version String
) ENGINE = ReplacingMergeTree
ORDER BY (source_id, name);

CREATE TABLE IF NOT EXISTS dws_source_tag_stats (
    source_id String,
    kind LowCardinality(String),
    tag String,
    record_count UInt64,
    transformation_version String
) ENGINE = ReplacingMergeTree
ORDER BY (source_id, tag);

CREATE TABLE IF NOT EXISTS dws_market_features (
    event_date Date32,
    feature LowCardinality(String),
    value Float64,
    model_version String,
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, feature);

CREATE TABLE IF NOT EXISTS ads_market_states (
    event_date Date32,
    cluster Int32,
    label String,
    confidence Float64,
    model_version String,
    trained_through Date32,
    features_json String,
    contributions_json String,
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY event_date;

CREATE TABLE IF NOT EXISTS ads_alerts (
    event_date Date32,
    rule String,
    rule_version String,
    level LowCardinality(String),
    title String,
    evidence String,
    value Nullable(Float64),
    threshold Nullable(Float64),
    transformation_version String
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, rule, title);
