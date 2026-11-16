r"""Validate the anomaly indicator on the January 2024 fire episode.

Method
------
1. Take every ingested NOAA-20 archive detection (one sensor, so the comparison is
   not contaminated by the instrument discontinuity).
2. Assign each detection to a department (point-in-polygon).
3. Count detections per region for a fixed calendar window (1-31 January) in every
   available year -> the baseline is the same window in the previous years.
4. Anomaly = observed / expected, plus the percentile of the observation inside the
   historical distribution of that region.
5. Weather-conditioned expectation with REGION FIXED EFFECTS: the within-region
   transformation removes the differences between departments (savanna vs Amazon,
   land use, burning practice) and keeps only how a region's own weather in 2024
   compares with its own history. Without fixed effects, the model confuses
   "region with high VPD" with "region that burns", and the coefficient on VPD
   comes out with the wrong sign.

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

SENSOR = "VIIRS_NOAA20_SP"          # NOAA-20 only: 2018-04 onward, still active
WINDOW_START, WINDOW_END = "01-01", "01-31"
TARGET_YEAR = 2024
FOCUS_REGIONS = ["Cundinamarca", "Bogota Capital District", "Meta", "Vichada",
                 "Norte de Santander", "Caqueta"]

WEATHER_FEATURES = ["precip_mm", "vpd_max_c", "temp_max_c"]


def load_year(year: int) -> pd.DataFrame | None:
    directory = HISTORY / str(year) / SENSOR
    if not directory.exists():
        return None
    parts = []
    for path in sorted(directory.glob("*.csv")):
        block = pd.read_csv(path)
        if not block.empty:
            parts.append(block)
    if not parts:
        return None
    frame = pd.concat(parts, ignore_index=True)
    frame["acq_date"] = pd.to_datetime(frame["acq_date"])
    frame = frame.loc[frame.acq_date.dt.strftime("%m-%d").between(WINDOW_START, WINDOW_END)]
    if frame.empty:
        return None
    return assign_regions_fast(frame)


def region_counts() -> pd.DataFrame:
    rows = []
    for directory in sorted(HISTORY.iterdir()):
        if not (directory.is_dir() and directory.name.isdigit()):
            continue
        year = int(directory.name)
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
        print(f"{year}: {len(frame):,} detecciones en la ventana -> "
              f"{int(counts.detections.sum()):,} en Colombia")
    if not rows:
        raise SystemExit("no hay datos ingeridos para la ventana")
    return pd.concat(rows, ignore_index=True)


def weather_window() -> pd.DataFrame:
    if not PANEL.exists():
        return pd.DataFrame()
    panel = pd.read_csv(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.loc[panel.date.dt.strftime("%m-%d").between(WINDOW_START, WINDOW_END)].copy()
    if panel.empty:
        return pd.DataFrame()
    panel["year"] = panel.date.dt.year
    return (
        panel.groupby(["region_id", "year"])
        .agg(precip_mm=("precip_mm", "sum"), vpd_max_c=("vpd_max_kpa", "mean"),
             temp_max_c=("temp_max_c", "mean"), rh_min_pct=("rh_min_pct", "mean"))
        .reset_index()
    )


def fixed_effects_expected(data: pd.DataFrame) -> tuple[pd.Series, np.ndarray]:
    """Within-region OLS: log1p(count) ~ weather, with a dummy per region.

    Returns the prediction for every row and the coefficient vector.
    """
    frame = data.dropna(subset=["detections", *WEATHER_FEATURES]).copy()
    frame["y"] = np.log1p(frame["detections"])
    frame["x_precip"] = np.log1p(frame["precip_mm"])

    frame["y_dm"] = frame["y"] - frame.groupby("region_id")["y"].transform("mean")
    design = ["x_precip", "vpd_max_c", "temp_max_c"]
    for column in design:
        frame[column + "_dm"] = frame[column] - frame.groupby("region_id")[column].transform("mean")

    X = frame[[c + "_dm" for c in design]].to_numpy()
    beta, *_ = np.linalg.lstsq(X, frame["y_dm"].to_numpy(), rcond=None)

    intercept = frame.groupby("region_id")["y"].mean()
    fitted = frame[["region_id", "year"]].copy()
    fitted["y_hat"] = fitted["region_id"].map(intercept) + X @ beta
    fitted["expected_weather"] = np.expm1(fitted["y_hat"])
    return fitted.set_index(["region_id", "year"])["expected_weather"], beta


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    counts = region_counts()
    weather = weather_window()

    merged = counts.merge(weather, on=["region_id", "year"], how="left") if not weather.empty else counts.copy()

    baseline_years = sorted(int(y) for y in merged.year.unique() if y < TARGET_YEAR)
    if len(baseline_years) < 2:
        raise SystemExit(f"se necesitan al menos 2 años de baseline, hay {baseline_years}")
    print(f"años de baseline: {baseline_years}")

    history = merged[merged.year.isin(baseline_years)]
    base = (
        history.groupby(["region_id", "region_name"])
        .agg(expected=("detections", "mean"), n_years=("year", "nunique"))
        .reset_index()
    )
    target = merged.loc[merged.year == TARGET_YEAR,
                        ["region_id", "region_name", "detections", "frp_sum",
                         "precip_mm", "vpd_max_c", "temp_max_c"]]
    result = target.merge(base, on=["region_id", "region_name"], how="left")
    result["ratio"] = (result.detections / result.expected).replace([np.inf, -np.inf], np.nan)

    percentiles = []
    for _, row in result.iterrows():
        series = history.loc[history.region_id == row.region_id, "detections"].sort_values()
        percentiles.append(
            float((series < row.detections).mean() * 100) if len(series) >= 2 else np.nan
        )
    result["percentile"] = percentiles

    if not weather.empty:
        expected_weather, beta = fixed_effects_expected(merged)
        result["expected_weather"] = [
            expected_weather.get((row.region_id, TARGET_YEAR), np.nan)
            for row in result.itertuples()
        ]
        result["ratio_weather"] = (result.detections / result.expected_weather).replace(
            [np.inf, -np.inf], np.nan
        )
        print("\nmodelo con efectos fijos por región: log1p(detecciones) ~ log1p(lluvia) + VPD + T_max")
        print(f"  coeficientes [log1p(lluvia), VPD, T_max] = {np.round(beta, 3)}")

    result = result.sort_values("ratio", ascending=False)

    print(f"\n=== Validación: enero {TARGET_YEAR} vs baseline {baseline_years[0]}-{baseline_years[-1]} ===")
    print(result[["region_name", "detections", "expected", "ratio", "percentile"]]
          .head(12).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    print("\n--- regiones de interés ---")
    cols = ["region_name", "detections", "expected", "ratio", "percentile",
            "precip_mm", "vpd_max_c", "expected_weather", "ratio_weather"]
    print(result.loc[result.region_name.isin(FOCUS_REGIONS), cols]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    national = result[["detections", "expected"]].sum()
    print(f"\nnacional: observado {national.detections:,.0f} vs esperado {national.expected:,.0f} "
          f"-> ratio {national.detections / national.expected:.2f}")

    result["year"] = TARGET_YEAR
    result.to_csv(OUT_CSV, index=False)
    print(f"\nescrito: {OUT_CSV.relative_to(ROOT)}")

    plot = result.dropna(subset=["ratio"]).nlargest(12, "detections")
    fig, ax = plt.subplots(figsize=(10, 4.4))
    x = np.arange(len(plot))
    ax.bar(x - 0.2, plot.expected, width=0.4, label="expected (baseline mean)", color="#a6a6a6")
    ax.bar(x + 0.2, plot.detections, width=0.4, label=f"observed, Jan {TARGET_YEAR}", color="#c0504d")
    ax.set_xticks(x)
    ax.set_xticklabels([n[:16] for n in plot.region_name], rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("detections, 1-31 January window")
    ax.set_title(f"January {TARGET_YEAR} vs baseline {baseline_years[0]}-{baseline_years[-1]} "
                 f"(VIIRS NOAA-20)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURES / "indicator_validation_2024.png", dpi=140)
    plt.close()
    print("figura: docs/figures/indicator_validation_2024.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
