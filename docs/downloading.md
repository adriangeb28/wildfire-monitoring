# Downloading the data (large files)

Nothing large is committed to this repository. `data/raw/` and `data/reference/`
are git-ignored; only small samples live in `workshop_1/samples/`.

Everything below is reproducible with the scripts in `tools/`.

## 0. Credentials

Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored.

| Variable | Where to get it |
|---|---|
| `FIRMS_MAP_KEY` | https://firms.modaps.eosdis.nasa.gov/api/map_key/ (free, instant) |
| `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` | https://urs.earthdata.nasa.gov/users/new (only needed for the email-based bulk archive) |

Open-Meteo needs **no key**.

## 1. Region layer — 33 administrative units (8.7 MB)

```powershell
$env:PYTHONPATH = "$PWD\vendor;$PWD\src"
python tools/build_regions.py
```

- Downloads `geoBoundaries gbOpen COL ADM1` (33 features, **ODbL 1.0**) into
  `data/reference/regions_col_adm1.geojson`.
- Writes `workshop_1/samples/regions_centroids.csv` (33 rows, committed).
- Alternative official source: **DANE, Marco Geoestadístico Nacional**
  (recommended by the course). geoBoundaries is used here because it exposes a
  direct programmatic download; the 33 units and their names match.

## 2. F3 — FIRMS near-real-time (small, no partition needed)

```powershell
python tools/collect_sample.py
```

Pulls the last 5 days for VIIRS NOAA-20 and NOAA-21 over the Colombia bbox and
profiles them. Writes the unmodified CSVs into `workshop_1/samples/`.

## 3. F1 — FIRMS archive (standard processing), partitioned by 5-day windows

The area API returns **at most 5 days per request**, and the `*_SP` sources serve
the archive-quality records for historical dates. A year is therefore 73
requests.

```powershell
python tools/pull_history.py 2024 VIIRS_NOAA20_SP VIIRS_SNPP_SP MODIS_SP
```

- Output: `data/raw/firms_history/<year>/<source>/<window_start>.csv`
- Manifest: `data/raw/firms_history/<year>/manifest.csv` (status per window)
- Re-running is safe: existing non-empty windows are reported as `cached`.
- 1 s pause between requests; the documented limit is **5000 transactions /
  10 min**.

**Alternative, email-based bulk archive.** The official archive download
(https://firms.modaps.eosdis.nasa.gov/download/) delivers CSV/SHP/JSON per
request by email after an Earthdata or email-code login. It is the method the
assignment describes; the API path above is used because it is automatable and
idempotent. Both serve the same standard-processing records. Document whichever
you use in the report.

## 4. F2 / F4 — Open-Meteo weather

Historical (ERA5 reanalysis), one call for all region centroids:

```powershell
python tools/pull_weather.py --mode historical --start 2018-01-01 --end 2026-11-01
```

Forecast with the recent past:

```powershell
python tools/pull_weather.py --mode forecast --past-days 7
```

Rules that must never change:

- `timezone=UTC` on every request (otherwise local time is returned and joins
  shift by 5 hours).
- One coordinate list (33 centroids), not 33 separate calls.
- Free tier: 10 000 calls/day, 5 000/hour, 600/minute — non-commercial only,
  data under **CC-BY 4.0** ("Weather data by Open-Meteo.com").

## Rate-limit etiquette

- Cache everything; never re-download a partition that already exists.
- Sleep between requests (`PAUSE_SECONDS` in `tools/pull_history.py`).
- On HTTP 429/503: exponential backoff, then resume from the manifest.
