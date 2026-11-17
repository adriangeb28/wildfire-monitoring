"""Wildfire monitoring pipeline: Bronze (raw JSON) -> Silver (processed Parquet).

Modules
-------
settings     paths and environment (works on the host and inside Docker)
sources      HTTP clients for FIRMS NRT and Open-Meteo, with retries
bronze       raw JSON envelopes: build, validate (basic schema check), persist
regions      point-in-polygon assignment to the 33 Colombian regions
preprocess   cleaning, typing, outliers, deduplication keys, schema enforcement
silver       state registry, new-file detection, Parquet persistence with lineage

The Airflow DAGs in airflow/dags/ and the command-line entry point ingest.py
call these functions; no pipeline logic lives inside the DAG files.
"""
