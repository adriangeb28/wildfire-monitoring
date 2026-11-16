# Wildfire monitoring: multi-source ingestion and analysis

Course: Data Analysis Programming, semester 2026-II
Workshop No. 1: hazard definition, source validation and data contract
Team 3

| Student | Code |
|---|---|
| César Ospina | 20222020059 |
| Santiago Alfonso | 20222020093 |
| Adrián Espinosa | 20222020104 |

## The hazard

Vegetation fires seen as thermal anomalies from a satellite. What we observe is a hotspot detection,
a pixel flagged as unusually hot, and not a fire. Several detections from different overpasses and
different sensors can describe the same fire, so grouping them into events is part of the design and
not a later cleanup.

Severity is Fire Radiative Power in MW, with brightness temperature in K as a secondary reading. The
`confidence` field is a quality flag; we never use it as a severity measure.

We work on Colombia, in 33 units (32 departments plus Bogotá D.C.). The primary baseline starts on
2018-01-01, because VIIRS NOAA-20 is the only sensor that is both long-lived and still transmitting;
MODIS from 2000 and S-NPP from 2012 stay as long-term context, always read per sensor. "Current
situation" means the last 24 hours and the last 7 days, set against the historical average for the
same calendar window and against the weather.

This project monitors and describes anomalous fire activity. It does not predict fires, and its
indicator is not a forecast.

## Data sources

| # | Role | Source | Access | Format |
|---|---|---|---|---|
| F1 | Historical | NASA FIRMS Archive | Bulk archive download | CSV / SHP / JSON |
| F2 | Historical | Open-Meteo Historical Weather (ERA5) | REST API | JSON |
| F3 | Incremental | NASA FIRMS NRT (VIIRS NOAA-20 / NOAA-21) | REST API (`MAP_KEY`) | CSV |
| F4 | Incremental | Open-Meteo Forecast | REST API | JSON |

Limits, licences and watermarks for each one are declared in
[`config/sources.yaml`](config/sources.yaml). All four were queried for real and the unmodified
responses are kept under [`workshop_1/samples/`](workshop_1/samples/), which is the evidence the
workshop asks for.

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

Credentials come from environment variables or from `.env`. Never commit `.env`; see
[`.env.example`](.env.example) for the variables we use.

## Large files

`data/raw/` is git-ignored. Bulk archives are not committed, only small samples under
`workshop_1/samples/`. How to download the big partitions is written down in
`docs/downloading.md`.

## Attribution and licences

NASA FIRMS data are open through NASA EOSDIS, and citing NASA FIRMS/LANCE is expected. Open-Meteo
publishes under CC-BY 4.0 with a free tier for non-commercial use, so the attribution "Weather data
by Open-Meteo.com" and ERA5/Copernicus appears wherever its data is used. The administrative
boundaries come from DANE, Marco Geoestadístico Nacional, with geoBoundaries as the programmatic
alternative.
