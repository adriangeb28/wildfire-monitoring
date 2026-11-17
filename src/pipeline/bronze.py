"""Bronze layer: one raw JSON file per source per ingestion run.

Why a JSON *envelope* around the payload
----------------------------------------
FIRMS answers in CSV and Open-Meteo in JSON. The workshop asks for raw JSON in
Bronze, and the course asks that raw data be kept exactly as received. The
envelope does both: the body is stored untouched in ``payload`` (as text), and
the envelope adds what is needed for provenance and change detection: when it
was fetched, the masked request, HTTP status and headers, a SHA-256 of the
payload and the result of the basic schema check.

File name: ``<source>_YYYYMMDD_HHMMSS.json``. The timestamp is the Airflow
logical run time (UTC), not the wall clock, so re-running the same interval
rewrites the same file instead of creating a second one (idempotency).
Files are written to a temporary name and renamed, so the FileSensor of the
Silver DAG never sees a half-written file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import settings
from .sources import FetchResult

log = settings.get_logger(__name__)

BRONZE_VERSION = 1

FIRMS_VIIRS_COLUMNS = [
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight",
]
FIRMS_REQUIRED = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "frp", "confidence"}


def bronze_name(result: FetchResult) -> str:
    if result.source in ("firms_nrt_viirs", "firms_archive"):
        return "firms_" + result.product.lower()        # firms_viirs_noaa20_nrt / _sp
    return result.source                                 # open_meteo_forecast


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_payload(result: FetchResult) -> dict:
    """Basic schema check. Returns a report; never raises on bad data."""
    report: dict = {"ok": True, "problems": [], "record_count": 0}
    if result.status != 200:
        report["ok"] = False
        report["problems"].append(f"http_status_{result.status}")
        return report

    if result.source in ("firms_nrt_viirs", "firms_archive"):
        reader = csv.reader(io.StringIO(result.payload))
        header = next(reader, [])
        missing = sorted(FIRMS_REQUIRED - set(header))
        if missing:
            report["ok"] = False
            report["problems"].append(f"missing_columns:{','.join(missing)}")
        unexpected = sorted(set(header) - set(FIRMS_VIIRS_COLUMNS))
        if unexpected:
            report["problems"].append(f"unexpected_columns:{','.join(unexpected)}")  # schema drift, not fatal
        report["record_count"] = sum(1 for row in reader if row)
        report["columns"] = header
        if report["record_count"] == 0:
            report["problems"].append("empty_window")   # valid: no fires or no overpass yet
        return report

    if result.source == "open_meteo_forecast":
        try:
            body = json.loads(result.payload)
        except json.JSONDecodeError as exc:
            return {"ok": False, "problems": [f"invalid_json:{exc}"], "record_count": 0}
        blocks = body if isinstance(body, list) else [body]
        expected = len(result.extra.get("region_order", [])) or len(blocks)
        if len(blocks) != expected:
            report["ok"] = False
            report["problems"].append(f"block_count_{len(blocks)}_expected_{expected}")
        for i, block in enumerate(blocks):
            hourly = block.get("hourly", {})
            if block.get("timezone") not in ("GMT", "UTC"):
                report["ok"] = False
                report["problems"].append(f"block_{i}_timezone_{block.get('timezone')}")
            for var in ("time", *settings.OPEN_METEO_HOURLY):
                if var not in hourly:
                    report["ok"] = False
                    report["problems"].append(f"block_{i}_missing_{var}")
        report["record_count"] = sum(len(b.get("hourly", {}).get("time", [])) for b in blocks)
        return report

    return {"ok": False, "problems": [f"unknown_source:{result.source}"], "record_count": 0}


def build_envelope(result: FetchResult, run_ts: datetime, validation: dict) -> dict:
    return {
        "bronze_version": BRONZE_VERSION,
        "source": result.source,
        "product": result.product,
        "run_ts": run_ts.astimezone(timezone.utc).isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "request": {"url": result.url, "params": result.params},
        "response": {
            "status": result.status,
            "content_type": result.content_type,
            "headers": result.headers,
        },
        "extra": result.extra,
        "validation": validation,
        "record_count": validation.get("record_count", 0),
        "payload_format": "json" if result.source == "open_meteo_forecast" else "csv",
        "payload_sha256": sha256_text(result.payload),
        "payload": result.payload,
    }


def write_bronze(envelope: dict, name: str, run_ts: datetime, directory: Path | None = None) -> Path:
    """Persist atomically as <name>_YYYYMMDD_HHMMSS.json and return the path."""
    directory = directory or settings.BRONZE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = run_ts.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = directory / f"{name}_{stamp}.json"
    tmp = directory / f".{target.name}.tmp"
    tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)
    log.info("bronze written: %s (%s records, sha256 %s)", target.name,
             envelope["record_count"], envelope["payload_sha256"][:12])
    return target


def read_bronze(path: Path) -> dict:
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    if envelope.get("bronze_version") != BRONZE_VERSION:
        raise ValueError(f"{path.name}: unsupported bronze_version {envelope.get('bronze_version')}")
    if sha256_text(envelope["payload"]) != envelope["payload_sha256"]:
        raise ValueError(f"{path.name}: payload does not match its sha256 (file altered)")
    return envelope
