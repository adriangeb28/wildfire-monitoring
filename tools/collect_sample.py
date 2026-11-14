"""Collect and profile a real Colombia sample from FIRMS NRT.

Saves the unmodified CSVs under workshop_1/samples/ and prints a first profile:
volumes, date span, FRP statistics, confidence mix and duplicate pressure.

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/collect_sample.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "workshop_1" / "samples"
BBOX = "-79.0,-4.5,-66.5,13.5"
DAY_RANGE = 5
SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip()
    return values


def fetch(source: str, key: str) -> Path:
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{BBOX}/{DAY_RANGE}"
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SAMPLES / f"firms_{source}_colombia_{DAY_RANGE}d_{ts}.csv"
    path.write_text(resp.text, encoding="utf-8")
    print(f"{source:<20} HTTP {resp.status_code} -> {path.name} ({len(resp.text)//1024} KB)")
    return path


def profile(paths: list[Path]) -> None:
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        df["source_file"] = path.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    print(f"\n=== PERFIL DE LA MUESTRA ({len(df)} detecciones) ===")
    print(f"columnas           : {list(df.columns[:14])}")
    print(f"rango de fechas    : {df['acq_date'].min()} -> {df['acq_date'].max()}")
    print(f"por sensor         : {df.groupby('satellite').size().to_dict()}")
    print(f"FRP (MW)           : min={df.frp.min():.2f}  media={df.frp.mean():.2f}  max={df.frp.max():.2f}  nulos={df.frp.isna().sum()}")
    print(f"confianza (VIIRS)  : {df.confidence.value_counts().to_dict()}")
    print(f"dia/noche          : {df.daynight.value_counts().to_dict()}")

    dup = df.duplicated(subset=["latitude", "longitude", "acq_date", "acq_time", "satellite"]).sum()
    near = df.duplicated(subset=["latitude", "longitude", "acq_date"]).sum()
    print(f"duplicados exactos : {dup}")
    print(f"misma celda/dia    : {near}  ({near / len(df):.1%} de las filas)")

    outside = (~df.latitude.between(-4.5, 13.5)) | (~df.longitude.between(-79.0, -66.5))
    print(f"fuera del bbox     : {int(outside.sum())}")
    print(f"confianza nula/MO  : {df.confidence.isna().sum()}")
    print(f"bright_ti4 nulos   : {df.bright_ti4.isna().sum()}")

    out = SAMPLES / "colombia_sample_profile.csv"
    df.head(200).to_csv(out, index=False)
    print(f"\nprimeras 200 filas -> {out.name}")


def main() -> int:
    key = load_env().get("FIRMS_MAP_KEY", "")
    if not key:
        print("Falta FIRMS_MAP_KEY en .env")
        return 1
    paths = [fetch(source, key) for source in SOURCES]
    profile(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
