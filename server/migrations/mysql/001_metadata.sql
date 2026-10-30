CREATE TABLE IF NOT EXISTS source_files (
    id VARCHAR(32) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    path TEXT NOT NULL,
    path_sha256 CHAR(64) NOT NULL,
    size BIGINT UNSIGNED NOT NULL,
    mtime_ns BIGINT UNSIGNED NOT NULL,
    status VARCHAR(16) NOT NULL,
    record_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
    error_count INT UNSIGNED NOT NULL DEFAULT 0,
    sheets_json JSON NOT NULL,
    error TEXT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_source_files_path_hash (path_sha256),
    KEY idx_source_files_kind_path (kind, path(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS import_batches (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_id VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    record_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
    error TEXT NULL,
    started_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    PRIMARY KEY (id),
    KEY idx_import_batches_source (source_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS source_objects (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_id VARCHAR(32) NOT NULL,
    bucket_name VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    size BIGINT UNSIGNED NOT NULL,
    etag VARCHAR(128) NULL,
    version_id VARCHAR(128) NULL,
    archived_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_source_objects_content (source_id, sha256),
    KEY idx_source_objects_source (source_id, id),
    CONSTRAINT fk_source_objects_file FOREIGN KEY (source_id) REFERENCES source_files (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
