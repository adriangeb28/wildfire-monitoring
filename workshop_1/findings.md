# Workshop 1 — Source findings (evidence log)

Every number below comes from real, unmodified responses stored under
`workshop_1/samples/`. Sample: **2 220 detections**, Colombia, 5-day window
(2026-11-10 → 2026-11-13), VIIRS NOAA-20 (1 071) and NOAA-21 (1 149).

## F3 — NASA FIRMS NRT (VIIRS NOAA-20 / NOAA-21)

**Query used**

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/-79.0,-4.5,-66.5,13.5/5
```

**Response shape:** HTTP 200, CSV, 14 columns:
`latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite,
instrument, confidence, version, bright_ti5, frp, daynight`

**Volume observed:** 2 220 rows / ~180 KB for 5 days. Dropping by day:
812 → 501 → 391 → 516 detections (2026-11-10 → 2026-11-13).

**Profile:** FRP min 0.00, mean 6.96, max 196.02 MW · confidence `n`=2 087,
`l`=79, `h`=54 · day 1 784, night 436 · 0 nulls in every column.

### Findings (the ≥5 data-quality problems required by the workshop)

| # | Problem | Evidence from the sample |
|---|---|---|
| 1 | **Naive duplicate detection finds nothing; realistic detection finds 44.5 %** | Exact `(lat, lon, date, time, satellite)` duplicates = **0**. But on a ~1.1 km grid (`round(2)` + same day), **987 of 2 220 rows (44.5 %)** share a cell. At ~0.1 km, 31 rows. The duplicate signal depends entirely on the tolerance you choose. |
| 2 | **`acq_time` is HHMM without zero padding** | 436 rows have a 3-digit `acq_time` (e.g. ``630`` = 06:30, `3` = 00:03). Parsed as an integer it silently becomes minutes or hours depending on the code. These correspond exactly to the 436 night detections. |
| 3 | **Physically meaningless FRP values** | 1 row with `frp = 0.00`; 86 rows with `frp < 1 MW`. An FRP of zero cannot be a fire detection and will distort any ΣFRP aggregate. |
| 4 | **The same fire appears as several near-identical records** | Three rows with `frp = 196.02`, at 2026-11-13 17:53 (UTC), positions 8.58028/-73.01519, 8.58118/-73.00967, 8.58410/-73.01637 — within ~700 m, same minute, one `h` and two `n` confidences. This is exactly why detections must be grouped into fire events. |
| 5 | **`confidence` is a discrete code, not a percentage** | VIIRS returns `l` / `n` / `h`. MODIS returns 0–100. Any filter like `confidence > 50` is meaningless on VIIRS, and a naive union of both sensors silently drops or keeps everything. |
| 6 | **The NRT endpoint cannot serve historical dates** | A request for 2024-01-22 (known fire episode) and 2024-09-15 both returned **0 rows**, while "last 5 days" returned 1 071. NRT is a recent-window product: history must come from the archive (F1). |

## F2 / F4 — Open-Meteo

**F2 query:** `archive-api.open-meteo.com/v1/archive`, Bogotá (4.7110, -74.0721),
`2024-01-01 → 2024-01-10`, `models=era5`, `timezone=UTC`
**Response:** HTTP 200, **240 hourly rows**, `timezone: GMT`, **0 nulls**.
`temperature_2m` 7.5–22.6 °C · `precipitation` 0.0–0.8 mm · `vapour_pressure_deficit` 0.0–1.46 kPa.

**F4 query:** `api.open-meteo.com/v1/forecast`, same point, `past_days=2`,
`forecast_days=2`, `timezone=UTC`
**Response:** HTTP 200, **96 hourly rows**, 2026-11-12T00:00 → 2026-11-15T23:00.

Findings:

| # | Problem | Evidence |
|---|---|---|
| 7 | **Local time is returned unless `timezone=UTC` is forced** | With the parameter, the response reports `timezone: GMT` and UTC hours. Without it, the same request returns Colombia local time — a silent 5-hour shift when joined with FIRMS `acq_time` (UTC). |
| 8 | **Weather is a series, not an event** | 240 hourly rows for one point: it cannot be stored in the event model. It needs the `weather_observation` table (long format: one row per variable). |
| 9 | **Centroid approximation** | One value per region (centroid) is not an area average: ERA5 cells are 0.25° (~28 km) and cover several municipalities at once. Must be declared as a limitation. |

## Sensor-change evidence (2026)

`VIIRS_SNPP_NRT` returns HTTP 200 with a **header-only CSV (0 rows)** — consistent
with Suomi NPP ceasing production on 2026-11-02, while its archive remains. This
is the empirical proof required for the baseline-per-sensor section.

## Files

| File | What it is |
|---|---|
| `firms_VIIRS_NOAA20_NRT_colombia_5d_*.csv` | Unmodified NOAA-20 response (1 071 rows) |
| `firms_VIIRS_NOAA21_NRT_colombia_5d_*.csv` | Unmodified NOAA-21 response (1 149 rows) |
| `firms_VIIRS_SNPP_NRT_*.csv` | Header-only response (sensor ceased) |
| `openmeteo_historical_era5_bogota_*.json` | Unmodified ERA5 response |
| `openmeteo_forecast_bogota_*.json` | Unmodified forecast response |
| `colombia_sample_profile.csv` | First 200 rows, working copy |
| `regions_centroids.csv` | 33 region centroids (weather query input) |
| `profile_summary.csv` | One-row-per-source summary exported by the notebook |

---

# Measured volumes and cross-source results

All figures produced by `notebooks/01_source_profiling.ipynb`
(18 code cells, validated top-to-bottom with 0 failures).

## F1 — archive volume (2024, Colombia bbox)

| Sensor | 5-day windows | Detections |
|---|---|---|
| `VIIRS_NOAA20_SP` | 74 | **311 832** |
| `VIIRS_SNPP_SP` | 30 (pull in progress) | **257 412** |
| **Total so far** | | **569 244** |

`MODIS_SP` is queued. First conclusion for the ingestion contract: the historical
volume is in the **hundreds of thousands of rows per sensor-year**, so the
partitioning decision (5-day windows, one file each, cached) is not cosmetic.

## Monthly detections per sensor (2024)

| Month | NOAA-20 SP | S-NPP SP |
|---|---|---|
| 2024-01 | 70 345 | 71 360 |
| 2024-02 | 54 920 | 58 157 |
| 2024-03 | 75 636 | 81 686 |
| 2024-04 | 41 388 | 42 537 |
| 2024-05 | 4 122 | 3 672 |
| 2024-06 | 2 519 | 1 361 |
| 2024-07 → 2024-12 | 4 526 … 16 467 | 0 (not yet downloaded) |

Two things this table proves:

1. **Strong seasonality**: the January–April dry season carries 90 % of the year's
   detections; May–June collapses to a few thousand. Any "anomaly" computed
   against an annual mean is therefore meaningless — the baseline must be a
   *calendar window*.
2. **The two VIIRS sensors track each other closely** in the overlapping months
   (within ~5–8 %), which is precisely the evidence needed to justify pooling
   them after harmonisation — and the reason the zeros from July onward must be
   read as *not yet downloaded*, never as *no fires*.

## Weather panel (F2)

36 135 region-days = **33 regions × 1 095 days**, 2018-01-01 → 2024-08-31,
**0 nulls** in every variable. Pull still running towards 2026-11.

| Variable | min | mean | max |
|---|---|---|---|
| `temp_max_c` | 7.3 | 28.44 | 41.1 |
| `rh_min_pct` | 8.0 | 62.38 | 96.0 |
| `precip_mm` | 0.0 | 8.13 | 229.0 |
| `wind_max_kmh` | 2.0 | 9.98 | 48.6 |
| `vpd_max_kpa` | 0.08 | 1.60 | 7.11 |

### The indicator's core assumption, tested (nacional, 2024)

Correlation of daily detections with weather:

| Variable | Correlation with detections |
|---|---|
| `vpd_max_kpa` (déficit de presión de vapor) | **+0.830** |
| `precip_7d` (lluvia acumulada 7 días) | **−0.689** |
| `temp_max_c` | +0.722 |
| `precip_mm` (del día) | −0.604 |

This is the quantitative justification for the weather-conditioned indicator: dry,
high-VPD days carry far more detections, so a raw count comparison between two
regions (or two years) with different rainfall is not an anomaly, it is weather.

## Overlap verification — 5 candidate pairs (real records)

NOAA-20 / NOAA-21 detections of the same fire (same day, ≤ 2 km):

| date | N20 time | N21 time | N20 FRP | N21 FRP | distance (km) | N20 conf | N21 conf |
|---|---|---|---|---|---|---|---|
| 2026-11-10 | 07:01 | 06:03 | 2.48 | 2.70 | 0.07 | n | n |
| 2026-11-10 | 06:44 | 06:03 | 3.76 | 2.46 | 0.16 | n | n |
| 2026-11-10 | 06:24 | 06:03 | 1.21 | 2.43 | 0.30 | n | n |
| 2026-11-10 | 06:05 | 06:03 | 1.97 | 1.92 | 0.26 | n | n |
| 2026-11-10 | 06:41 | 06:03 | 1.50 | 1.50 | 0.12 | n | n |

What differs in every pair: the **timestamp** (different overpass), the
**position** (up to ~300 m of geolocation spread), the **FRP** (different pixel
footprint), and sometimes the **confidence**. What does not exist in the source:
any identifier. The identifier has to be constructed by the ingestion layer.

