"""ingest.py - command-line entry point of the wildfire pipeline (course contract).

    python ingest.py --mode historical [--start 2024-01-01 --end 2024-01-31] [--product VIIRS_NOAA20_SP]
    python ingest.py --mode incremental
    python ingest.py --mode incremental --from-fixtures     # offline: replay recorded responses
    python ingest.py --mode status

The Airflow DAGs (airflow/dags/) call the same functions; this entry point is
for manual runs, the historical bulk load and the live demonstration.

historical   FIRMS standard-processing archive through the area API, in 5-day
             windows (the API maximum). Each window becomes one Bronze file named
             after the window start, so re-running a range rewrites the same
             files and Silver ignores what it already processed (idempotent).
incremental  One poll of F3 (VIIRS NOAA-20 and NOAA-21 NRT, 2-day window) and
             F4 (Open-Meteo forecast), then Silver processing of new files.
status       Bronze file counts and the Silver registry (files, rows, keys, last run).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pipeline import bronze, settings, silver, sources  # noqa: E402

log = settings.get_logger("ingest")
ARCHIVE_PRODUCTS = ("VIIRS_NOAA20_SP", "VIIRS_SNPP_SP")
WINDOW_DAYS = 5


def persist(result: sources.FetchResult, run_ts: datetime) -> Path:
    validation = bronze.validate_payload(result)
    envelope = bronze.build_envelope(result, run_ts, validation)
    path = bronze.write_bronze(envelope, bronze.bronze_name(result), run_ts)
    if not validation["ok"]:
        log.error("%s failed the schema check: %s", path.name, validation["problems"])
    return path


def run_historical(start: date, end: date, products: list[str]) -> int:
    settings.ensure_dirs()
    for product in products:
        cursor = start
        while cursor <= end:
            days = min(WINDOW_DAYS, (end - cursor).days + 1)
            run_ts = datetime(cursor.year, cursor.month, cursor.day, tzinfo=timezone.utc)
            name = f"firms_{product.lower()}_{run_ts:%Y%m%d_%H%M%S}.json"
            if (settings.BRONZE_DIR / name).exists():
                log.info("cached: %s", name)
            else:
                persist(sources.fetch_firms_nrt(product, days, cursor, source="firms_archive"), run_ts)
                time.sleep(1.0)  # be polite: far below 5000 transactions / 10 min
            cursor += timedelta(days=days)
    summary = silver.process_pending()
    print(json.dumps(summary["outputs"], indent=2, default=str))
    return 0


def run_incremental(from_fixtures: bool) -> int:
    settings.ensure_dirs()
    run_ts = datetime.now(timezone.utc).replace(microsecond=0)
    if from_fixtures:
        fixtures = sorted((ROOT / "tests" / "fixtures").glob("*.json"))
        for path in fixtures:
            target = settings.BRONZE_DIR / path.name
            if not target.exists():
                shutil.copy(path, target)
                log.info("replayed recorded response %s", path.name)
    else:
        for product in settings.FIRMS_PRODUCTS:
            start = run_ts.date() - timedelta(days=settings.FIRMS_DAY_RANGE - 1)
            persist(sources.fetch_firms_nrt(product, settings.FIRMS_DAY_RANGE, start), run_ts)
        persist(sources.fetch_open_meteo_forecast(), run_ts)
    summary = silver.process_pending()
    print(json.dumps({"status": summary["status"], "outputs": summary["outputs"]}, indent=2, default=str))
    return 0


def run_status() -> int:
    settings.ensure_dirs()
    bronze_files = sorted(settings.BRONZE_DIR.glob("*.json"))
    by_source: dict[str, int] = {}
    for path in bronze_files:
        prefix = path.name.rsplit("_", 2)[0]
        by_source[prefix] = by_source.get(prefix, 0) + 1
    report = {"bronze_files": by_source, "silver": silver.status(),
              "latest_bronze": bronze_files[-1].name if bronze_files else None}
    print(json.dumps(report, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest", description="Wildfire monitoring ingestion")
    parser.add_argument("--mode", choices=["historical", "incremental", "status"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, help="historical: first day (UTC)")
    parser.add_argument("--end", type=date.fromisoformat, help="historical: last day (UTC)")
    parser.add_argument("--product", action="append", choices=ARCHIVE_PRODUCTS,
                        help="historical: FIRMS SP product(s); default VIIRS_NOAA20_SP")
    parser.add_argument("--from-fixtures", action="store_true",
                        help="incremental: replay tests/fixtures instead of calling the APIs")
    args = parser.parse_args(argv)

    if args.mode == "historical":
        start = args.start or date(2024, 1, 1)
        end = args.end or (start + timedelta(days=WINDOW_DAYS * 6 - 1))
        return run_historical(start, end, args.product or ["VIIRS_NOAA20_SP"])
    if args.mode == "incremental":
        return run_incremental(args.from_fixtures)
    return run_status()


if __name__ == "__main__":
    raise SystemExit(main())
