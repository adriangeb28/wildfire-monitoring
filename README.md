# Wildfire monitoring: multi-source ingestion and analysis

Course: Data Analysis Programming, semester 2026-II  
Team 3 · Repository: https://github.com/adriangeb28/wildfire-monitoring

| Stage | Status |
|---|---|
| Workshop 1: hazard definition, source validation, data contract | delivered ([`workshop_1/`](workshop_1/)) |
| Workshop 2: Docker stack, Bronze ingestion DAG, Silver processing DAG | delivered ([`workshop_2/`](workshop_2/)) |
| Workshop 3: Gold layer (PySpark), event grouping, governance KPIs & Airflow DAG | delivered ([`workshop_3/`](workshop_3/)) |
| Workshop 4: Interactive Plotly Dash applications (Governance & Storytelling) | delivered ([`workshop_4/`](workshop_4/)) |

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

## Pipeline (Workshops 2, 3 & 4)

```text
FIRMS NRT (N20, N21) ─┐   bronze_ingestion DAG     datalake_bronze/                 silver_processing DAG          datalake_silver/
Open-Meteo forecast ──┴─► every 3 h (TaskFlow) ─► <source>_YYYYMMDD_HHMMSS.json ─► FileSensor + preprocessing ─► <topic>_YYYYMMDD_HHMMSS.parquet
                                                   raw payload + sha256 + headers                                   _quarantine/rejected_*.parquet
                                                                                                                           │
  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  ▼
gold_processing DAG (PySpark 3.5) ──► datalake_gold/governance_*.parquet   ──► dashboard/governance_app.py   (http://localhost:8050)
(daily / manual trigger)          ──► datalake_gold/storytelling_*.parquet ──► dashboard/storytelling_app.py (http://localhost:8051)
```

- **Bronze** keeps each response exactly as received inside a JSON envelope (FIRMS answers CSV, so
  the CSV text is the `payload`), with the masked request, HTTP headers, SHA-256 and the schema check.
- **Silver** types, validates and cleans the rows ([`src/pipeline/preprocess.py`](src/pipeline/preprocess.py)
  documents every rule and the Workshop 1 finding behind it), quarantines invalid rows with a reason,
  and uses a state registry so a record is written once, a revised record is marked `revised`, and
  re-running never duplicates anything.
- **Gold** ([`src/pipeline/gold.py`](src/pipeline/gold.py)) runs on Apache Spark (PySpark) to cluster
  nearby detections into ~1 km² fire events (`grid_cell`), join daily meteorological drivers
  (`temp_max_c`, `rh_min_pct`, `precip_sum_mm`, `wind_max_kmh`), compute weather-conditioned anomaly
  levels (`Very low` to `Extreme`), and publish two Parquet datasets: `governance_*.parquet` and
  `storytelling_*.parquet`.
- **Presentation Layer** ([`dashboard/`](dashboard/)) exposes two independent Plotly Dash web
  applications reading exclusively from `datalake_gold/*.parquet` via `pd.read_parquet()`:
  - **Data Governance Dashboard (`http://localhost:8050`):** Technical audit of ingestion volume, null
    rates, outlier rates, schema compliance, and SLA threshold statuses.
  - **Regional Wildfire Storytelling Dashboard (`http://localhost:8051`):** Functional interface with
    interactive date, department, and severity filters, narrative insights, and meteorological driver charts.

## Running it

### With Docker & Local Dashboards (the workshop setup)

Requirements: Docker Desktop (or Docker Engine + Compose v2), Python 3.11+ (with `.venv`), and a FIRMS `MAP_KEY`.

```bash
cp .env.example .env              # Windows: Copy-Item .env.example .env ; then set FIRMS_MAP_KEY
docker compose build              # Airflow 2.10.5 image + Java 17, PySpark, pandas, pyarrow, shapely
docker compose up airflow-init    # once: metadata DB migration + user airflow / airflow
docker compose up -d              # webserver, scheduler, triggerer, postgres, warehouse-db
```

Open http://localhost:8080 (user `airflow`, password `airflow`). Trigger the three DAGs in sequence
for an end-to-end run:

1. `bronze_ingestion` (runs every 3 hours; writes three raw JSON envelopes to `datalake_bronze/`).
2. `silver_processing` (runs every 30 minutes via `FileSensor`; writes validated Parquet to `datalake_silver/`).
3. `gold_processing` (runs daily or via **Trigger DAG**; runs PySpark to write `governance_*.parquet`
   and `storytelling_*.parquet` into `datalake_gold/`).

Once `datalake_gold/` has Parquet outputs, launch both dashboards in two separate terminals:

```bash
# Terminal 1 — Data Governance Dashboard (http://localhost:8050)
python -m pip install -r requirements.txt
python -m dashboard.governance_app

# Terminal 2 — Regional Storytelling Dashboard (http://localhost:8051)
python -m dashboard.storytelling_app
```

Stop containers with `docker compose down` (data stays in the folders; `down -v` also wipes the databases).

### Without Docker (development)

```bash
python -m pip install -r requirements.txt
python ingest.py --mode incremental --from-fixtures   # offline: recorded responses -> Bronze -> Silver
python ingest.py --mode incremental                   # live: needs FIRMS_MAP_KEY in .env
python ingest.py --mode historical --start 2024-01-01 --end 2024-01-30
python ingest.py --mode status
python -m pytest -q                                   # 19 tests on recorded responses
```

## Repository structure

```text
airflow/dags/               bronze_ingestion_dag.py, silver_processing_dag.py, gold_processing_dag.py
src/pipeline/               sources, bronze, preprocess, regions, silver, gold (all pipeline logic)
dashboard/                  utils.py, governance_app.py (port 8050), storytelling_app.py (port 8051)
ingest.py                   command-line entry point: historical | incremental | status
docker-compose.yml          Airflow stack + PostGIS warehouse; docker/airflow/ holds the image
datalake_bronze/            raw JSON envelopes        datalake_silver/   Parquet + _quarantine/
datalake_gold/              PySpark Gold Parquet      reference/         33-region layer (geoBoundaries)
config/sources.yaml         one entry per source: URL, format, schedule, watermark
sql/schema.sql          canonical database schema (loaded into warehouse-db)
tests/, tests/fixtures/     pytest suite and recorded responses
notebooks/                  01 source profiling (W1), 02 Silver DQ (W2/W3), 03 Gold preview (W3)
workshop_1/ .. workshop_4/  deliverables, reports, and visual documentation per workshop
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
boundaries come from geoBoundaries `gbOpen/COL/ADM1` (ODbL 1.0); DANE's Marco Geoestadístico
Nacional is the official alternative. Built with Apache Airflow, Apache Spark (PySpark), Plotly Dash,
Dash Bootstrap Components, pandas, PyArrow and Shapely.