"""Gold processing DAG: Silver Parquet -> PySpark KPIs & Storytelling -> datalake_gold/."""

from __future__ import annotations

import sys
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task

sys.path.insert(0, "/opt/airflow/src")

DEFAULT_ARGS = {
    "owner": "team3-wildfire",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="gold_processing",
    description="Silver Parquet -> PySpark Governance & Storytelling Parquet in datalake_gold/",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 11, 16, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["wildfire", "gold", "pyspark", "workshop3"],
)
def gold_processing():

    @task
    def validate_silver_inputs() -> dict:
        from pipeline.gold import _resolve_datalake_dirs

        silver, _ = _resolve_datalake_dirs()
        fires = sorted(silver.glob("fire_detections_*.parquet"))
        weather = sorted(silver.glob("weather_hourly_*.parquet"))
        if not fires or not weather:
            raise FileNotFoundError(f"Missing Silver Parquet inputs in {silver} for Gold processing.")
        return {"fire_files": len(fires), "weather_files": len(weather)}

    @task
    def run_pyspark_gold(inputs: dict) -> dict:
        import pendulum as _p
        from pipeline import gold

        print(f"[gold] Consolidating {inputs['fire_files']} fire and {inputs['weather_files']} weather partitions...")
        return gold.run_gold_pipeline(run_ts=_p.now("UTC"))

    @task
    def verify_gold_outputs(summary: dict) -> dict:
        import pandas as pd
        from pipeline.gold import _resolve_datalake_dirs

        _, gold_dir = _resolve_datalake_dirs()
        gov_path = gold_dir / summary["governance_file"]
        story_path = gold_dir / summary["storytelling_file"]

        gov_df = pd.read_parquet(gov_path)
        story_df = pd.read_parquet(story_path)
        assert len(gov_df) > 0, "Governance Gold file is empty"
        assert len(story_df) > 0, "Storytelling Gold file is empty"
        print(f"[verify] {gov_path.name}: {len(gov_df)} rows, {len(gov_df.columns)} cols")
        print(f"[verify] {story_path.name}: {len(story_df)} rows, {len(story_df.columns)} cols")
        return summary

    inputs = validate_silver_inputs()
    summary = run_pyspark_gold(inputs)
    verify_gold_outputs(summary)


gold_processing()