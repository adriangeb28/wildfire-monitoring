"""Region layer: administrative boundaries (33 units) and point-in-polygon assignment.

Reference source: geoBoundaries gbOpen COL ADM1 (33 features, ODbL 1.0).
The full GeoJSON is downloaded into data/reference/ (not committed). Only the
33-row centroid table is committed, under workshop_1/samples/.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "data" / "reference"
REGIONS_GEOJSON = REFERENCE_DIR / "regions_col_adm1.geojson"
CENTROIDS_CSV = ROOT / "workshop_1" / "samples" / "regions_centroids.csv"


def slug(name: str) -> str:
    """Stable, file-safe region id derived from the official name."""
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}
    text = name.lower().strip()
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return "_".join(part for part in "".join(c if c.isalnum() else " " for c in text).split())


@lru_cache(maxsize=1)
def load_regions() -> list[dict]:
    """Return [{'region_id', 'name', 'geometry'}] for the 33 regions."""
    if not REGIONS_GEOJSON.exists():
        raise FileNotFoundError(
            f"{REGIONS_GEOJSON} is missing. Run: python tools/build_regions.py"
        )
    data = json.loads(REGIONS_GEOJSON.read_text(encoding="utf-8"))
    regions = []
    for feature in data["features"]:
        props = feature["properties"]
        name = props.get("shapeName") or props.get("name") or "unknown"
        regions.append(
            {
                "region_id": props.get("shapeISO") or slug(name),
                "name": name,
                "geometry": shape(feature["geometry"]),
            }
        )
    return regions


@lru_cache(maxsize=1)
def _tree() -> tuple[STRtree, list[dict]]:
    regions = load_regions()
    return STRtree([r["geometry"] for r in regions]), regions


def assign_region(lat: float, lon: float) -> tuple[str | None, str | None]:
    """Point-in-polygon assignment. Returns (region_id, name) or (None, None)."""
    tree, regions = _tree()
    point = Point(lon, lat)
    for index in tree.query(point):
        candidate = regions[int(index)]
        if candidate["geometry"].covers(point):
            return candidate["region_id"], candidate["name"]
    return None, None


def assign_regions(frame, lat_col: str = "latitude", lon_col: str = "longitude"):
    """Vectorised-ish assignment: adds region_id and region_name columns."""
    results = [assign_region(lat, lon) for lat, lon in zip(frame[lat_col], frame[lon_col])]
    frame = frame.copy()
    frame["region_id"] = [r[0] for r in results]
    frame["region_name"] = [r[1] for r in results]
    return frame
