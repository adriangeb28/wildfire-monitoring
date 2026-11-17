"""Workshop 2 architecture diagram: sources, Airflow, Bronze, Silver, Gold (planned), dashboard (planned).

    python tools/make_w2_architecture.py   ->  docs/figures/w2_architecture.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "w2_architecture.png"

INK = "#1f3864"


def box(ax, x, y, w, h, title, lines, fill="#f7f9fc", edge="#2f5597", dashed=False, size=7.3):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=0.8",
                                linewidth=1.3, edgecolor=edge, facecolor=fill, zorder=2,
                                linestyle="--" if dashed else "-"))
    ax.text(x + w / 2, y + h - 2.0, title, ha="center", va="center", fontsize=9, fontweight="bold",
            color=INK, zorder=3)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 5.0 - i * 2.6, line, ha="center", va="center", fontsize=size,
                color="#262626", zorder=3)


def zone(ax, x, y, w, h, label, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.0",
                                linewidth=0, facecolor=color, alpha=0.55, zorder=0))
    ax.text(x + 1.2, y + h - 1.6, label, fontsize=8.5, fontweight="bold", color="#404040", zorder=1)


def arrow(ax, a, b, label=None, rad=0.0, dashed=False, dy=1.3):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, linewidth=1.2,
                                 color="#595959", connectionstyle=f"arc3,rad={rad}", zorder=1,
                                 linestyle="--" if dashed else "-"))
    if label:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, label, ha="center", fontsize=6.8,
                color="#333333", zorder=4,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none"))


def main() -> int:
    fig, ax = plt.subplots(figsize=(16, 8.2))
    ax.set_xlim(0, 170)
    ax.set_ylim(0, 86)
    ax.axis("off")

    # layer zones
    zone(ax, 1, 4, 30, 70, "SOURCES (external)", "#eef2f7")
    zone(ax, 35, 4, 96, 70, "DOCKER COMPOSE (localhost)", "#e9eff9")
    zone(ax, 135, 4, 33, 70, "PLANNED (W3-W4)", "#f2f2f2")

    box(ax, 3, 52, 26, 17, "F3 FIRMS NRT", ["VIIRS NOAA-20 / NOAA-21", "area API, CSV, MAP_KEY", "2-day window, ~3 h latency"])
    box(ax, 3, 31, 26, 17, "F4 Open-Meteo", ["Forecast API, JSON", "33 centroids, UTC", "past 7 d + next 7 d"])
    box(ax, 3, 8, 26, 19, "F1 / F2 archives", ["FIRMS SP (5-day windows)", "Open-Meteo ERA5", "bulk load via", "ingest.py --mode historical"], dashed=True)

    # Airflow
    box(ax, 38, 54, 44, 17, "Airflow 2.10 (LocalExecutor)", ["webserver :8080 · scheduler · triggerer",
        "metadata DB: postgres:16", "DAGs bind-mounted from airflow/dags/"], fill="#fff2cc", edge="#bf9000")

    box(ax, 38, 30, 44, 19, "DAG bronze_ingestion", ["@dag / @task, cron 0 */3 * * *", "extract_firms (mapped x2)",
        "extract_open_meteo", "validate -> persist (atomic write)"], fill="#fff7e0", edge="#bf9000")
    box(ax, 86, 54, 42, 17, "DAG silver_processing", ["cron */30, FileSensor on *.json", "find_new_files (short-circuit)",
        "process -> report"], fill="#fff7e0", edge="#bf9000")

    # layers
    box(ax, 38, 7, 44, 19, "BRONZE  datalake_bronze/", ["<source>_YYYYMMDD_HHMMSS.json", "payload exactly as received",
        "+ sha256, masked request,", "HTTP headers, schema check"], fill="#f8e5d0", edge="#a0522d")
    box(ax, 86, 7, 42, 43, "SILVER  datalake_silver/", ["preprocessing (pandas):", "types, UTC, required fields",
        "range checks, frp > 0", "point-in-polygon -> region_id", "confidence l/n/h -> levels",
        "IQR / z-score flags (kept)", "gap fill <= 3 h (weather)", "dedup: registry new / revised",
        "", "fire_detections_YYYYMMDD_HHMMSS.parquet", "weather_hourly_YYYYMMDD_HHMMSS.parquet",
        "_quarantine/rejected_*.parquet", "_state/ registry (SQLite)"], fill="#e7eef8", edge="#7f8c9a", size=7.0)

    box(ax, 137, 44, 29, 25, "GOLD  datalake_gold/", ["PySpark over all Silver", "fire events (clustering)",
        "region-day panel", "baseline per sensor", "anomaly indicator"], fill="#fdf3c4", edge="#bf9000", dashed=True)
    box(ax, 137, 24, 29, 16, "warehouse-db", ["PostGIS :5433", "canonical schema", "(sql/schema.sql)"], dashed=True)
    box(ax, 137, 6, 29, 14, "Dash dashboard", ["localhost:8050", "today · 7 days · baseline"], fill="#e2f0d9", edge="#548235", dashed=True)

    arrow(ax, (29.4, 60), (37.6, 40), "HTTPS")
    arrow(ax, (29.4, 39), (37.6, 37))
    arrow(ax, (29.4, 17), (37.6, 16), "historical", dashed=True)
    arrow(ax, (60, 53.7), (60, 49.4), "schedules")
    arrow(ax, (82.4, 62), (85.6, 62), dy=1.6)
    arrow(ax, (60, 29.7), (60, 26.4), "writes JSON")
    arrow(ax, (82.4, 16), (85.6, 16), "sensor + read", dy=2.2)
    arrow(ax, (107, 53.7), (107, 50.4), "runs")
    arrow(ax, (128.4, 40), (136.6, 52), "Parquet", dashed=True)
    arrow(ax, (151.5, 43.7), (151.5, 40.4), dashed=True)
    arrow(ax, (151.5, 23.7), (151.5, 20.4), dashed=True)

    ax.text(1, 82.5, "Wildfire monitoring: Workshop 2 technical architecture (medallion layers on Airflow)",
            fontsize=13, fontweight="bold", color=INK)
    ax.text(1, 79, "Solid = implemented in Workshop 2 · dashed = planned. All outputs persist on the host "
            "through bind mounts; every Silver row keeps the name of its Bronze file.", fontsize=8.3, color="#404040")
    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"written: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
