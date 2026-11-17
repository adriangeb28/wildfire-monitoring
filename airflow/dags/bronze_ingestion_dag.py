"""Bronze ingestion DAG: FIRMS NRT (VIIRS NOAA-20, NOAA-21) + Open-Meteo forecast.

Schedule: every 3 hours, the polling frequency fixed in the Workshop 1
ingestion contract (FIRMS NRT latency is about 3 h after the overpass).

Tasks (TaskFlow API)
--------------------
extract_firms (mapped over the two VIIRS products)  ->  validate  ->  persist
extract_open_meteo                                  ->  validate  ->  persist

Each persisted file is ``datalake_bronze/<source>_YYYYMMDD_HHMMSS.json`` where
the timestamp is the run's ``logical_date`` (UTC). Clearing and re-running a
run keeps its logical date, so it rewrites the same file and never adds a
second one (idempotency). Manual triggers get their own logical date, which is
how several Bronze files can be produced for the evidence without waiting
for the 3-hour schedule.
"""

from __future__ import annotations

import sys
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task

sys.path.insert(0, "/opt/airflow/src")  # project package, mounted by docker-compose

DEFAULT_ARGS = {
    "owner": "team3-wildfire",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}


@dag(
    dag_id="bronze_ingestion",
    description="FIRMS NRT + Open-Meteo forecast -> raw JSON in datalake_bronze/",
    schedule="0 */3 * * *",
    start_date=pendulum.datetime(2026, 11, 16, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["wildfire", "bronze", "workshop2"],
)
def bronze_ingestion():

    @task
    def extract_firms(product: str, data_interval_end=None) -> dict:
        """Call the FIRMS area API for one VIIRS product, 2-day window ending at the run."""
        from pipeline import settings, sources

        end = data_interval_end.date()
        start = end - timedelta(days=settings.FIRMS_DAY_RANGE - 1)
        result = sources.fetch_firms_nrt(product, settings.FIRMS_DAY_RANGE, start)
        return result.__dict__

    @task
    def extract_open_meteo() -> dict:
        """One Open-Meteo forecast call for the 33 region centroids (UTC)."""
        from pipeline import sources

        return sources.fetch_open_meteo_forecast().__dict__

    @task
    def validate(raw: dict) -> dict:
        """Basic schema check. A failed check is persisted too (with ok=false) so it is auditable,
        but it raises afterwards so the run is visibly red."""
        from pipeline import bronze
        from pipeline.sources import FetchResult

        report = bronze.validate_payload(FetchResult(**raw))
        if report["problems"]:
            print(f"[validate] {raw['source']}/{raw['product']}: {report['problems']}")
        return {"raw": raw, "validation": report}

    @task
    def persist(checked: dict, logical_date=None) -> str:
        from pipeline import bronze
        from pipeline.sources import FetchResult

        result = FetchResult(**checked["raw"])
        run_ts = logical_date
        envelope = bronze.build_envelope(result, run_ts, checked["validation"])
        path = bronze.write_bronze(envelope, bronze.bronze_name(result), run_ts)
        if not checked["validation"]["ok"]:
            raise ValueError(f"{path.name} failed the schema check: {checked['validation']['problems']}")
        return str(path)

    firms_raw = extract_firms.expand(product=["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"])
    persist.expand(checked=validate.expand(raw=firms_raw))
    persist.override(task_id="persist_open_meteo")(
        validate.override(task_id="validate_open_meteo")(extract_open_meteo())
    )


bronze_ingestion()
