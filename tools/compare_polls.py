"""Compare two Bronze files of the same source: what changed between two polls?

This is the empirical update-behaviour check asked for in Workshop 1 (poll an
incremental source twice, at least one hour apart, and record what changed).
It uses only the standard library, so it runs on any machine with Python.

    python tools/compare_polls.py datalake_bronze/firms_viirs_noaa20_nrt_A.json datalake_bronze/firms_viirs_noaa20_nrt_B.json
    python tools/compare_polls.py --latest firms_viirs_noaa20_nrt      # the two newest files of a source
    python tools/compare_polls.py --latest open_meteo_forecast --markdown workshop_2/poll_comparison.md
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "datalake_bronze"
FIRE_KEY = ("latitude", "longitude", "acq_date", "acq_time", "satellite")
FIRE_VALUES = ("frp", "bright_ti4", "bright_ti5", "confidence", "scan", "track", "version")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_firms(a: dict, b: dict) -> dict:
    def rows(env):
        return {tuple(r[k] for k in FIRE_KEY): r for r in csv.DictReader(io.StringIO(env["payload"]))}
    ra, rb = rows(a), rows(b)
    common = ra.keys() & rb.keys()
    changed = [k for k in common if any(ra[k].get(f) != rb[k].get(f) for f in FIRE_VALUES)]
    dates = lambda r: sorted({k[2] for k in r})  # noqa: E731
    return {
        "rows_first": len(ra), "rows_second": len(rb),
        "new_in_second": len(rb.keys() - ra.keys()),
        "gone_in_second": len(ra.keys() - rb.keys()),
        "same_key_changed_values": len(changed),
        "dates_first": dates(ra), "dates_second": dates(rb),
        "example_changed": [{"key": dict(zip(FIRE_KEY, k)),
                             "first": {f: ra[k][f] for f in FIRE_VALUES if f in ra[k]},
                             "second": {f: rb[k][f] for f in FIRE_VALUES if f in rb[k]}} for k in changed[:2]],
    }


def compare_weather(a: dict, b: dict) -> dict:
    def values(env):
        body = json.loads(env["payload"])
        blocks = body if isinstance(body, list) else [body]
        order = env.get("extra", {}).get("region_order") or list(range(len(blocks)))
        out = {}
        for region, block in zip(order, blocks):
            hourly = block["hourly"]
            for var, series in hourly.items():
                if var == "time":
                    continue
                for t, v in zip(hourly["time"], series):
                    out[(region, t, var)] = v
        return out
    va, vb = values(a), values(b)
    common = va.keys() & vb.keys()
    changed = [k for k in common if va[k] != vb[k]]
    times = lambda v: (min(k[1] for k in v), max(k[1] for k in v)) if v else (None, None)  # noqa: E731
    return {
        "values_first": len(va), "values_second": len(vb),
        "window_first": times(va), "window_second": times(vb),
        "new_hours_in_second": len(vb.keys() - va.keys()),
        "hours_dropped_in_second": len(va.keys() - vb.keys()),
        "same_hour_changed_value": len(changed),
        "example_changed": [{"key": k, "first": va[k], "second": vb[k]} for k in changed[:3]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--latest", help="source prefix; compares its two newest Bronze files")
    parser.add_argument("--markdown", type=Path, help="append the result as markdown to this file")
    args = parser.parse_args()

    files = args.files
    if args.latest:
        files = sorted(BRONZE.glob(f"{args.latest}_*.json"))[-2:]
    if len(files) != 2:
        parser.error("need exactly two Bronze files of the same source")
    a, b = load(files[0]), load(files[1])
    if a["source"] != b["source"]:
        parser.error("the two files come from different sources")

    result = compare_weather(a, b) if a["source"] == "open_meteo_forecast" else compare_firms(a, b)
    header = {
        "source": a["source"], "product": a["product"],
        "first": {"file": files[0].name, "fetched_at": a["fetched_at"], "sha256": a["payload_sha256"][:16]},
        "second": {"file": files[1].name, "fetched_at": b["fetched_at"], "sha256": b["payload_sha256"][:16]},
        "identical_payload": a["payload_sha256"] == b["payload_sha256"],
        "etag_or_last_modified": {k: v for k, v in b["response"]["headers"].items()
                                  if k.lower() in ("etag", "last-modified")},
    }
    report = header | result
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.markdown:
        with args.markdown.open("a", encoding="utf-8") as fh:
            fh.write(f"\n### {a['product']}: {files[0].name} vs {files[1].name}\n\n```json\n{text}\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
