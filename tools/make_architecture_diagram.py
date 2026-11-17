"""Draw the high-level architecture diagram (docs/figures/architecture.png).

Follows the reference architecture of the Course Project document
(sources -> raw landing zone -> normalize/validate/deduplicate -> database,
with quarantine, analytics and dashboard), adapted to wildfire monitoring.

    python tools/make_architecture_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "architecture.png"

BLUE, LIGHT, GREY, AMBER = "#2f5597", "#f7f9fc", "#595959", "#fff2cc"


def box(ax, x, y, w, h, title, lines, fill=LIGHT, edge=BLUE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=0.8",
                                linewidth=1.4, edgecolor=edge, facecolor=fill, zorder=2))
    ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="center", fontsize=9.5,
            fontweight="bold", color="#1f3864", zorder=3)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 5.6 - i * 2.9, line, ha="center", va="center",
                fontsize=7.4, color="#262626", zorder=3)


def arrow(ax, a, b, label=None, rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=13, linewidth=1.3,
                                 color=GREY, connectionstyle=f"arc3,rad={rad}", zorder=1))
    if label:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 1.4, label, ha="center", fontsize=7,
                color="#333333", bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                                           edgecolor="none"), zorder=4)


def main() -> int:
    fig, ax = plt.subplots(figsize=(15, 7.2))
    ax.set_xlim(0, 160)
    ax.set_ylim(-3, 78)
    ax.axis("off")

    # Docker Compose boundary
    ax.add_patch(FancyBboxPatch((38, 3), 120, 64, boxstyle="round,pad=0.4,rounding_size=1.2",
                                linewidth=1.2, edgecolor="#8faadc", facecolor="none",
                                linestyle="--", zorder=0))
    ax.text(40, 64.5, "Docker Compose (local)", fontsize=8.5, color="#2f5597", style="italic")

    # Sources
    box(ax, 2, 50, 30, 15, "F1 FIRMS archive (SP)", ["historical · CSV · area API", "VIIRS N20/S-NPP, MODIS", "5-day windows · MAP_KEY"])
    box(ax, 2, 33, 30, 15, "F2 Open-Meteo ERA5", ["historical · JSON · no key", "33 region centroids", "timezone=UTC"])
    box(ax, 2, 16, 30, 15, "F3 FIRMS NRT (VIIRS)", ["incremental · CSV", "NOAA-20 / NOAA-21", "poll every 3 h, 1-day overlap"])
    box(ax, 2, -1, 30, 15, "F4 Open-Meteo Forecast", ["incremental · JSON", "past_days=7 + forecast", "hourly, 48 h overlap"])
    ax.text(17, 68.5, "Sources", ha="center", fontsize=10, fontweight="bold", color="#1f3864")

    # Orchestrator + ingestion app
    box(ax, 41, 44, 30, 18, "Orchestrator", ["Airflow DAG (or documented", "scheduler) runs", "ingest.py --mode incremental", "ingest.py --mode historical"], fill=AMBER)
    box(ax, 41, 14, 30, 24, "Raw landing zone", ["data/raw/", "files kept exactly as received", "source_YYYYMMDD_HHMMSS.ext", "+ HTTP headers (ETag,", "Last-Modified) + checksum"])

    # Processing
    box(ax, 76, 26, 34, 30, "Normalize · validate · dedupe", ["UTC timestamps (acq_time HHMM)", "point-in-polygon -> region_id", "confidence l/n/h -> 0-100", "range/type/coordinate checks", "content_hash -> new / changed", "group detections -> fire_event"])
    box(ax, 76, 6, 34, 15, "Quarantine", ["rejected_record", "(reason + raw payload)"], fill="#fbe5d6", edge="#c55a11")

    # Database
    box(ax, 115, 30, 40, 30, "PostgreSQL + PostGIS", ["source · ingestion_run · ingestion_state", "event · event_group · rejected_record", "fire_detection · fire_event", "weather_observation · region", "analytical views:", "region-day panel"])

    # Analytics + dashboard
    box(ax, 115, 6, 40, 19, "Analytics + Dash (localhost:8050)", ["today · last 7 days · historical avg", "per-sensor baseline, weather-", "conditioned anomaly per region", "data-health panel"], fill="#e2f0d9", edge="#548235")

    for y in (57.5, 40.5, 23.5, 6.5):
        arrow(ax, (32.6, y), (40.6, 26), rad=0.0)
    arrow(ax, (56, 43.7), (56, 38.4), "triggers")
    arrow(ax, (71.4, 26), (75.6, 41), "read")
    arrow(ax, (93, 25.7), (93, 21.4), "invalid rows")
    arrow(ax, (110.4, 41), (114.6, 45), "idempotent upsert")
    arrow(ax, (135, 29.6), (135, 25.4), "reads DB only")

    ax.text(2, 74.5, "Wildfire monitoring — high-level architecture (Workshop 1)", fontsize=13,
            fontweight="bold", color="#1f3864")
    ax.text(2, 71.2, "Reference architecture of the course adapted to the hazard. The watermark in "
            "ingestion_state advances only after the partition commits.", fontsize=8.2, color="#404040")
    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"written: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
