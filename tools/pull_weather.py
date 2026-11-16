"""Pull Open-Meteo weather for the 33 region centroids and build a daily panel.

Design: one request per month with all 33 coordinates (so ~106 requests for
2018-2026, far below the free-tier limits), hourly variables, immediately
aggregated to the daily panel the indicator needs. The first month's unmodified
JSON is kept as raw evidence; the rest are reduced and not stored hourly.

Daily panel columns (one row per region-day):
    temp_max_c, temp_min_c, rh_min_pct, precip_mm, wind_max_kmh, vpd_max_kpa

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/pull_weather.py --mode historical --start 2018-01-01 --end 2026-11-01
    python tools/pull_weather.py --mode forecast --past-days 7
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CENTROIDS = ROOT / "workshop_1" / "samples" / "regions_centroids.csv"
RAW = ROOT / "data" / "raw" / "openmeteo"
PANEL = RAW / "daily_panel.csv"
PANEL_FIELDS = [
    "region_id", "name", "date",
    "temp_max_c", "temp_min_c", "rh_min_pct", "precip_mm", "wind_max_kmh", "vpd_max_kpa",
]

HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "vapour_pressure_deficit"]
FORECAST_HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]


def centroids() -> list[dict]:
    with CENTROIDS.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1).toordinal() - 1
        yield max(first, start), min(date.fromordinal(last), end)
        month += 1
        if month == 13:
            month, year = 1, year + 1


def daily_rows(block: dict, region: dict) -> list[dict]:
    """Aggregate one region's hourly series into daily rows."""
    hourly = block.get("hourly", {})
    times = hourly.get("time", [])
    acc: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for i, stamp in enumerate(times):
        day = stamp[:10]
        for var in HOURLY:
            series = hourly.get(var)
            if series and i < len(series) and series[i] is not None:
                acc[day][var].append(series[i])

    rows = []
    for day in sorted(acc):
        values = acc[day]
        temp = values.get("temperature_2m", [])
        rh = values.get("relative_humidity_2m", [])
        precip = values.get("precipitation", [])
        wind = values.get("wind_speed_10m", [])
        vpd = values.get("vapour_pressure_deficit", [])
        rows.append(
            {
                "region_id": region["region_id"],
                "name": region["name"],
                "date": day,
                "temp_max_c": round(max(temp), 2) if temp else "",
                "temp_min_c": round(min(temp), 2) if temp else "",
                "rh_min_pct": round(min(rh), 1) if rh else "",
                "precip_mm": round(sum(precip), 2) if precip else "",
                "wind_max_kmh": round(max(wind), 1) if wind else "",
                "vpd_max_kpa": round(max(vpd), 2) if vpd else "",
            }
        )
    return rows


def append_panel(rows: list[dict]) -> None:
    if not rows:
        return
    new_file = not PANEL.exists()
    with PANEL.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PANEL_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def existing_days() -> set[tuple[str, str]]:
    if not PANEL.exists():
        return set()
    with PANEL.open(encoding="utf-8") as fh:
        return {(row["region_id"], row["date"]) for row in csv.DictReader(fh)}


def call(url: str, params: dict, attempts: int = 4) -> dict | list:
    """GET with exponential backoff; Open-Meteo resets long connections."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=300)
            resp.raise_for_status()
            return json.loads(resp.text)
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 5 * (2**attempt)
            print(f"    reintento {attempt + 1}/{attempts} en {wait}s ({type(exc).__name__})")
            time.sleep(wait)
    raise RuntimeError(f"fallo tras {attempts} intentos: {last}")


def in_batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def pull_historical(start: date, end: date, model: str, batch_size: int = 11) -> None:
    regions = centroids()
    RAW.mkdir(parents=True, exist_ok=True)
    done_dir = RAW / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    kept_evidence = any(RAW.glob("evidence_era5_*.json"))
    total = 0
    for first, last in months(start, end):
        marker = done_dir / f"{first.isoformat()}..{last.isoformat()}.done"
        if marker.exists():
            print(f"{first.isoformat()}..{last.isoformat()}: ya completado")
            continue
        rows: list[dict] = []
        evidence_written = False
        for batch in in_batches(regions, batch_size):
            params = {
                "latitude": ",".join(r["lat"] for r in batch),
                "longitude": ",".join(r["lon"] for r in batch),
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                "hourly": ",".join(HOURLY),
                "timezone": "UTC",
                "models": model,
            }
            payload = call("https://archive-api.open-meteo.com/v1/archive", params)
            blocks = payload if isinstance(payload, list) else [payload]
            if not kept_evidence and not evidence_written:
                (RAW / f"evidence_era5_{first.isoformat()}.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                evidence_written = True
            for region, block in zip(batch, blocks):
                rows.extend(daily_rows(block, region))
            time.sleep(1.0)
        append_panel(rows)
        marker.write_text("ok", encoding="utf-8")
        total += len(rows)
        print(f"{first.isoformat()}..{last.isoformat()}: {len(rows)} region-dias")
    print(f"\npanel: {PANEL.relative_to(ROOT)} ({total} filas nuevas)")


def pull_forecast(past_days: int, forecast_days: int) -> None:
    regions = centroids()
    params = {
        "latitude": ",".join(r["lat"] for r in regions),
        "longitude": ",".join(r["lon"] for r in regions),
        "hourly": ",".join(FORECAST_HOURLY),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }
    payload = call("https://api.open-meteo.com/v1/forecast", params)
    blocks = payload if isinstance(payload, list) else [payload]
    out_dir = RAW / "forecast"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"forecast_{ts}.json").write_text(json.dumps(payload), encoding="utf-8")
    rows = []
    for region, block in zip(regions, blocks):
        rows.extend(daily_rows(block, region))
    path = out_dir / f"forecast_{ts}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"forecast: {len(rows)} region-dias -> {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["historical", "forecast"], required=True)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--model", default="era5")
    parser.add_argument("--past-days", type=int, default=7)
    parser.add_argument("--forecast-days", type=int, default=7)
    args = parser.parse_args()

    if args.mode == "historical":
        pull_historical(date.fromisoformat(args.start), date.fromisoformat(args.end), args.model)
    else:
        pull_forecast(args.past_days, args.forecast_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
