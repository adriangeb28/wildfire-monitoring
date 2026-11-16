r"""Sensor-change analysis for the historical archive (requirement: "document the effect").

Loads the 2024 partitions of every downloaded sensor, assigns each detection to a
department, and reports:

  * volume per sensor and the scale factor between them
  * how much of the bounding box is actually Colombia
  * monthly seasonality per sensor
  * top departments

Outputs a CSV summary and two figures for the report.

Usage:
    set PYTHONPATH=%CD%\vendor;$CD%\src
    python tools/analyze_sensors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from normalization.regions import assign_regions_fast, load_regions  # noqa: E402

HISTORY = ROOT / "data" / "raw" / "firms_history" / "2024"
FIGURES = ROOT / "docs" / "figures"
OUT_CSV = ROOT / "workshop_1" / "sensor_comparison_2024.csv"

LABELS = {
    "MODIS_SP": "MODIS (1 km)",
    "VIIRS_SNPP_SP": "VIIRS Suomi-NPP (375 m)",
    "VIIRS_NOAA20_SP": "VIIRS NOAA-20 (375 m)",
}


def load_sensor(directory: Path) -> pd.DataFrame | None:
    files = sorted(directory.glob("*.csv"))
    if not files:
        return None
    parts = []
    for path in files:
        block = pd.read_csv(path)
        if block.empty:
            continue
        parts.append(block)
    if not parts:
        return None
    frame = pd.concat(parts, ignore_index=True)
    frame["acq_date"] = pd.to_datetime(frame["acq_date"])
    return frame


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    print(f"regiones: {len(load_regions())}")

    frames: dict[str, pd.DataFrame] = {}
    for directory in sorted(HISTORY.iterdir()):
        if not directory.is_dir():
            continue
        frame = load_sensor(directory)
        if frame is None:
            print(f"{directory.name}: sin datos")
            continue
        print(f"{directory.name}: {len(frame):,} filas -> asignando regiones...")
        frame = assign_regions_fast(frame)
        frames[directory.name] = frame
        inside = int(frame.region_id.notna().sum())
        print(f"   dentro de Colombia: {inside:,} ({inside / len(frame):.1%})")

    if not frames:
        print("No hay particiones descargadas.")
        return 1

    # ---- volume and scale factors -----------------------------------------
    rows = []
    for sensor, frame in frames.items():
        inside = int(frame.region_id.notna().sum())
        rows.append(
            {
                "sensor": sensor,
                "label": LABELS.get(sensor, sensor),
                "detections": len(frame),
                "inside_colombia": inside,
                "inside_pct": round(inside / len(frame) * 100, 1),
                "frp_sum_mw": round(float(frame.frp.sum()), 1),
                "frp_mean_mw": round(float(frame.frp.mean()), 3),
            }
        )
    summary = pd.DataFrame(rows).sort_values("detections", ascending=False)
    print("\n=== volumen por sensor (2024) ===")
    print(summary.to_string(index=False))

    viiRs = summary[summary.sensor.str.startswith("VIIRS")]
    if len(viiRs) == 2:
        big, small = viiRs.iloc[0], viiRs.iloc[1]
        ratio = big.detections / small.detections
        print(f"\nfactor entre los dos VIIRS: {ratio:.3f} ({big.sensor} / {small.sensor})")
    if "MODIS_SP" in frames:
        viirs_total = int(viiRs.detections.sum())
        modis_total = int(summary.loc[summary.sensor == "MODIS_SP", "detections"].iloc[0])
        print(
            f"factor MODIS vs VIIRS : {viirs_total / modis_total:.2f}x  "
            f"(MODIS detecta {modis_total / viirs_total:.1%} de lo que detecta VIIRS)"
        )
        modis_frp = float(summary.loc[summary.sensor == "MODIS_SP", "frp_mean_mw"].iloc[0])
        viirs_frp = float(viiRs.frp_mean_mw.mean())
        print(f"FRP media por detección: MODIS {modis_frp:.2f} MW vs VIIRS {viirs_frp:.2f} MW "
              f"({modis_frp / viirs_frp:.2f}x)")
        print(
            f"=> Una baseline construida con MODIS haría que la actividad actual parezca "
            f"~{viirs_total / modis_total:.1f}x mayor solo por el cambio de instrumento."
        )

    # ---- monthly seasonality ----------------------------------------------
    monthly = pd.concat(
        [
            frame.groupby(frame.acq_date.dt.month).size().rename(sensor)
            for sensor, frame in frames.items()
        ],
        axis=1,
    ).fillna(0).astype(int).sort_index()
    monthly.index.name = "month"

    print("\n=== detecciones por mes y sensor (2024) ===")
    print(monthly.to_string())

    monthly.to_csv(OUT_CSV, index_label="month")
    summary.to_csv(OUT_CSV.with_name("sensor_summary_2024.csv"), index=False)
    print(f"\nescrito: {OUT_CSV.relative_to(ROOT)}")

    # ---- figures -----------------------------------------------------------
    ax = monthly.plot(figsize=(9, 4), marker="o")
    ax.set_title("Detections per month by sensor — Colombia bbox, 2024")
    ax.set_xlabel("month")
    ax.set_ylabel("detections")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURES / "sensor_seasonality_2024.png", dpi=140)
    plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    summary.set_index("label")["detections"].plot.bar(ax=axes[0], color="#c0504d")
    axes[0].set_title("Total detections 2024 per sensor")
    axes[0].set_ylabel("detections")
    axes[0].tick_params(axis="x", rotation=20)

    share = summary.set_index("label")[["inside_colombia"]].assign(
        outside=lambda d: summary.set_index("label")["detections"] - d["inside_colombia"]
    )
    share.plot.bar(stacked=True, ax=axes[1], color=["#4f81bd", "#c0c0c0"])
    axes[1].set_title("Inside vs outside Colombia (bbox leakage)")
    axes[1].tick_params(axis="x", rotation=20)
    plt.tight_layout()
    plt.savefig(FIGURES / "sensor_volume_and_bbox_2024.png", dpi=140)
    plt.close()
    print("figuras: docs/figures/sensor_seasonality_2024.png, sensor_volume_and_bbox_2024.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
