-- ---------------------------------------------------------------------------
-- sql/schema.sql
-- Wildfire Monitoring — canonical schema (Workshop 1 draft)
-- Target: PostgreSQL 14+ with PostGIS.
-- The notebook stage may use SQLite via pandas/GeoPandas; this file is the
-- design of record.
-- ---------------------------------------------------------------------------

-- Reference layer: administrative regions (33 for Colombia)
CREATE TABLE IF NOT EXISTS region (
    region_id     TEXT PRIMARY KEY,           -- e.g. DANE department code
    name          TEXT NOT NULL,
    level         TEXT NOT NULL DEFAULT 'department',
    centroid_lat  DOUBLE PRECISION NOT NULL,  -- used for the weather API
    centroid_lon  DOUBLE PRECISION NOT NULL,
    geometry      GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    source        TEXT NOT NULL               -- DANE / GADM / Natural Earth
);

-- Catalog of every data source (course model: source)
CREATE TABLE IF NOT EXISTS source (
    source_id     TEXT PRIMARY KEY,           -- firms_archive | firms_nrt_viirs | open_meteo_historical | open_meteo_forecast
    name          TEXT NOT NULL,
    url           TEXT NOT NULL,
    format        TEXT NOT NULL,              -- csv | json
    role          TEXT NOT NULL,              -- historical | incremental
    license       TEXT NOT NULL,              -- NASA EOSDIS open data | CC BY 4.0
    attribution   TEXT NOT NULL,              -- citation text required by the provider
    status        TEXT NOT NULL DEFAULT 'active', -- active | frozen | retired (e.g. VIIRS_SNPP after 2026-11-02)
    notes         TEXT
);

-- Canonical event table (as required by the course event model)
-- The course names the time column `timestamp`; here it is `observed_at`
-- (a reserved word is avoided). Mapping: timestamp == observed_at.
CREATE TABLE IF NOT EXISTS event (
    event_id      TEXT PRIMARY KEY,           -- deterministic hash, never serial
    source        TEXT NOT NULL REFERENCES source (source_id),
    event_type    TEXT NOT NULL,              -- fire_detection
    observed_at   TIMESTAMPTZ NOT NULL,       -- always UTC
    latitude      DOUBLE PRECISION NOT NULL,  -- WGS84 decimal degrees
    longitude     DOUBLE PRECISION NOT NULL,
    severity      DOUBLE PRECISION,           -- numeric value...
    severity_unit TEXT,                       -- ...and its unit (MW for FRP)
    raw_reference TEXT NOT NULL,              -- raw file name (source_YYYYMMDD_HHMMSS.ext) + line number
    content_hash  TEXT NOT NULL,              -- SHA-256 of the normalised source row; a new hash
                                              -- for the same event_id means the record was revised
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_event_observed_at ON event (observed_at);
CREATE INDEX IF NOT EXISTS idx_event_source       ON event (source);

-- Hazard-specific attributes for satellite hotspot detections
CREATE TABLE IF NOT EXISTS fire_detection (
    event_id        TEXT PRIMARY KEY REFERENCES event (event_id) ON DELETE CASCADE,
    region_id       TEXT REFERENCES region (region_id),
    brightness      DOUBLE PRECISION,   -- K   (MODIS)
    bright_ti4      DOUBLE PRECISION,   -- K   (VIIRS)
    bright_ti5      DOUBLE PRECISION,   -- K   (VIIRS)
    frp             DOUBLE PRECISION,   -- MW
    confidence_raw  TEXT,               -- 'l' | 'n' | 'h' (VIIRS) or 0-100 (MODIS)
    confidence_norm SMALLINT,           -- harmonised to 0-100
    satellite       TEXT NOT NULL,      -- N, 1, 20, 21
    instrument      TEXT NOT NULL,      -- MODIS | VIIRS
    scan            DOUBLE PRECISION,
    track           DOUBLE PRECISION,
    daynight        TEXT,               -- D | N
    product_version TEXT                -- NRT | SP + version
);

CREATE INDEX IF NOT EXISTS idx_fire_detection_region  ON fire_detection (region_id);
CREATE INDEX IF NOT EXISTS idx_fire_detection_product ON fire_detection (product_version);

-- Fire events: detections grouped in space and time (the main challenge)
CREATE TABLE IF NOT EXISTS fire_event (
    fire_event_id  TEXT PRIMARY KEY,          -- hash(rounded centroid + first_seen)
    region_id      TEXT REFERENCES region (region_id),
    first_seen     TIMESTAMPTZ NOT NULL,
    last_seen      TIMESTAMPTZ NOT NULL,
    centroid_lat   DOUBLE PRECISION NOT NULL,
    centroid_lon   DOUBLE PRECISION NOT NULL,
    n_detections   INTEGER NOT NULL,
    frp_sum        DOUBLE PRECISION,
    frp_max        DOUBLE PRECISION,
    sensor_set     TEXT[] NOT NULL,           -- which sensors contributed
    cluster_params JSONB NOT NULL             -- eps_space_km, eps_time_h, method
);

CREATE INDEX IF NOT EXISTS idx_fire_event_first_seen ON fire_event (first_seen);

-- Detections belonging to each event
CREATE TABLE IF NOT EXISTS fire_event_member (
    fire_event_id TEXT NOT NULL REFERENCES fire_event (fire_event_id) ON DELETE CASCADE,
    event_id      TEXT NOT NULL REFERENCES event (event_id) ON DELETE CASCADE,
    PRIMARY KEY (fire_event_id, event_id)
);

-- Weather series. NOT an event: a continuous field sampled per region.
-- This table exists because F2 and F4 do not fit the discrete event model.
CREATE TABLE IF NOT EXISTS weather_observation (
    region_id            TEXT NOT NULL REFERENCES region (region_id),
    observed_at          TIMESTAMPTZ NOT NULL,       -- always UTC
    variable             TEXT NOT NULL,              -- temperature_2m, precipitation, ...
    value                DOUBLE PRECISION,
    unit                 TEXT NOT NULL,              -- C | mm | km/h | kPa | %
    source               TEXT NOT NULL,              -- open_meteo_historical | open_meteo_forecast
    model                TEXT,                       -- era5 | era5_land | ifs
    grid_resolution_deg  DOUBLE PRECISION,
    raw_reference        TEXT NOT NULL,
    PRIMARY KEY (region_id, observed_at, variable, source)
);

CREATE INDEX IF NOT EXISTS idx_weather_observed_at ON weather_observation (observed_at);

-- Operational table: auditable record of each execution (course model: ingestion_run)
CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id            BIGSERIAL PRIMARY KEY,
    source            TEXT NOT NULL REFERENCES source (source_id),
    partition         TEXT NOT NULL,          -- e.g. '2019|VIIRS_NOAA20_SP'
    mode              TEXT NOT NULL CHECK (mode IN ('historical', 'incremental')),
    status            TEXT NOT NULL CHECK (status IN ('started', 'committed', 'failed')),
    rows_in           INTEGER,                -- rows read from the raw file
    rows_new          INTEGER,                -- rows inserted
    rows_updated      INTEGER,                -- rows whose content_hash changed
    rows_rejected     INTEGER,                -- rows sent to rejected_record
    watermark_before  TIMESTAMPTZ,
    watermark_after   TIMESTAMPTZ,
    error_message     TEXT,
    started           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished          TIMESTAMPTZ
);

-- Incremental state per source (course model: ingestion_state).
-- The watermark only advances after the partition commits.
CREATE TABLE IF NOT EXISTS ingestion_state (
    source_id         TEXT PRIMARY KEY REFERENCES source (source_id),
    watermark         TIMESTAMPTZ,            -- F3: max(acq_date + acq_time) UTC; F4: max(hourly.time)
    last_success      TIMESTAMPTZ,
    last_run_id       BIGINT REFERENCES ingestion_run (run_id),
    http_etag         TEXT,                   -- kept for change detection when the source sends it
    http_last_modified TEXT
);

-- Quarantine for records failing validation (course model: rejected_record)
CREATE TABLE IF NOT EXISTS rejected_record (
    rejected_id   BIGSERIAL PRIMARY KEY,
    run_id        BIGINT NOT NULL REFERENCES ingestion_run (run_id),
    source        TEXT NOT NULL REFERENCES source (source_id),
    reason        TEXT NOT NULL,              -- e.g. 'frp<=0', 'outside_colombia', 'bad_acq_time', 'lat_out_of_range'
    payload       JSONB NOT NULL,             -- the original row, unmodified
    raw_reference TEXT,
    rejected_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Course model: event_group (group_id, event_id).
-- In this domain a group is a fire event, so fire_event_member is the
-- physical table and event_group is exposed with the course's names.
CREATE OR REPLACE VIEW event_group AS
SELECT fire_event_id AS group_id, event_id
FROM fire_event_member;
