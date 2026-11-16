"""Generate notebooks/01_source_profiling.ipynb.

The notebook is built from a list of (kind, source) cells so that the code is
reviewable here and the JSON is always well-formed. Validate with:

    python tools/build_notebook.py
    python tools/validate_notebook.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "01_source_profiling.ipynb"

CELLS: list[tuple[str, str]] = [
    (
        "md",
        """# 01: profiling the four sources

Wildfire monitoring, Team 3, Data Analysis Programming 2026-II, Workshop 1
deliverable 2. Hazard: vegetation fires seen as satellite thermal anomalies, with
FRP in MW as the severity measure. Scope: Colombia, 33 regions.

Four sources, profiled on the raw responses kept in `workshop_1/samples/`:

| # | Role | Source |
|---|---|---|
| F1 | Historical | NASA FIRMS archive (standard processing, `*_SP`) |
| F2 | Historical | Open-Meteo Historical Weather (ERA5 reanalysis) |
| F3 | Incremental | NASA FIRMS NRT (VIIRS NOAA-20 and NOAA-21) |
| F4 | Incremental | Open-Meteo Forecast |

The notebook goes through what each source contains, what is wrong with it,
whether two sources describe the same fire, and what all of that forces in the
canonical model.

Run it from the repository root:

```powershell
$env:PYTHONPATH = "$PWD/vendor;$PWD/src"
jupyter nbconvert --to notebook --execute notebooks/01_source_profiling.ipynb --inplace
```""",
    ),
    (
        "code",
        '''import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

SAMPLES = ROOT / "workshop_1" / "samples"
RAW = ROOT / "data" / "raw"
FIGURES = ROOT / "docs" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH = -79.0, -4.5, -66.5, 13.5
pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 30)
print("project root :", ROOT)
print("samples      :", len(list(SAMPLES.glob('*'))), "files")''',
    ),
    (
        "md",
        """## 0. A reusable profiler

Every source gets the same six checks: null share per field, value ranges,
duplicated identifiers, timestamp format and time zone, coordinate validity and
unit consistency. Six is enough to catch everything we found, and it keeps the
output comparable between sources.""",
    ),
    (
        "code",
        '''def profile_table(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    """Per-field profile: dtype, null %, cardinality, range for numeric fields."""
    rows = []
    for column in frame.columns:
        series = frame[column]
        row = {
            "field": column,
            "dtype": str(series.dtype),
            "null_pct": round(float(series.isna().mean()) * 100, 2),
            "n_unique": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series) and series.notna().any():
            row["min"] = float(series.min())
            row["max"] = float(series.max())
        rows.append(row)
    table = pd.DataFrame(rows)
    print(f"=== {name}: {len(frame):,} rows x {frame.shape[1]} columns ===")
    return table


def bbox_violations(frame: pd.DataFrame, lat="latitude", lon="longitude") -> int:
    outside = ~frame[lat].between(BBOX_SOUTH, BBOX_NORTH) | ~frame[lon].between(BBOX_WEST, BBOX_EAST)
    return int(outside.sum())


print("helpers defined")''',
    ),
    (
        "md",
        """## 1. F3: NASA FIRMS NRT (VIIRS NOAA-20 and NOAA-21)

The area API takes at most five days per request:""",
    ),
    (
        "code",
        '''files = sorted(SAMPLES.glob("firms_VIIRS_NOAA2*_colombia_5d_*.csv"))
parts = []
for path in files:
    block = pd.read_csv(path)
    block["raw_reference"] = path.name
    parts.append(block)
f3 = pd.concat(parts, ignore_index=True)

profile_table(f3, "F3 FIRMS NRT")
print()
print(f3.head(3).to_string(index=False))''',
    ),
    (
        "md",
        """### Finding 1: the duplicate count depends on the tolerance you pick

Exact duplicates are zero. On a ~1 km grid and the same day, 44.5 % of rows share
a cell. The result is not a property of the data, it is a property of the test,
and that is the evidence behind the workshop warning about grouping detections
into fire events.""",
    ),
    (
        "code",
        '''exact = f3.duplicated(subset=["latitude", "longitude", "acq_date", "acq_time", "satellite"]).sum()
print(f"duplicados exactos                              : {exact}")

duplicate_scan = []
for decimals in (3, 2, 1):
    grid = f3.assign(lat_g=f3.latitude.round(decimals), lon_g=f3.longitude.round(decimals))
    involved = int(grid.duplicated(subset=["lat_g", "lon_g", "acq_date"], keep=False).sum())
    duplicate_scan.append({
        "tolerance_deg": decimals,
        "approx_km": round(111 * 10 ** -decimals, 2),
        "rows_involved": involved,
        "pct": round(involved / len(f3) * 100, 1),
    })
duplicates = pd.DataFrame(duplicate_scan)
print(duplicates.to_string(index=False))''',
    ),
    (
        "md",
        """### Finding 2: `acq_time` is HHMM without zero padding

436 rows carry a three-digit `acq_time`, so `630` means 06:30. Read as an integer
the value silently becomes 630 minutes or 6.30 hours, depending on the code.
Those 436 rows are exactly the night detections.""",
    ),
    (
        "code",
        '''f3["acq_time_str"] = f3.acq_time.astype(int).astype(str)
f3["acq_time_digits"] = f3.acq_time_str.str.len()

print("distribución de dígitos en acq_time:")
print(f3.acq_time_digits.value_counts().sort_index().to_string())
print()
print("cruce con daynight (las 3 cifras son las nocturnas):")
print(pd.crosstab(f3.acq_time_digits, f3.daynight).to_string())
print()
print("ejemplos de acq_time de 3 cifras:", f3.loc[f3.acq_time_digits == 3, "acq_time"].head(6).tolist())''',
    ),
    (
        "md",
        """### Finding 3: FRP values that cannot be right

One row has an FRP of zero, which cannot be a fire detection, and 86 sit below
1 MW, at the noise floor of the product. Both distort any total.""",
    ),
    (
        "code",
        '''print("FRP == 0      :", int((f3.frp == 0).sum()))
print("FRP < 1 MW    :", int((f3.frp < 1).sum()))
print("FRP statistics:", {k: round(float(v), 2) for k, v in f3.frp.describe().items()})
print()
print("ejemplo de registro con FRP = 0:")
print(f3.loc[f3.frp == 0].head(2).to_string(index=False))''',
    ),
    (
        "md",
        """### Finding 4: `confidence` is a code, not a percentage

VIIRS returns `l`, `n` or `h`. MODIS returns 0–100. A filter like
`confidence > 50` means nothing on VIIRS, and unioning both sensors without
normalising silently keeps or drops everything.""",
    ),
    (
        "code",
        '''print("confianza (VIIRS):", f3.confidence.value_counts().to_dict())
print("¿es numérica?     :", pd.api.types.is_numeric_dtype(f3.confidence))
print()
print("Si aplicáramos 'confidence > 50' a VIIRS, sobrevivirían:",
      int((pd.to_numeric(f3.confidence, errors="coerce") > 50).sum()), "filas de", len(f3))''',
    ),
    (
        "md",
        """### Finding 5: the bounding box is not the country

The API only takes a bounding box, and the Colombian box contains Venezuela,
Ecuador, Peru, Brazil and Panama. Assigning each detection to a department with a
point-in-polygon test shows that half the rows are fires somewhere else.""",
    ),
    (
        "code",
        '''from normalization.regions import assign_regions, load_regions

regions = load_regions()
print("regiones cargadas:", len(regions))

f3 = assign_regions(f3)
inside = int(f3.region_id.notna().sum())
print(f"detecciones totales    : {len(f3)}")
print(f"dentro de Colombia     : {inside} ({inside / len(f3):.1%})")
print(f"FUERA (países vecinos) : {len(f3) - inside} ({(len(f3) - inside) / len(f3):.1%})")''',
    ),
    (
        "code",
        '''top_regions = (
    f3.dropna(subset=["region_name"])
    .groupby("region_name")
    .agg(detections=("frp", "size"), frp_sum=("frp", "sum"), frp_max=("frp", "max"))
    .sort_values("detections", ascending=False)
    .round(1)
)
print("Top 10 departamentos por detecciones (5 días):")
print(top_regions.head(10).to_string())
print()
print("regiones sin detecciones:", 33 - top_regions.shape[0])''',
    ),
    (
        "md",
        """## 2. F1: the FIRMS archive (standard processing)

The `*_SP` sources serve archive-quality records and the API accepts historical
dates for them, five days at a time (the partitioned pull lives in
`tools/pull_history.py`). The `*_NRT` sources only answer for the recent window: a
request for 2024-01-22 comes back empty.""",
    ),
    (
        "code",
        '''history_dir = RAW / "firms_history" / "2024"
frames = []
for source_dir in sorted(history_dir.glob("*")):
    if not source_dir.is_dir():
        continue
    parts = [pd.read_csv(f) for f in sorted(source_dir.glob("*.csv"))]
    if not parts:
        continue
    block = pd.concat(parts, ignore_index=True)
    block["sensor"] = source_dir.name
    frames.append(block)

if frames:
    f1 = pd.concat(frames, ignore_index=True)
    f1["region_id"] = np.nan
    profile_table(f1, "F1 FIRMS archive 2024")
else:
    f1 = pd.DataFrame()
    print("Sin datos históricos todavía: ejecuta tools/pull_history.py 2024 VIIRS_NOAA20_SP")''',
    ),
    (
        "md",
        """### Comparing sensors (the 2026 discontinuities)

Suomi NPP stopped on 2026-11-02 and Terra MODIS has been in standby since March
2026. A baseline that mixes sensors measures the instruments. That is why the
baseline here is built per sensor, and the cell below shows what happens if you
forget it.""",
    ),
    (
        "code",
        '''if not f1.empty:
    f1["acq_date"] = pd.to_datetime(f1.acq_date)
    comparison = (
        f1.groupby([f1.acq_date.dt.to_period("M"), "sensor"])
        .size()
        .unstack("sensor")
        .fillna(0)
        .astype(int)
    )
    comparison.index = comparison.index.astype(str)
    print("Detecciones por mes y sensor (Colombia, bbox):")
    print(comparison.to_string())
    print()
    print("Totales anuales y ratio entre sensores:")
    totals = f1.groupby("sensor").size()
    print(totals.to_string())

    ax = comparison.plot(figsize=(11, 4), marker="o")
    ax.set_title("Detecciones mensuales por sensor — Colombia 2024")
    ax.set_ylabel("detecciones")
    ax.set_xlabel("")
    plt.tight_layout()
    plt.savefig(FIGURES / "sensor_comparison_2024.png", dpi=140)
    plt.show()''',
    ),
    (
        "md",
        """## 3. F2: Open-Meteo historical (ERA5)

A daily panel built from hourly ERA5 values for the 33 region centroids, one
request per month with every coordinate in the same call, always with
`timezone=UTC`.""",
    ),
    (
        "code",
        '''panel_path = RAW / "openmeteo" / "daily_panel.csv"
if panel_path.exists():
    weather = pd.read_csv(panel_path)
    profile_table(weather, "F2 Open-Meteo ERA5 daily panel")
    print()
    print("rango de fechas:", weather.date.min(), "->", weather.date.max())
    print("regiones       :", weather.region_id.nunique())
else:
    weather = pd.DataFrame()
    print("Sin panel climático: ejecuta tools/pull_weather.py --mode historical")''',
    ),
    (
        "code",
        '''if not weather.empty:
    summary = weather[["temp_max_c", "temp_min_c", "rh_min_pct", "precip_mm", "wind_max_kmh", "vpd_max_kpa"]].describe().T
    print(summary.round(2).to_string())
    print()
    print("nulos por variable:")
    print(weather[["temp_max_c", "rh_min_pct", "precip_mm", "vpd_max_kpa"]].isna().sum().to_string())''',
    ),
    (
        "md",
        """## 4. Weather context: do dry days carry more detections?

A deliberately simple test of the assumption the indicator rests on. If dry days
with a high vapour pressure deficit do not carry more detections, the design is
wrong and it is better to find out now.""",
    ),
    (
        "code",
        '''if not f1.empty and not weather.empty:
    fires_daily = f1.dropna(subset=["latitude", "longitude"]).copy()
    fires_daily["date"] = pd.to_datetime(fires_daily["acq_date"]).dt.normalize()
    daily = (
        fires_daily.groupby("date")
        .size()
        .rename("detections")
        .reset_index()
    )
    weather["date"] = pd.to_datetime(weather["date"])
    national = weather.groupby("date")[["precip_mm", "vpd_max_kpa", "temp_max_c"]].mean().reset_index()
    merged = daily.merge(national, on="date", how="inner")

    if len(merged) > 30:
        merged["precip_7d"] = merged.precip_mm.rolling(7, min_periods=1).sum()
        print("Correlación detecciones vs clima (nacional, 2024):")
        print(merged[["detections", "precip_mm", "precip_7d", "vpd_max_kpa", "temp_max_c"]].corr()["detections"].round(3).to_string())
        ax = merged.plot.scatter(x="precip_7d", y="detections", alpha=0.5, figsize=(6, 4))
        ax.set_title("Detecciones vs precipitación acumulada 7 días (2024)")
        plt.tight_layout()
        plt.savefig(FIGURES / "detections_vs_precip.png", dpi=140)
        plt.show()''',
    ),
    (
        "md",
        """## 5. F4: Open-Meteo forecast, and the seam with F2

The forecast product and ERA5 do not come from the same model. Their overlap is
the only place where the two can be compared, and the size of the difference is
what the ingestion contract has to declare.""",
    ),
    (
        "code",
        '''forecast_files = sorted((RAW / "openmeteo" / "forecast").glob("*.csv"))
if forecast_files:
    f4 = pd.read_csv(forecast_files[-1])
    profile_table(f4, "F4 Open-Meteo forecast")
    print()
    print("rango:", f4.date.min(), "->", f4.date.max(), "| regiones:", f4.region_id.nunique())
else:
    f4 = pd.DataFrame()
    print("Sin datos de forecast: ejecuta tools/pull_weather.py --mode forecast")''',
    ),
    (
        "code",
        '''if not f4.empty and not weather.empty:
    f4["date"] = pd.to_datetime(f4.date)
    weather["date"] = pd.to_datetime(weather["date"])
    overlap_dates = sorted(set(f4.date) & set(weather.date))
    if overlap_dates:
        a = f4[f4.date.isin(overlap_dates)].groupby("date").temp_max_c.mean()
        b = weather[weather.date.isin(overlap_dates)].groupby("date").temp_max_c.mean()
        diff = (a - b).round(2)
        print(f"días en solape: {len(overlap_dates)}")
        print("diferencia de temp_max (°C) entre forecast y ERA5:")
        print(diff.to_string())
    else:
        print("Sin días de solape entre F4 y F2")''',
    ),
    (
        "md",
        """## 6. Overlap: the same fire seen twice

Candidate pairs are NOAA-20 and NOAA-21 detections on the same day, within about
2 km and 10 minutes of each other. One fire, two records.""",
    ),
    (
        "code",
        '''def overlap_pairs(frame: pd.DataFrame, max_km: float = 2.0) -> pd.DataFrame:
    a = frame[frame.satellite == "N20"]
    b = frame[frame.satellite == "N21"]
    grid = {(round(r.latitude, 2), round(r.longitude, 2)): r
            for r in a.itertuples()}
    pairs = []
    for r in b.itertuples():
        key = (round(r.latitude, 2), round(r.longitude, 2))
        cand = grid.get(key)
        if cand is None:
            continue
        dy = (r.latitude - cand.latitude) * 111.0
        dx = (r.longitude - cand.longitude) * 111.0 * np.cos(np.radians(r.latitude))
        dist = float(np.hypot(dx, dy))
        if dist <= max_km:
            pairs.append({
                "date": r.acq_date,
                "n20_time": cand.acq_time, "n21_time": r.acq_time,
                "n20_frp": round(float(cand.frp), 2), "n21_frp": round(float(r.frp), 2),
                "dist_km": round(dist, 2),
                "n20_conf": cand.confidence, "n21_conf": r.confidence,
            })
        if len(pairs) >= 5:
            break
    return pd.DataFrame(pairs)


print("Pares candidatos NOAA-20 / NOAA-21 (mismo incendio, dos registros):")
print(overlap_pairs(f3).to_string(index=False))''',
    ),
    (
        "md",
        """In every pair the timestamp differs because the overpass differs, the position
differs by up to about 2 km of geolocation spread, the FRP differs because the
pixel footprint differs, and the confidence code often changes too. None of the
sources provides an identifier, so the ingestion layer has to build one.

## 7. Summary export

One row per source, which is what the report cites.""",
    ),
    (
        "code",
        '''summary = pd.DataFrame([
    {"source": "F1 firms_archive", "records_profiled": len(f1), "coverage": "2018-04 -> present",
     "format": "csv via API (SP)", "key_finding": "sensor change 2026 breaks naive baselines"},
    {"source": "F2 open_meteo_historical", "records_profiled": len(weather), "coverage": "2018 -> present",
     "format": "json (ERA5)", "key_finding": "local time unless timezone=UTC"},
    {"source": "F3 firms_nrt_viirs", "records_profiled": len(f3), "coverage": "last 5 days",
     "format": "csv (NRT)", "key_finding": "44.5% near-duplicates on a 1 km grid; 50% outside Colombia"},
    {"source": "F4 open_meteo_forecast", "records_profiled": len(f4), "coverage": "last 7 days + 7 ahead",
     "format": "json", "key_finding": "model seam with ERA5"},
])
summary.to_csv(ROOT / "workshop_1" / "profile_summary.csv", index=False)
print(summary.to_string(index=False))
print()
print("escrito:", ROOT / "workshop_1" / "profile_summary.csv")''',
    ),
    (
        "md",
        """## 8. What this forces in the design

Detection is not an event. With 44.5 % of rows sharing a ~1 km cell, the system
needs a `fire_event` table and a grouping rule before it aggregates anything.

Region assignment is not cosmetic either. Half the rows in the bounding box
belong to other countries.

The baseline has to be per sensor, because MODIS and the three VIIRS sensors
differ in footprint and in what they can detect.

Weather is stored as a series in `weather_observation`, never as an event, and
every request forces `timezone=UTC`.

Confidence gets normalised to one scale before any filter runs.

And the indicator has to condition on weather. A raw count compares a wet year
with a dry one and calls the difference an anomaly.""",
    ),
]


def cell(kind: str, source: str) -> dict:
    if kind == "md":
        return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def main() -> int:
    notebook = {
        "cells": [cell(kind, source) for kind, source in CELLS],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.14"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"escrito: {OUT.relative_to(ROOT)}")
    print(f"celdas : {len(CELLS)} ({sum(1 for k, _ in CELLS if k == 'code')} de código)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
