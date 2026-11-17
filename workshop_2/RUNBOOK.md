# Workshop 2 runbook: run the stack and collect the evidence

Who: whoever has Docker Desktop and the FIRMS `MAP_KEY`. Time: about 30 minutes of work spread over
**at least 2 hours**, because the polls must be at least one hour apart (Workshop 1 requirement) and
the FIRMS NRT feed needs time to publish new overpasses.

Every item marked **[evidence]** goes into the report (`workshop_2/report.pdf`). Save screenshots in
`workshop_2/screenshots/` with the names given.

## 0. Prepare (5 min)

```bash
git pull
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env`: set `FIRMS_MAP_KEY` (the real key). On Linux also set `AIRFLOW_UID` to the output of
`id -u`. Nothing else needs to change.

## 1. Build and start (10 min, first time)

```bash
docker compose build
docker compose up airflow-init          # wait for "exited with code 0"
docker compose up -d
docker compose ps                       # all services "healthy" (webserver can take ~1 min)
```

**[evidence]** `01_compose_ps.png`: the `docker compose ps` output with the services healthy.

Open http://localhost:8080, log in with `airflow` / `airflow`.

**[evidence]** `02_airflow_dags.png`: the DAG list showing `bronze_ingestion` and `silver_processing`.

## 2. First Bronze run (T = 0)

In the UI: `bronze_ingestion` → **Trigger DAG** (play button). Wait until all tasks are green
(about 1 minute).

**[evidence]** `03_bronze_graph.png`: Graph view of the successful run (extract → validate → persist,
the FIRMS branch mapped ×2).
**[evidence]** `04_bronze_log.png`: the log of one `persist` task showing `bronze written: ...`.

Check the files on disk:

```bash
ls datalake_bronze/          # firms_viirs_noaa20_nrt_*.json, firms_viirs_noaa21_nrt_*.json, open_meteo_forecast_*.json
```

## 3. First Silver run

`silver_processing` → **Trigger DAG**. The FileSensor finds the files, `find_new_files` reports them,
`process` writes the Parquet files.

**[evidence]** `05_silver_graph.png`: Graph view with `wait_for_bronze`, `find_new_files`, `process`,
`report` green.
**[evidence]** `06_silver_log.png`: the `report` task log (outputs and registry totals).

Trigger `silver_processing` once more right away: `find_new_files` returns False and the rest is
skipped (pink). **[evidence]** `07_silver_idempotent.png`: that run, which shows idempotency.

## 4. Second and third rounds (T + 1 h or more, T + 2 h or more)

Repeat steps 2 and 3 at least **two more times, each at least one hour after the previous one**. The
scheduler also runs `bronze_ingestion` by itself every 3 hours. If the scheduled run arrives first,
it counts as one of the rounds.

After the third round you must have:

* at least 3 files per FIRMS product and 3 forecast files in `datalake_bronze/` (≥ 3 required),
* at least 3 `fire_detections_*.parquet` and 3 `weather_hourly_*.parquet` in `datalake_silver/`
  (≥ 3 required). If a round brings no new fire rows, no fire file is written for it, so do another
  round later.

**[evidence]** `08_bronze_runs.png`: Grid view of `bronze_ingestion` with the green runs.
**[evidence]** `09_folders.png`: file explorer (or `ls -l`) of `datalake_bronze/` and `datalake_silver/`.

## 5. Poll comparison (closes the Workshop 1 open item)

```bash
python tools/compare_polls.py --latest firms_viirs_noaa20_nrt --markdown workshop_2/poll_comparison.md
python tools/compare_polls.py --latest firms_viirs_noaa21_nrt --markdown workshop_2/poll_comparison.md
python tools/compare_polls.py --latest open_meteo_forecast   --markdown workshop_2/poll_comparison.md
```

To compare the first and the last poll instead of the last two, pass the two file names explicitly.

## 6. Notebook

```bash
python -m pip install -r requirements.txt
jupyter nbconvert --to notebook --execute notebooks/02_silver_exploration.ipynb --inplace
```

**[evidence]** `10_notebook.png`: the checks cell with every line `OK`.

## 7. Tests and status

```bash
python -m pytest -q                     # expected: 19 passed
python ingest.py --mode status
```

**[evidence]** `11_pytest.png` and `12_status.png`.

## 8. Commit the outputs

The workshop asks for the sample outputs in the repository:

```bash
git add datalake_bronze/*.json datalake_silver/*.parquet datalake_silver/_quarantine/*.parquet \
        datalake_silver/_manifest.jsonl workshop_2/ notebooks/02_silver_exploration.ipynb
git commit -m "data(workshop2): bronze and silver outputs from three DAG rounds"
git push
```

Then send the screenshots and `workshop_2/poll_comparison.md` to whoever finishes the report, so the
real numbers go into the evidence section.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `extract_firms` fails with `FIRMS_MAP_KEY is not set` | `.env` missing or key not set; edit `.env`, then `docker compose up -d` again |
| `Invalid MAP_KEY` / HTTP 4xx in the log | wrong or expired key; request a new one at the FIRMS site |
| DAGs not listed | `docker compose logs airflow-scheduler`; an import error is printed there |
| Permission denied writing `datalake_*` (Linux) | set `AIRFLOW_UID` in `.env` to `id -u`, rerun `docker compose up airflow-init` |
| `wait_for_bronze` skipped | no JSON in `datalake_bronze/` yet; run `bronze_ingestion` first |
| Port 8080 or 5433 busy | stop the other program, or change the left side of the port mapping in `docker-compose.yml` |

## 9. Rebuild the report with the screenshots

Put the PNG files in `workshop_2/screenshots/` with the names above. The report picks them up
automatically (missing ones show as "Screenshot pending"):

```bash
cd workshop_2/report
pdflatex report.tex && pdflatex report.tex
cp report.pdf ../report.pdf
```

No LaTeX installed? Commit the screenshots and ask whoever has it (or Claude) to rebuild.
