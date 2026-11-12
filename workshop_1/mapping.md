# Canonical Mapping — Wildfire Monitoring

Maps every source field onto the canonical event model, and the hazard-specific
attributes onto the domain tables in [`sql/schema.sql`](../sql/schema.sql).

Status: **draft** — fill the `TODO` rows after profiling the real responses
(`notebooks/01_source_profiling.ipynb`).

## Canonical fields

| Canonical field | Type | Rule |
|---|---|---|
| `event_id` | text | Deterministic hash, never a serial. Built from source + position + timestamp. |
| `source` | text | One of `firms_archive`, `firms_nrt_viirs`, `open_meteo_historical`, `open_meteo_forecast`. |
| `event_type` | text | `fire_detection` for hotspot records. |
| `observed_at` | timestamptz | Always UTC. |
| `latitude` / `longitude` | double | WGS84, decimal degrees. |
| `severity` + `severity_unit` | double + text | FRP in MW for detections. |
| `raw_reference` | text | Path of the unmodified response + line number or record id. |

## F1 — NASA FIRMS archive (VIIRS / MODIS)

| Source field | Canonical field | Rule |
|---|---|---|
| `latitude`, `longitude` | `latitude`, `longitude` | as delivered (WGS84) |
| `acq_date` + `acq_time` | `observed_at` | `acq_time` is an integer HHMM **without zero padding** (`3` = 00:03). Build UTC timestamp explicitly. |
| `frp` | `severity` | MW |
| `brightness` (MODIS) / `bright_ti4` (VIIRS) | `fire_detection.brightness` / `.bright_ti4` | K |
| `confidence` | `fire_detection.confidence_raw` | MODIS: integer 0–100. VIIRS: `l` / `n` / `h` |
| — | `fire_detection.confidence_norm` | Harmonise to 0–100 (document the mapping used) |
| `satellite`, `instrument` | `fire_detection.satellite`, `.instrument` | as delivered |
| `daynight`, `scan`, `track`, `version` | `fire_detection.*` | as delivered |

## F3 — NASA FIRMS NRT (VIIRS NOAA-20 / NOAA-21)

Same mapping as F1, with `source = firms_nrt_viirs` and
`product_version = 'NRT'`. NOTE: NRT records are replaced by SP records with a
~5-month lag, so the same detection can change after publication.

## F2 / F4 — Open-Meteo (historical and forecast)

**These sources do not fit the discrete event model.** A weather value is a
sample of a continuous field at a location and time, not a discrete event. Only
`observed_at`, `latitude`, `longitude` (region centroid) and `raw_reference` map
onto `event`; the measurements live in `weather_observation`.

| Source field | Target | Rule |
|---|---|---|
| `hourly.time` | `weather_observation.observed_at` | Force `timezone=UTC` in the request. |
| `hourly.<variable>` | `weather_observation.value` | One row per variable (long format). |
| — | `weather_observation.unit` | `°C`, `mm`, `km/h`, `kPa`, `%` |
| — | `weather_observation.model` | `era5`, `era5_land`, or forecast model |
| `latitude`/`longitude` of request | `region_id` | Join on the region centroid; the value is a centroid approximation, not an area average. |

## Hazard-specific attributes

- **`fire_detection`**: brightness, bright_ti4, bright_ti5, frp, confidence_raw,
  confidence_norm, satellite, instrument, scan, track, daynight, product_version.
- **`fire_event`** (grouping): cluster detections in space and time.
  - `eps_space` ≈ 1.5–2 km (VIIRS footprint 375 m; cross-sensor geolocation spread ~1 km)
  - `eps_time` ≈ 24 h with connected-component chaining (a fire burns for days)
  - `event_id` = hash(rounded centroid + first_seen)
  - Report **three** metrics: detection count, grouped event count, ΣFRP.
- **`region`**: 33 units, DANE Marco Geoestadístico Nacional.

## Normalisation rules

| Concern | Rule |
|---|---|
| Timestamps | UTC, `TIMESTAMPTZ`. No naive datetimes anywhere. |
| Coordinates | WGS84, decimal degrees. Validate against region polygons (the Colombia bbox includes 5 neighbouring countries). |
| Severity | FRP in MW; scale documented per source. |
| Confidence | Normalised to 0–100 with a documented mapping table. |
| Units | Declared per column; never inferred at read time. |

## TODO

- [ ] Fill exact field lists after downloading real responses.
- [ ] Document the `l/n/h` → 0–100 mapping actually used.
- [ ] Add the ER diagram (draft) to `docs/`.
- [ ] Confirm the `event_id` hash inputs.
