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

-- Canonical event table (as required by the course event model)
CREATE TABLE IF NOT EXISTS event (
    event_id      TEXT PRIMARY KEY,           -- deterministic hash, never serial
    source        TEXT NOT NULL,              -- firms_nrt_viirs | firms_archive | ...
    event_type    TEXT NOT NULL,              -- fire_detection | burned_area
    observed_at   TIMESTAMPTZ NOT NULL,       -- always UTC
    latitude      DOUBLE PRECISION NOT NULL,  -- WGS84 decimal degrees
    longitude     DOUBLE PRECISION NOT NULL,
    severity      DOUBLE PRECISION,           -- numeric value...
    severity_unit TEXT,                       -- ...and its unit (MW for FRP)
    raw_reference TEXT NOT NULL,              -- file path + line/id in the raw response
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
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

-- Operational table: makes ingestion restartable and auditable
CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id            BIGSERIAL PRIMARY KEY,
    source            TEXT NOT NULL,
    partition         TEXT NOT NULL,          -- e.g. '2019|VIIRS_NOAA20_SP'
    mode              TEXT NOT NULL,          -- historical | incremental
    status            TEXT NOT NULL,          -- started | committed | failed
    rows_read         INTEGER,
    rows_written      INTEGER,
    watermark_before  TIMESTAMPTZ,
    watermark_after   TIMESTAMPTZ,
    error_message     TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ
);
