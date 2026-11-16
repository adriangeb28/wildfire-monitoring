"""Validate the anomaly indicator on the January 2024 fire episode.

Method
------
1. Take every ingested NOAA-20 archive detection (one sensor, so the comparison is
   not contaminated by the instrument discontinuity).
2. Assign each detection to a department (point-in-polygon).
3. Count detections per region for a fixed calendar window (1-31 January) in every
   available year -> the baseline is the same window in the previous years.
4. Anomaly = observed / expected, plus the percentile of the observation inside the
   historical distribution for that region.
5. Weather-conditioned expectation: OLS of log1p(count) on [log1p(precip_7d),
   vpd_max_c, temp_max_c] over all region-year observations, then compare the
   observed count with the weather-adjusted prediction.

Usage:
    set PYTHONPATH=%CD%\vendor;$CD%\src
    python tools/validate_indicator.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from normalization.regions import assign_regions_fast  # noqa: E402

HISTORY = ROOT / "data" / "raw" / "firms_history"
PANEL = ROOT / "data" / "raw" / "openmeteo" / "daily_panel.csv"
FIGURES = ROOT / "docs" / "figures"
OUT_CSV = ROOT / "workshop_1" / "indicator_validation_2024.csv"

SENSOR = "VIIRS_NOAA20_SP"
WINDOW_START = "01-01"
WINDOW_END = "01-31"
TARGET_YEAR = 2024
FOCUS_REGIONS = ["Cundinamarca", "Bogota Capital District", "Meta", "Vichada", "Norte de Santander"]


def load_year(year: int) -> pd.DataFrame | None:
    directory = HISTORY / str(year) / SENSOR
    if not directory.exists():
        return None
    files = sorted(directory.glob("*.csv"))
    if not files:
        return None
    parts = []
    for path in files:
        block = pd.read_csv(path)
        if not block.empty:
            parts.append(block)
    if not parts:
        return None
    frame = pd.concat(parts, ignore_index=True)
    frame["acq_date"] = pd.to_datetime(frame["acq_date"])
    mask = frame.acq_date.dt.strftime("%m-%d").between(WINDOW_START, WINDOW_END)
    frame = frame.loc[mask]
    if frame.empty:
        return None
    return assign_regions_fast(frame)


def region_counts() -> pd.DataFrame:
    rows = []
    for year in sorted({int(p.name) for p in HISTORY.iterdir() if p.is_dir() and p.name.isdigit()}):
        frame = load_year(year)
        if frame is None:
            print(f"{year}: sin datos para la ventana")
            continue
        counts = (
            frame.dropna(subset=["region_name"])
            .groupby(["region_id", "region_name"])
            .agg(detections=("frp", "size"), frp_sum=("frp", "sum"))
            .reset_index()
        )
        counts["year"] = year
        rows.append(counts)
        print(f"{year}: {len(frame):,} detecciones en la ventana -> {counts.detections.sum():,} en Colombia")
    if not rows:
        raise SystemExit("no hay datos ingeridos para la ventana")
    return pd.concat(rows, ignore_index=True)


def weather_window() -> pd.DataFrame:
    if not PANEL.exists():
        return pd.DataFrame()
    panel = pd.read_csv(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel.date.dt.strftime("%m-%d").between(WINDOW_START, WINDOW_END)].copy()
    panel["year"] = panel.date.dt.year
    if panel.empty:
        return pd.DataFrame()
    return (
        panel.groupby(["region_id", "year"])
        .agg(precip_mm=("precip_mm", "sum"), vpd_max_c=("vpd_max_kpa", "mean"),
             temp_max_c=("temp_max_c", "mean"), rh_min_pct=("rh_min_pct", "mean"))
        .reset_index()
    )


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    counts = region_counts()
    weather = weather_window()

    merged = counts.merge(weather, on=["region_id", "year"], how="left") if not weather.empty else counts.copy()

    baseline_years = sorted(y for y in merged.year.unique() if y < TARGET_YEAR)
    if not baseline_years:
        raise SystemExit("no hay años anteriores a 2024 para construir la baseline")
    print(f"años de baseline: {baseline_years}")

    base = (
        merged[merged.year.isin(baseline_years)]
        .groupby(["region_id", "region_name"])
        .agg(expected=("detections", "mean"), expected_max=("detections", "max"),
             n_years=("year", "nunique"))
        .reset_index()
    )
    target = merged[merged.year == TARGET_YEAR][["region_id", "region_name", "detections",
                                                 "frp_sum", "precip_mm", "vpd_max_c", "temp_max_c"]]
    result = target.merge(base, on=["region_id", "region_name"], how="left")

    # percentile of the 2024 observation inside the historical distribution
    history = merged[merged.year.isin(baseline_years)]
    percentiles, pos = [], []
    for _, row in result.iterrows():
        series = history.loc[history.region_id == row.region_id, "detections"].sort_values()
        if len(series) < 2 or pd.isna(row.detections):
            percentiles.append(np.nan)
            pos.append(np.nan)
        else:
            percentiles.append(float((series < row.detections).mean() * 100))
            pos.append(float(series.rank(pct=True).iloc[-1] * 100))
    result["percentile"] = percentiles

    result["ratio"] = (result.detections / result.expected).replace([np.inf, -np.inf], np.nan)
    result = result.sort_values("ratio", ascending=False)

    print(f"\n=== Validación: enero {TARGET_YEAR} vs baseline {baseline_years[0]}-{baseline_years[-1]} ===")
    print(result[["region_name", "detections", "expected", "ratio", "percentile"]]
          .head(12).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    print("\n--- regiones de interés ---")
    focus = result[result.region_name.isin(FOCUS_REGIONS)]
    print(focus[["region_name", "detections", "expected", "ratio", "percentile", "precip_mm", "vpd_max_c"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    national = result[["detections", "expected"]].sum()
    print(f"\nnacional: observado {national.detections:,.0f} vs esperado {national.expected:,.0f} "
          f"-> ratio {national.detections / national.expected:.2f}")

    # ---- weather-conditioned expectation -----------------------------------
    if not weather.empty and "vpd_max_c" in merged.columns:
        model_data = merged.dropna(subset=["detections", "precip_mm", "vpd_max_c", "temp_max_c"]).copy()
        if len(model_data) > 20:
            X = np.column_stack([
                np.ones(len(model_data)),
                np.log1p(model_data.precip_mm),
                model_data.vpd_max_c,
                model_data.temp_max_c,
            ])
            y = np.log1p(model_data.detections)
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            print("\nmodelo clima-condicionado: log1p(detecciones) ~ log1p(lluvia_ventana) + VPD + T_max")
            print(f"  coeficientes [intercepto, log1p(lluvia), VPD, T_max] = {np.round(beta, 3)}")

            pred_rows = result.dropna(subset=["precip_mm", "vpd_max_c", "temp_max_c"])
            Xp = np.column_stack([
                np.ones(len(pred_rows)),
                np.log1p(pred_rows.precip_mm),
                pred_rows.vpd_max_c,
                pred_rows.temp_max_c,
            ])
            result.loc[pred_rows.index, "expected_weather"] = np.expm1(Xp @ beta)
            result["ratio_weather"] = (
                result.detections / result.expected_weather
            ).replace([np.inf, -np.inf], np.nan)

            focus = result[result.region_name.isin(FOCUS_REGIONS)]
            print("\n--- anomalía bruta vs condicionada por clima ---")
            print(focus[["region_name", "detections", "expected", "ratio", "expected_weather", "ratio_weather"]]
                  .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    result["year"] = TARGET_YEAR
    result.to_csv(OUT_CSV, index=False)
    print(f"\nescrito: {OUT_CSV.relative_to(ROOT)}")

    # ---- figure ------------------------------------------------------------
    plot = result.dropna(subset=["ratio"]).nlargest(12, "detections")
    fig, ax = plt.subplots(figsize=(10, 4.4))
    x = np.arange(len(plot))
    ax.bar(x - 0.2, plot.expected, width=0.4, label="expected (baseline mean)", color="#a6a6a6")
    ax.bar(x + 0.2, plot.detections, width=0.4, label="observed, Jan 2024", color="#c0504d")
    ax.set_xticks(x)
    ax.set_xticklabels([n[:16] for n in plot.region_name], rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("detections in the 1-31 January window")
    ax.set_title(f"January {TARGET_YEAR} observed vs baseline ({baseline_years[0]}-{baseline_years[-1]}), "
                 f"VIIRS NOAA-20")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURES / "indicator_validation_2024.png", dpi=140)
    plt.close()
    print("figura: docs/figures/indicator_validation_2024.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
