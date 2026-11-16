"""Build the region layer: download boundaries and write the centroid table.

Downloads geoBoundaries gbOpen COL ADM1 (33 features) into data/reference/ and
writes workshop_1/samples/regions_centroids.csv, which is the input for the
Open-Meteo weather queries (one coordinate per region).

Usage:
    set PYTHONPATH=%CD%\vendor
    python tools/build_regions.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "data" / "reference"
GEOJSON = REFERENCE_DIR / "regions_col_adm1.geojson"
CENTROIDS = ROOT / "workshop_1" / "samples" / "regions_centroids.csv"
META = "https://www.geoboundaries.org/api/current/gbOpen/COL/ADM1/"
EXPECTED_REGIONS = 33  # 32 departments + Bogota D.C.


def main() -> int:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

    if GEOJSON.exists():
        print(f"ya existe: {GEOJSON.relative_to(ROOT)} ({GEOJSON.stat().st_size // 1024} KB)")
    else:
        meta = requests.get(META, timeout=120).json()
        print(f"fuente   : {meta.get('boundarySource')}")
        print(f"licencia : {meta.get('boundaryLicense')}")
        url = meta["gjDownloadURL"]
        print(f"descarga : {url}")
        payload = requests.get(url, timeout=300).content
        GEOJSON.write_bytes(payload)
        print(f"guardado : {GEOJSON.relative_to(ROOT)} ({len(payload) // 1024} KB)")

    data = json.loads(GEOJSON.read_text(encoding="utf-8"))
    features = data["features"]
    print(f"features : {len(features)}")
    if len(features) != EXPECTED_REGIONS:
        print(f"ADVERTENCIA: se esperaban {EXPECTED_REGIONS} regiones")

    from shapely.geometry import shape

    rows = []
    for feature in features:
        props = feature["properties"]
        name = props.get("shapeName", "unknown")
        geometry = shape(feature["geometry"])
        centroid = geometry.representative_point()  # inside the polygon, unlike centroid
        rows.append(
            {
                "region_id": props.get("shapeISO") or name,
                "name": name,
                "lat": round(centroid.y, 4),
                "lon": round(centroid.x, 4),
                "n_parts": len(getattr(geometry, "geoms", [geometry])),
            }
        )

    rows.sort(key=lambda r: r["name"])
    CENTROIDS.parent.mkdir(parents=True, exist_ok=True)
    with CENTROIDS.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["region_id", "name", "lat", "lon", "n_parts"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"centroides: {CENTROIDS.relative_to(ROOT)} ({len(rows)} filas)")
    print("\nprimeras 8 regiones:")
    for row in rows[:8]:
        print(f"  {row['name']:<22} lat={row['lat']:>8} lon={row['lon']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
