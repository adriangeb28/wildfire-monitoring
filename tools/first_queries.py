"""First real queries to the four sources — Workshop 1 evidence collector.

Saves the UNMODIFIED responses under workshop_1/samples/ together with the HTTP
headers (ETag / Last-Modified are part of the incremental-source evidence).

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/first_queries.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "workshop_1" / "samples"
BBOX = "-79.0,-4.5,-66.5,13.5"          # Colombia: west,south,east,north
BOGOTA = (4.7110, -74.0721)             # lat, lon


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip()
    return values


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save(name: str, text: str) -> Path:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    path = SAMPLES / name
    path.write_text(text, encoding="utf-8")
    return path


def save_headers(name: str, response: requests.Response) -> Path:
    keep = ("Date", "Content-Type", "ETag", "Last-Modified", "Age", "Cache-Control")
    lines = [f"{k}: {response.headers[k]}" for k in keep if k in response.headers]
    return save(name, "\n".join(lines) + "\n")


def firms(source: str, map_key: str, day_range: int = 1) -> None:
    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{map_key}/{source}/{BBOX}/{day_range}"
    )
    ts = stamp()
    print(f"\n=== FIRMS {source} (day_range={day_range}) ===")
    if not map_key:
        print("  SKIP: no MAP_KEY in .env")
        return
    try:
        resp = requests.get(url, timeout=120)
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR de red: {exc}")
        return

    body = resp.text
    path = save(f"firms_{source}_{ts}.csv", body)
    save_headers(f"firms_{source}_{ts}_headers.txt", resp)

    head = body.splitlines()[0] if body.strip() else "(respuesta vacia)"
    rows = max(len(body.strip().splitlines()) - 1, 0) if body.strip() else 0
    print(f"  HTTP {resp.status_code} | {rows} filas | {len(body)} bytes")
    print(f"  guardado: workshop_1/samples/{path.name}")
    if rows == 0:
        print(f"  primera linea: {head[:160]}")
    else:
        print(f"  columnas: {head}")
        for line in body.strip().splitlines()[1:4]:
            print(f"    {line[:150]}")


def open_meteo_historical() -> None:
    lat, lon = BOGOTA
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": "2024-01-01",
        "end_date": "2024-01-10",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,vapour_pressure_deficit",
        "timezone": "UTC",
        "models": "era5",
    }
    ts = stamp()
    print("\n=== OPEN-METEO Historical (ERA5, Bogota, 2024-01-01..10) ===")
    try:
        resp = requests.get(url, params=params, timeout=120)
        save(f"openmeteo_historical_era5_bogota_{ts}.json", resp.text)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {exc}")
        return
    hourly = data.get("hourly", {})
    n = len(hourly.get("time", []))
    print(f"  HTTP {resp.status_code} | {n} horas | zona: {data.get('timezone')}")
    print(f"  primera hora: {hourly.get('time', [''])[0]}")
    for var in ("temperature_2m", "precipitation", "vapour_pressure_deficit"):
        series = hourly.get(var, [])
        if series:
            valid = [v for v in series if v is not None]
            print(f"  {var:<24} min={min(valid):>8.2f} max={max(valid):>8.2f} nulos={len(series)-len(valid)}")


def open_meteo_forecast() -> None:
    lat, lon = BOGOTA
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "past_days": 2,
        "forecast_days": 2,
        "timezone": "UTC",
    }
    ts = stamp()
    print("\n=== OPEN-METEO Forecast (Bogota, past_days=2) ===")
    try:
        resp = requests.get(url, params=params, timeout=120)
        save(f"openmeteo_forecast_bogota_{ts}.json", resp.text)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {exc}")
        return
    hourly = data.get("hourly", {})
    n = len(hourly.get("time", []))
    print(f"  HTTP {resp.status_code} | {n} horas | zona: {data.get('timezone')}")
    print(f"  primera hora: {hourly.get('time', [''])[0]}  ultima: {hourly.get('time', [''])[-1]}")


def main() -> int:
    env = load_env()
    key = env.get("FIRMS_MAP_KEY", "")
    print(f"MAP_KEY presente: {'si' if key else 'no'} ({len(key)} caracteres)")
    print(f"BBOX Colombia   : {BBOX}")

    firms("VIIRS_NOAA20_NRT", key, 1)
    firms("VIIRS_NOAA21_NRT", key, 1)
    firms("VIIRS_SNPP_NRT", key, 1)   # expected dead since 2026-11-02
    open_meteo_historical()
    open_meteo_forecast()

    print("\nListo. Respuestas crudas en workshop_1/samples/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
