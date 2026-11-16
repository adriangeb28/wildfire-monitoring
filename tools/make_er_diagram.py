"""Draw the draft entity-relationship diagram for the wildfire schema.

Rendered with matplotlib only (no graphviz dependency) so it can be regenerated
anywhere the notebook environment runs. Output: docs/figures/er_diagram.png

Geometry is defined TOP-DOWN: each table declares the y of its top edge and the
box grows downwards, which is what keeps boxes from overlapping.

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/make_er_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "er_diagram.png"

TITLE_BG = "#2f5597"
TITLE_FG = "white"
BOX_BG = "#f7f9fc"
BOX_EDGE = "#2f5597"
KEY_BG = "#fff2cc"
HEAD_H = 5.2
ROW_H = 3.8

# x = left edge, top = y of the top edge, w = width
TABLES = {
    "event": {
        "x": 5, "top": 100, "w": 50,
        "columns": [
            "event_id  PK",
            "source · event_type",
            "observed_at  (UTC)",
            "latitude · longitude  (WGS84)",
            "severity + severity_unit",
            "raw_reference",
        ],
    },
    "fire_event": {
        "x": 59, "top": 100, "w": 50,
        "columns": [
            "fire_event_id  PK",
            "region_id  FK",
            "first_seen · last_seen",
            "centroid_lat · centroid_lon",
            "n_detections · frp_sum · frp_max",
            "sensor_set · cluster_params",
        ],
    },
    "fire_detection": {
        "x": 5, "top": 68, "w": 50,
        "columns": [
            "event_id  PK, FK → event",
            "region_id  FK → region",
            "brightness · bright_ti4 · bright_ti5",
            "frp",
            "confidence_raw · confidence_norm",
            "satellite · instrument · daynight",
        ],
    },
    "fire_event_member": {
        "x": 113, "top": 68, "w": 50,
        "columns": [
            "fire_event_id  FK, PK",
            "event_id  FK, PK",
        ],
    },
    "weather_observation": {
        "x": 5, "top": 34, "w": 50,
        "columns": [
            "region_id  FK, PK",
            "observed_at  PK  (UTC)",
            "variable  PK",
            "value · unit · source · model",
            "grid_resolution_deg · raw_reference",
        ],
    },
    "region": {
        "x": 59, "top": 34, "w": 50,
        "columns": [
            "region_id  PK  (33 units)",
            "name · level",
            "centroid_lat · centroid_lon",
            "geometry  (WGS84)",
            "source  (geoBoundaries / DANE)",
        ],
    },
    "ingestion_run": {
        "x": 113, "top": 34, "w": 50,
        "columns": [
            "run_id  PK",
            "source · partition · mode",
            "status  (started/committed/failed)",
            "rows_read · rows_written",
            "watermark_before · watermark_after",
        ],
    },
}

# (from, to, label, from_side, to_side, curvature)
RELATIONS = [
    ("fire_detection", "event", "event_id", "top", "bottom", 0.0),
    ("fire_detection", "region", "region_id", "right", "left", -0.18),
    ("fire_event_member", "event", "event_id", "left", "bottom", -0.12),
    ("fire_event_member", "fire_event", "fire_event_id", "top", "right", -0.12),
    ("fire_event", "region", "region_id", "bottom", "top", 0.0),
    ("weather_observation", "region", "region_id", "right", "left", 0.0),
]


def box_height(spec: dict) -> float:
    return HEAD_H + ROW_H * len(spec["columns"])


def draw_box(ax, name: str, spec: dict) -> None:
    x, top, w = spec["x"], spec["top"], spec["w"]
    h = box_height(spec)
    bottom = top - h

    ax.add_patch(
        FancyBboxPatch(
            (x, bottom), w, h,
            boxstyle="round,pad=0.4,rounding_size=1.0",
            linewidth=1.4, edgecolor=BOX_EDGE, facecolor=BOX_BG, zorder=2,
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (x, top - HEAD_H), w, HEAD_H,
            boxstyle="round,pad=0.4,rounding_size=1.0",
            linewidth=1.4, edgecolor=TITLE_BG, facecolor=TITLE_BG, zorder=3,
        )
    )
    ax.text(x + w / 2, top - HEAD_H / 2, name, ha="center", va="center",
            fontsize=10, fontweight="bold", color=TITLE_FG, zorder=4)

    for index, column in enumerate(spec["columns"]):
        row_center = top - HEAD_H - ROW_H * (index + 0.5)
        is_key = "PK" in column or "FK" in column
        if is_key:
            ax.add_patch(
                FancyBboxPatch(
                    (x + 1.2, row_center - 1.35), w - 2.4, ROW_H - 0.5,
                    boxstyle="round,pad=0.12,rounding_size=0.35",
                    linewidth=0, facecolor=KEY_BG, zorder=3,
                )
            )
        ax.text(x + 2.2, row_center, column, ha="left", va="center",
                fontsize=7.6, family="DejaVu Sans", zorder=4,
                fontweight="bold" if is_key else "normal")


def anchor(spec: dict, side: str) -> tuple[float, float]:
    x, top, w = spec["x"], spec["top"], spec["w"]
    bottom = top - box_height(spec)
    return {
        "left": (x, (top + bottom) / 2),
        "right": (x + w, (top + bottom) / 2),
        "top": (x + w / 2, top),
        "bottom": (x + w / 2, bottom),
    }[side]


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 8.0))
    ax.set_xlim(0, 168)
    ax.set_ylim(0, 112)
    ax.axis("off")

    for name, spec in TABLES.items():
        draw_box(ax, name, spec)

    for source, target, label, from_side, to_side, curvature in RELATIONS:
        start = anchor(TABLES[source], from_side)
        end = anchor(TABLES[target], to_side)
        ax.add_patch(
            FancyArrowPatch(
                start, end, arrowstyle="-|>", mutation_scale=14,
                linewidth=1.4, color="#595959", shrinkA=2, shrinkB=2,
                connectionstyle=f"arc3,rad={curvature}", zorder=1,
            )
        )
        mid_x, mid_y = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(mid_x, mid_y, label, fontsize=7, color="#333333",
                ha="center", va="center", zorder=5,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                          edgecolor="none", alpha=0.92))

    ax.text(2, 108.5, "Wildfire monitoring — draft ER diagram (Workshop 1)",
            fontsize=13, fontweight="bold", color="#1f3864")
    ax.text(2, 104.5,
            "event = canonical model required by the course   ·   fire_detection / fire_event / "
            "weather_observation = hazard domain   ·   region = 33 administrative units   ·   "
            "ingestion_run = operational state",
            fontsize=8, color="#404040")
    ax.text(2, 2.0,
            "PK = primary key   ·   FK = foreign key   ·   all timestamps UTC   ·   "
            "all geometry WGS84 decimal degrees   ·   writes are idempotent on duplicate_key",
            fontsize=8, color="#404040", style="italic")

    plt.tight_layout()
    plt.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"escrito: {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
