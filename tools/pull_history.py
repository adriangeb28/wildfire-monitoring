"""Partitioned historical pull from the FIRMS area API (standard-processing data).

The area API serves at most 5 days per request, so a year is pulled as 73
windows. Every unmodified response is written under data/raw/ (git-ignored) and
recorded in a manifest, so a failed window can be retried without re-downloading.

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/pull_history.py 2024 VIIRS_NOAA20_SP
    python tools/pull_history.py 2024 VIIRS_NOAA20_SP VIIRS_SNPP_SP MODIS_SP
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "firms_history"
BBOX = "-79.0,-4.5,-66.5,13.5"
WINDOW_DAYS = 5
PAUSE_SECONDS = 1.0


def load_key() -> str:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("FIRMS_MAP_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def windows(year: int):
    start = date(year, 1, 1)
    while start.year == year:
        yield start
        start += timedelta(days=WINDOW_DAYS)


def pull(year: int, source: str, key: str, manifest: csv.writer) -> int:
    out_dir = RAW / str(year) / source
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for start in windows(year):
        target = out_dir / f"{start.isoformat()}.csv"
        if target.exists() and target.stat().st_size > 130:  # already have data
            total += target.stat().st_size
            manifest.writerow([year, source, start.isoformat(), "cached", target.name, target.stat().st_size])
            continue
        url = (
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{key}/{source}/{BBOX}/{WINDOW_DAYS}/{start.isoformat()}"
        )
        try:
            resp = requests.get(url, timeout=180)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {source} {start}: {exc}")
            manifest.writerow([year, source, start.isoformat(), f"error:{exc}", "", 0])
            continue
        target.write_text(resp.text, encoding="utf-8")
        rows = max(len(resp.text.strip().splitlines()) - 1, 0)
        total += rows
        manifest.writerow([year, source, start.isoformat(), "ok", target.name, rows])
        time.sleep(PAUSE_SECONDS)
    return total


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    year = int(argv[1])
    sources = argv[2:]
    key = load_key()
    if not key:
        print("Falta FIRMS_MAP_KEY en .env")
        return 1

    manifest_dir = RAW / str(year)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.csv"
    new_file = not manifest_path.exists()
    with manifest_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["year", "source", "window_start", "status", "file", "rows"])
        for source in sources:
            print(f"=== {source} {year} ===")
            rows = pull(year, source, key, writer)
            print(f"  total filas: {rows}")

    print(f"\nmanifiesto: {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
