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

## F1 — archive volume, 2024 complete (Colombia bbox)

| Sensor | Detections | Inside Colombia | Inside % | ΣFRP (MW) | FRP mean (MW) |
|---|---|---|---|---|---|
| `VIIRS_SNPP_SP` (375 m) | 319 981 | 107 432 | 33.6 % | 2 900 083 | 9.06 |
| `VIIRS_NOAA20_SP` (375 m) | 311 832 | 104 838 | 33.6 % | 2 836 330 | 9.10 |
| `MODIS_SP` (1 km) | 71 820 | 24 727 | 34.4 % | 2 329 333 | 32.43 |
| **Total** | **703 633** | **236 997** | **33.7 %** | **8 065 746** | — |

### The sensor effect, quantified (the graded requirement)

1. **Two VIIRS sensors agree within 2.6 %** for the same year
   (S-NPP / NOAA-20 = **1.026**). They can therefore be pooled — after declaring
   the factor — to lengthen the baseline. NOAA-21 has only ~3.7 years of history,
   so it is used for the incremental stream, not as the baseline anchor.
2. **MODIS and VIIRS are not interchangeable.** VIIRS detects **8.8×** more
   records than MODIS (MODIS sees 11.4 % of the VIIRS count), and the mean FRP
   per detection differs by **3.57×** (32.43 MW vs 9.08 MW) because a 1 km pixel
   aggregates more energy and only the large fires cross its threshold.
   **Consequence: a baseline built on MODIS with a present of VIIRS would report
   an ~8.8× "anomaly" that is purely an instrument change.** This is the exact
   failure mode the assignment asks teams to document.
3. **Only 33.7 % of the bounding-box records are Colombian.** In November the
   figure was 50.0 %. The leakage varies with the season and with fire activity
   in neighbouring countries — which means the filter cannot be skipped even for
   a single aggregation.

## Monthly detections per sensor (2024, complete)

| Month | MODIS | NOAA-20 | S-NPP |
|---|---|---|---|
| 1 | 16 937 | 71 651 | 72 419 |
| 2 | 13 357 | 54 920 | 58 157 |
| 3 | 17 613 | 75 636 | 81 686 |
| 4 | 8 144 | 41 388 | 42 537 |
| 5 | 793 | 4 122 | 3 672 |
| 6 | 558 | 2 519 | 1 997 |
| 7 | 849 | 4 526 | 2 634 |
| 8 | 2 538 | 10 704 | 10 805 |
| 9 | 2 694 | 11 344 | 11 358 |
| 10 | 2 386 | 10 723 | 10 196 |
| 11 | 2 046 | 7 832 | 8 002 |
| 12 | 3 905 | 16 467 | 16 518 |

Two conclusions that shape the design:

1. **Strong seasonality, identical across sensors**: January–April (dry season)
   carries ~76 % of the year's detections; May–June collapses by more than an
   order of magnitude. Any anomaly computed against an annual mean is therefore
   meaningless: the baseline must be a **calendar window** (same days of the year,
   previous years).
2. **The three sensors move together**, so seasonality is real signal, not
   instrument noise. The instrument difference is a *level* shift (8.8×), not a
   *shape* change — which is exactly why a per-sensor baseline works and a pooled
   one does not.

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

