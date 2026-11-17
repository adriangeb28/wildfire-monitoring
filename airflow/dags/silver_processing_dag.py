"""Silver processing DAG: FileSensor on datalake_bronze/ -> preprocessing -> Parquet.

Flow (TaskFlow API + FileSensor)
--------------------------------
wait_for_bronze  FileSensor on datalake_bronze/*.json (connection ``fs_bronze``,
                 defined in docker-compose.yml). Mode ``reschedule`` frees the
                 worker slot between pokes.
find_new_files   short-circuit: compares the folder with the Silver state
                 registry. The sensor answers "is there Bronze data?", the
                 registry answers "is any of it new?". If nothing is new the
                 rest of the run is skipped (green, no output).
process          preprocessing + Parquet persistence (src/pipeline/silver.py):
                 datalake_silver/fire_detections_YYYYMMDD_HHMMSS.parquet
                 datalake_silver/weather_hourly_YYYYMMDD_HHMMSS.parquet
                 datalake_silver/_quarantine/rejected_YYYYMMDD_HHMMSS.parquet
report           logs the run summary and the registry totals.

Sensor timing: Bronze lands every 3 h, so the sensor pokes every 2 min
(poke_interval=120 s) and gives up after 3 h (timeout), one Bronze period. With
soft_fail=True a run that sees no Bronze file at all ends as *skipped*, not
failed. The DAG itself is scheduled every 30 min, so new Bronze files are
picked up at most ~30 min after they land.
"""

from __future__ import annotations

import sys
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.sensors.filesystem import FileSensor

sys.path.insert(0, "/opt/airflow/src")

DEFAULT_ARGS = {
    "owner": "team3-wildfire",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="silver_processing",
    description="New Bronze JSON -> cleaned, validated, deduplicated Parquet in datalake_silver/",
    schedule="*/30 * * * *",
    start_date=pendulum.datetime(2026, 11, 16, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["wildfire", "silver", "workshop2"],
)
def silver_processing():

    wait_for_bronze = FileSensor(
        task_id="wait_for_bronze",
        fs_conn_id="fs_bronze",
        filepath="*.json",
        poke_interval=120,
        timeout=3 * 60 * 60,
        mode="reschedule",
        soft_fail=True,
    )

    @task.short_circuit
    def find_new_files() -> bool:
        from contextlib import closing

        from pipeline import silver

        with closing(silver.connect()) as con:
            pending = silver.pending_bronze_files(con)
        print(f"[find_new_files] {len(pending)} new bronze file(s): {[p.name for p in pending]}")
        return bool(pending)

    @task
    def process() -> dict:
        import pendulum as _p

        from pipeline import silver

        # processing-run timestamp in the file names = wall clock of this run (UTC)
        summary = silver.process_pending(run_ts=_p.now("UTC"))
        if summary["status"] != "committed":
            raise RuntimeError(f"silver run did not commit: {summary}")
        return summary

    @task
    def report(summary: dict) -> dict:
        from pipeline import silver

        totals = silver.status()
        print("[report] outputs :", summary["outputs"])
        print("[report] registry:", totals)
        return totals

    summary = process()
    wait_for_bronze >> find_new_files() >> summary
    report(summary)


silver_processing()
