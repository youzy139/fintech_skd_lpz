ALTER TABLE dwd_source_files ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;
ALTER TABLE dwd_source_records ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;
ALTER TABLE dwd_source_record_tags ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;
ALTER TABLE dws_source_daily_stats ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;
ALTER TABLE dws_source_fields ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;
ALTER TABLE dws_source_tag_stats ADD COLUMN IF NOT EXISTS generation UInt64 DEFAULT 1;

CREATE TABLE IF NOT EXISTS catalog_publication_runs (
    source_id String,
    generation UInt64,
    status LowCardinality(String),
    record_count UInt64,
    error Nullable(String),
    updated_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(generation)
ORDER BY source_id;

CREATE TABLE IF NOT EXISTS catalog_publications (
    source_id String,
    generation UInt64,
    record_count UInt64,
    published_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(generation)
ORDER BY source_id;

CREATE VIEW IF NOT EXISTS active_source_files AS
SELECT f.id, f.kind, f.path, f.size, f.mtime_ns, f.status, f.record_count, f.error_count,
       f.sheets_json, f.error, f.updated_at, f.transformation_version
FROM dwd_source_files AS f
INNER JOIN catalog_publications AS p FINAL ON f.id = p.source_id AND f.generation = p.generation;

CREATE VIEW IF NOT EXISTS active_source_records AS
SELECT r.source_id, r.record_index, r.kind, r.source_path, r.import_batch_id, r.event_date,
       r.title, r.payload_json, r.transformation_version
FROM dwd_source_records AS r
INNER JOIN catalog_publications AS p FINAL ON r.source_id = p.source_id AND r.generation = p.generation;

CREATE VIEW IF NOT EXISTS active_source_record_tags AS
SELECT t.source_id, t.record_index, t.kind, t.tag, t.event_date, t.transformation_version
FROM dwd_source_record_tags AS t
INNER JOIN catalog_publications AS p FINAL ON t.source_id = p.source_id AND t.generation = p.generation;

CREATE VIEW IF NOT EXISTS active_source_daily_stats AS
SELECT d.source_id, d.event_date, d.record_count, d.transformation_version
FROM dws_source_daily_stats AS d
INNER JOIN catalog_publications AS p FINAL ON d.source_id = p.source_id AND d.generation = p.generation;

CREATE VIEW IF NOT EXISTS active_source_fields AS
SELECT d.source_id, d.name, d.field_position, d.non_null_count, d.transformation_version
FROM dws_source_fields AS d
INNER JOIN catalog_publications AS p FINAL ON d.source_id = p.source_id AND d.generation = p.generation;

CREATE VIEW IF NOT EXISTS active_source_tag_stats AS
SELECT d.source_id, d.kind, d.tag, d.record_count, d.transformation_version
FROM dws_source_tag_stats AS d
INNER JOIN catalog_publications AS p FINAL ON d.source_id = p.source_id AND d.generation = p.generation;
