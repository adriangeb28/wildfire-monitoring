# Wildfire Monitoring — Multi-Source Ingestion and Analysis System

**Course:** Data Analysis Programming — Semester 2026-II
**Workshop:** No. 1 — Hazard Definition, Source Validation, and Data Contract
**Team 3**

| Student | Code |
|---|---|
| César Ospina | 20222020059 |
| Santiago Alfonso | 20222020093 |
| Adrián Espinosa | 20222020104 |

## Hazard

Vegetation fires detected by satellite thermal anomaly. The unit of observation
is a **hotspot detection** (a pixel flagged as thermally anomalous), not a fire as
a discrete entity. Grouping detections into fire events is part of the design.

- **Severity measure:** Fire Radiative Power (FRP) in **MW**. Brightness
  temperature (K) is a secondary measure. `confidence` is a quality filter, not a
  severity measure.
- **Geographic scope:** Colombia — 33 regions (32 departments + Bogotá D.C.)
- **Historical window:** 2018-01-01 to present (primary baseline, VIIRS NOAA-20),
  plus 2000/2012 to present as per-sensor long-term context.
- **Current situation:** last 24 hours and last 7 days, compared against the
  historical average for the same calendar window, conditioned on weather.

> **Scope of claims.** This project monitors and describes anomalous fire
> activity. It does **not** predict fires and its indicator is not a forecast.

## Data sources

| # | Role | Source | Access | Format |
|---|---|---|---|---|
| F1 | Historical | NASA FIRMS Archive | Bulk archive download | CSV / SHP / JSON |
| F2 | Historical | Open-Meteo Historical Weather (ERA5) | REST API | JSON |
| F3 | Incremental | NASA FIRMS NRT (VIIRS NOAA-20 / NOAA-21) | REST API (`MAP_KEY`) | CSV |
| F4 | Incremental | Open-Meteo Forecast | REST API | JSON |

Source limits, licensing and watermarks are declared in
[`config/sources.yaml`](config/sources.yaml). Every source in this project was
queried for real; the unmodified responses are kept under
[`workshop_1/samples/`](workshop_1/samples/).

## Repository structure

```
src/                    ingestion package (sources, normalization, storage)
ingest.py               command-line entry point (stub at this stage)
config/sources.yaml     one entry per source: URL, format, schedule, watermark
data/raw/               raw landing zone (git-ignored)
sql/                    schema definitions
dashboard/              Dash application
tests/                  tests
tests/fixtures/         recorded sample responses
notebooks/              profiling and analysis notebooks
docs/                   decisions, diagrams, report sources
workshop_1/             workshop-1 deliverables (samples, mapping)
```

## Setup

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env      # then edit .env with your own credentials
```

Credentials are read from environment variables (or `.env`). **Never commit
`.env`.** See [`.env.example`](.env.example).

## Large files

`data/raw/` is git-ignored. Bulk archives are not committed; only small samples
live in `workshop_1/samples/`. Download instructions for the large partitions
are documented in `docs/downloading.md`.

## Attribution and licences

- **NASA FIRMS** — NASA EOSDIS. Data are openly available; cite NASA FIRMS/LANCE.
- **Open-Meteo** — data under **CC-BY 4.0**, free tier for non-commercial use
  only. Attribute "Weather data by Open-Meteo.com" and ERA5/Copernicus.
- **Administrative boundaries** — DANE, Marco Geoestadístico Nacional.
