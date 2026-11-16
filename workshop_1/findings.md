# Workshop 1: source findings

Everything below comes from raw responses kept under `workshop_1/samples/`. The working sample is
2 220 detections over Colombia in a 5-day window (2026-11-10 to 2026-11-13), of which 1 071 come from
VIIRS NOAA-20 and 1 149 from NOAA-21.

## F3: NASA FIRMS NRT (VIIRS NOAA-20 and NOAA-21)

The query we used:

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/-79.0,-4.5,-66.5,13.5/5
```

It answers HTTP 200 with a CSV of 14 columns:
`latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence,
version, bright_ti5, frp, daynight`.

Volume: 2 220 rows, about 180 KB, for five days. Day by day it drops as 812, 501, 391 and 516
detections. The profile is FRP min 0.00, mean 6.96, max 196.02 MW; confidence `n` 2 087, `l` 79, `h` 54;
1 784 day detections and 436 night ones; no nulls in any column.

### Six problems, with the record that shows each one

| # | Problem | Evidence from the sample |
|---|---|---|
| 1 | Naive duplicate detection finds nothing; realistic detection finds 44.5 % | Exact `(lat, lon, date, time, satellite)` duplicates: **0**. On a ~1.1 km grid (`round(2)` plus same day), **987 of 2 220 rows (44.5 %)** share a cell. At ~0.1 km, 31 rows. The duplicate signal depends entirely on the tolerance you pick. |
| 2 | `acq_time` is HHMM without zero padding | 436 rows carry a 3-digit `acq_time` (`630` means 06:30, `3` means 00:03). Read as an integer it silently turns into minutes or hours depending on the code. Those rows are exactly the 436 night detections. |
| 3 | Physically meaningless FRP values | 1 row with `frp = 0.00`, and 86 rows below 1 MW. An FRP of zero cannot be a fire detection, and it distorts any total. |
| 4 | The same fire appears as several near-identical records | Three rows with `frp = 196.02` at 2026-11-13 17:53 UTC, at 8.58028/-73.01519, 8.58118/-73.00967 and 8.58410/-73.01637. They sit within ~700 m, in the same minute, one with `h` confidence and two with `n`. This is the reason detections have to be grouped into fire events. |
| 5 | `confidence` is a discrete code, not a percentage | VIIRS returns `l`, `n` or `h`; MODIS returns 0-100. A filter such as `confidence > 50` means nothing on VIIRS, and joining both sensors without normalising silently keeps or drops everything. |
| 6 | The NRT endpoint cannot serve historical dates | Requests for 2024-01-22, a known fire episode, and for 2024-09-15 both returned **0 rows**, while "last 5 days" returned 1 071. NRT is a recent-window product, so history has to come from the archive (F1). |

## F2 and F4: the Open-Meteo sources

The F2 query went to `archive-api.open-meteo.com/v1/archive` for Bogotá (4.7110, -74.0721), between
2024-01-01 and 2024-01-10, with `models=era5` and `timezone=UTC`. It returned HTTP 200, 240 hourly
rows, `timezone: GMT` and **0 nulls**: temperature 7.5 to 22.6 °C, precipitation 0.0 to 0.8 mm, vapour
pressure deficit 0.0 to 1.46 kPa.

The F4 query hit `api.open-meteo.com/v1/forecast` for the same point with `past_days=2`,
`forecast_days=2` and `timezone=UTC`, and returned HTTP 200 with 96 hourly rows covering
2026-11-12T00:00 to 2026-11-15T23:00.

| # | Problem | Evidence |
|---|---|---|
| 7 | Local time comes back unless `timezone=UTC` is forced | With the parameter the response reports `timezone: GMT` and UTC hours. Without it, the same request returns Colombia local time, a silent 5-hour shift when it is joined with FIRMS `acq_time`, which is UTC. |
| 8 | Weather is a series, not an event | 240 hourly rows for one point cannot be stored in the event model. It needs the `weather_observation` table in long format, one row per variable. |
| 9 | Centroid approximation | One value per region is not an area average. ERA5 cells are 0.25° (~28 km) and cover several municipalities at once, so we declare it as a limitation and do not try to fix it. |

## What the 2026 sensor change looks like in the data

`VIIRS_SNPP_NRT` answers HTTP 200 with a header-only CSV and **0 rows**. That matches Suomi NPP
ceasing production on 2026-11-02 while its archive stays available, and it is the empirical proof the
baseline-per-sensor section needs.

## Files in `samples/`

| File | What it is |
|---|---|
| `firms_VIIRS_NOAA20_NRT_colombia_5d_*.csv` | Unmodified NOAA-20 response (1 071 rows) |
| `firms_VIIRS_NOAA21_NRT_colombia_5d_*.csv` | Unmodified NOAA-21 response (1 149 rows) |
| `firms_VIIRS_SNPP_NRT_*.csv` | Header-only response (sensor ceased) |
| `openmeteo_historical_era5_bogota_*.json` | Unmodified ERA5 response |
| `openmeteo_forecast_bogota_*.json` | Unmodified forecast response |
| `colombia_sample_profile.csv` | First 200 rows, working copy |
| `regions_centroids.csv` | 33 region centroids, the weather query input |
| `profile_summary.csv` | One-row-per-source summary exported by the notebook |

# Volumes and cross-source results

Everything in this half comes from `notebooks/01_source_profiling.ipynb`: 18 code cells, run from top
to bottom without failures.

## F1: archive volume for 2024 (Colombia bounding box)

| Sensor | Detections | Inside Colombia | Inside % | ΣFRP (MW) | FRP mean (MW) |
|---|---|---|---|---|---|
| `VIIRS_SNPP_SP` (375 m) | 319 981 | 107 432 | 33.6 % | 2 900 083 | 9.06 |
| `VIIRS_NOAA20_SP` (375 m) | 311 832 | 104 838 | 33.6 % | 2 836 330 | 9.10 |
| `MODIS_SP` (1 km) | 71 820 | 24 727 | 34.4 % | 2 329 333 | 32.43 |
| **Total** | **703 633** | **236 997** | **33.7 %** | **8 065 746** | - |

### The sensor effect, which is what the assignment asks to document

Two VIIRS sensors agree within 2.6 % for the same year, S-NPP against NOAA-20 at **1.026**, so they
can be pooled to lengthen the baseline once the factor is written down. NOAA-21 is a separate matter:
with about 3.7 years of history it belongs to the incremental stream and not to the baseline.

MODIS and VIIRS cannot be averaged together. VIIRS detects **8.8x** more records than MODIS, which is
another way of saying MODIS sees 11.4 % of the VIIRS count, and the mean FRP per detection differs by
**3.57x**, 32.43 MW against 9.08 MW, because a 1 km pixel gathers more energy and only large fires
cross its threshold. Put a VIIRS present against a MODIS baseline and the report shows an 8.8x
anomaly that came from the instrument. This is the failure mode the assignment expects teams to find
and write up.

Only 33.7 % of the records returned by the bounding box are Colombian. In November the same figure was
50.0 %. The leakage follows the season and the fire activity of the neighbouring countries, so the
filter cannot be skipped even for a single aggregation.

## Monthly detections per sensor, 2024

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

Two things come out of that table. The seasonality is strong and identical across sensors: January to
April, the dry season, carries about 76 % of the year, and May to June collapses by more than an order
of magnitude, which makes an anomaly against an annual mean meaningless and forces a baseline built on
a calendar window. And the three sensors move together, so the seasonality is signal. The instrument
difference is a shift in level, not a change in shape, which is why a per-sensor baseline works and a
pooled one does not.

## The weather panel (F2)

108 735 region-days, that is 33 regions over 3 235 days, from 2018-01-01 to 2026-11-09, with **no
nulls** in any variable.

| Variable | min | mean | max |
|---|---|---|---|
| `temp_max_c` | 6.90 | 28.08 | 41.10 |
| `rh_min_pct` | 8.00 | 64.11 | 97.00 |
| `precip_mm` | 0.00 | 8.88 | 254.50 |
| `wind_max_kmh` | 2.00 | 9.64 | 87.60 |
| `vpd_max_kpa` | 0.06 | 1.49 | 7.11 |

### Testing the assumption the indicator rests on (national, 2024)

| Variable | Correlation with daily detections |
|---|---|
| `vpd_max_kpa` (vapour pressure deficit) | **+0.830** |
| `precip_7d` (accumulated over 7 days) | **-0.689** |
| `temp_max_c` | +0.722 |
| `precip_mm` (same day) | -0.604 |

Dry, high-VPD days carry far more detections. A raw count comparison between two regions with
different rainfall is therefore not measuring an anomaly, it is measuring weather, and the indicator
has to say so.

## Overlap verification: five pairs of real records

NOAA-20 and NOAA-21 detections of the same fire, same day, within 2 km:

| date | N20 time | N21 time | N20 FRP | N21 FRP | distance (km) | N20 conf | N21 conf |
|---|---|---|---|---|---|---|---|
| 2026-11-10 | 07:01 | 06:03 | 2.48 | 2.70 | 0.07 | n | n |
| 2026-11-10 | 06:44 | 06:03 | 3.76 | 2.46 | 0.16 | n | n |
| 2026-11-10 | 06:24 | 06:03 | 1.21 | 2.43 | 0.30 | n | n |
| 2026-11-10 | 06:05 | 06:03 | 1.97 | 1.92 | 0.26 | n | n |
| 2026-11-10 | 06:41 | 06:03 | 1.50 | 1.50 | 0.12 | n | n |

In every pair the timestamp differs because the overpass differs, the position differs by up to about
300 m of geolocation spread, the FRP differs because the pixel footprint differs, and sometimes the
confidence code changes too. What the source never provides is an identifier, so the ingestion layer
has to build one.
