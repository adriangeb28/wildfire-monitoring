# Canonical mapping

How each source field lands in the canonical event model, and how the hazard-specific attributes land
in the domain tables of [`sql/schema.sql`](../sql/schema.sql). This is the Workshop 1 version: the
tables below were filled against the real responses, and the ER draft lives in
`docs/figures/er_diagram.png`.

## Canonical fields

| Canonical field | Type | Rule |
|---|---|---|
| `event_id` | text | Deterministic hash, never a serial. Built from source + position + timestamp. |
| `source` | text | One of `firms_archive`, `firms_nrt_viirs`, `open_meteo_historical`, `open_meteo_forecast`. |
| `event_type` | text | `fire_detection` for hotspot records. |
| `observed_at` | timestamptz | Always UTC. |
| `latitude` / `longitude` | double | WGS84, decimal degrees. |
| `severity` + `severity_unit` | double + text | FRP in MW for detections. |
| `raw_reference` | text | Raw file name (`source_YYYYMMDD_HHMMSS.ext`) + line number. |
| `content_hash` | text | SHA-256 of the normalised row. Same `event_id` with a new hash means the record was revised (new vs changed detection). |

## F1: NASA FIRMS archive (VIIRS and MODIS)

| Source field | Canonical field | Rule |
|---|---|---|
| `latitude`, `longitude` | `latitude`, `longitude` | as delivered (WGS84) |
| `acq_date` + `acq_time` | `observed_at` | `acq_time` is an integer HHMM **without zero padding** (`3` = 00:03). Build UTC timestamp explicitly. |
| `frp` | `severity` | MW |
| `brightness` (MODIS) / `bright_ti4` (VIIRS) | `fire_detection.brightness` / `.bright_ti4` | K |
| `confidence` | `fire_detection.confidence_raw` | MODIS: integer 0-100. VIIRS: `l` / `n` / `h` |
| - | `fire_detection.confidence_norm` | Harmonise to 0-100 (document the mapping used) |
| `satellite`, `instrument` | `fire_detection.satellite`, `.instrument` | as delivered |
| `daynight`, `scan`, `track`, `version` | `fire_detection.*` | as delivered |

## F3: NASA FIRMS NRT (VIIRS NOAA-20 and NOAA-21)

Same mapping as F1, with `source = firms_nrt_viirs` and `product_version = 'NRT'`. One thing to keep
in mind: NRT records are replaced by SP records with a lag of about five months, so the same detection
can change after it was published.

## F2 and F4: Open-Meteo, historical and forecast

These two do not fit the discrete event model, and forcing them in breaks it. A weather value is a
sample of a continuous field at a place and a time. No `event` row is written for weather: the
measurements live in `weather_observation`, one row per variable, and reach the fire events through
`region_id` and the date. Writes are upserts keyed on (`region_id`, `observed_at`, `variable`,
`source`), because forecast and `past_days` values change between calls.

| Source field | Target | Rule |
|---|---|---|
| `hourly.time` | `weather_observation.observed_at` | Force `timezone=UTC` in the request. |
| `hourly.<variable>` | `weather_observation.value` | One row per variable (long format). |
| - | `weather_observation.unit` | `°C`, `mm`, `km/h`, `kPa`, `%` |
| - | `weather_observation.model` | `era5`, `era5_land`, or forecast model |
| `latitude`/`longitude` of request | `region_id` | Join on the region centroid; the value is a centroid approximation, not an area average. |

## Hazard-specific attributes

`fire_detection` carries brightness, bright_ti4, bright_ti5, frp, confidence_raw, confidence_norm,
satellite, instrument, scan, track, daynight and product_version.

`fire_event` is where detections get grouped in space and time. The proposed parameters are
`eps_space` around 1.5 to 2 km, because the VIIRS footprint is 375 m but cross-sensor geolocation
spread reaches about 1 km, and `eps_time` around 24 h with connected-component chaining, because a
fire burns for days. The identifier is a hash of the rounded centroid plus `first_seen`. We report
detection count, grouped event count and total FRP, and we say which of the three the indicator uses.

`region` holds the 33 units, from geoBoundaries `gbOpen/COL/ADM1` (ODbL 1.0); DANE's Marco
Geoestadístico Nacional is the official alternative.

## Operational tables (course model)

| Course table | Table in `sql/schema.sql` | Notes |
|---|---|---|
| `source` | `source` | URL, format, role, licence, attribution, status (`active` / `frozen` / `retired`) |
| `ingestion_run` | `ingestion_run` | `rows_in`, `rows_new`, `rows_updated`, `rows_rejected`, watermark before/after, `started`, `finished` |
| `ingestion_state` | `ingestion_state` | `watermark`, `last_success`, last run; advanced only after commit |
| `event` | `event` | `timestamp` of the course model is `observed_at` |
| `event_group` | view over `fire_event_member` | a group is a fire event: `group_id` = `fire_event_id` |
| `rejected_record` | `rejected_record` | run, source, reason, unmodified payload (JSONB) |

## Normalisation rules

| Concern | Rule |
|---|---|
| Timestamps | UTC, `TIMESTAMPTZ`. No naive datetimes anywhere. |
| Coordinates | WGS84, decimal degrees. Validate against region polygons (the Colombia bbox includes 5 neighbouring countries). |
| Severity | FRP in MW; scale documented per source. |
| Confidence | Normalised to 0-100 with a documented mapping table. |
| Units | Declared per column; never inferred at read time. |

## Still open

The `l`/`n`/`h` to 0-100 mapping is not fixed yet (`confidence_raw` is always kept unchanged, so it can be re-derived),
and the clustering thresholds are values we proposed and never tuned. Both belong to
Workshop 2.
