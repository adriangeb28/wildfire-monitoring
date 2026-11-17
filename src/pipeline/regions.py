"""Point-in-polygon assignment to the 33 Colombian regions.

Uses shapely (vectorised ``contains_xy``) when it is installed, which is the
case in the Docker image. A pure-Python ray-casting fallback keeps the tests
runnable on machines without shapely; both give the same answer for points
that are not exactly on a border.

Layer: geoBoundaries gbOpen COL ADM1 (ODbL 1.0), stored in reference/ with
coordinates rounded to 4 decimals (about 11 m).
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from . import settings

try:
    import shapely
    from shapely.geometry import shape
except ImportError:  # pragma: no cover - exercised only without shapely
    shapely = None


@lru_cache(maxsize=1)
def _features() -> list[dict]:
    data = json.loads(settings.REGIONS_GEOJSON.read_text(encoding="utf-8"))
    out = []
    for feature in data["features"]:
        props = feature["properties"]
        geom = feature["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        xs = [x for poly in polys for x, _ in poly[0]]
        ys = [y for poly in polys for _, y in poly[0]]
        out.append({
            "region_id": props["shapeISO"],
            "name": props["shapeName"],
            "geometry": geom,
            "polygons": polys,
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        })
    return out


def _ring_contains(ring: list, x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygon_contains(polygon: list, x: float, y: float) -> bool:
    if not _ring_contains(polygon[0], x, y):
        return False
    return not any(_ring_contains(hole, x, y) for hole in polygon[1:])


def assign(lat: np.ndarray, lon: np.ndarray) -> tuple[list, list]:
    """Return (region_id, region_name) lists; None for points outside Colombia."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    ids: list = [None] * len(lat)
    names: list = [None] * len(lat)
    pending = np.ones(len(lat), dtype=bool) & np.isfinite(lat) & np.isfinite(lon)

    for feature in _features():
        x0, y0, x1, y1 = feature["bbox"]
        candidates = pending & (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)
        if not candidates.any():
            continue
        idx = np.nonzero(candidates)[0]
        if shapely is not None:
            geom = shape(feature["geometry"])
            shapely.prepare(geom)
            hit = shapely.contains_xy(geom, lon[idx], lat[idx])
        else:
            hit = np.array([
                any(_polygon_contains(poly, lon[i], lat[i]) for poly in feature["polygons"])
                for i in idx
            ], dtype=bool)
        for i in idx[hit]:
            ids[i] = feature["region_id"]
            names[i] = feature["name"]
        pending[idx[hit]] = False
        if not pending.any():
            break
    return ids, names
