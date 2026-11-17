"""Build recorded Bronze envelopes in tests/fixtures/ from the Workshop 1 raw samples.

The samples are real responses (FIRMS NRT VIIRS NOAA-20 / NOAA-21, 5-day
Colombia window, and the Open-Meteo forecast for Bogota), taken on 2026-11-14.
Wrapping them in the Bronze envelope lets the tests and the offline demo run
the exact Silver code path without calling the APIs.

    python tools/make_fixtures.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline import bronze  # noqa: E402
from pipeline.sources import FetchResult  # noqa: E402

SAMPLES = ROOT / "workshop_1" / "samples"
OUT = ROOT / "tests" / "fixtures"
RUN_TS = datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)

CASES = [
    ("firms_nrt_viirs", "VIIRS_NOAA20_NRT", "firms_VIIRS_NOAA20_NRT_colombia_5d_20261114T025629Z.csv",
     "text/csv", {}),
    ("firms_nrt_viirs", "VIIRS_NOAA21_NRT", "firms_VIIRS_NOAA21_NRT_colombia_5d_20261114T025640Z.csv",
     "text/csv", {}),
    ("open_meteo_forecast", "forecast", "openmeteo_forecast_bogota_20261114T025548Z.json",
     "application/json", {"region_order": ["CO-DC"]}),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for source, product, sample, ctype, extra in CASES:
        result = FetchResult(source=source, product=product, url=f"recorded:{sample}", params={},
                             status=200, headers={"Content-Type": ctype}, content_type=ctype,
                             payload=(SAMPLES / sample).read_text(encoding="utf-8"), extra=extra)
        validation = bronze.validate_payload(result)
        envelope = bronze.build_envelope(result, RUN_TS, validation)
        envelope["fetched_at"] = "2026-11-14T02:56:29+00:00"   # time of the recorded call
        path = bronze.write_bronze(envelope, bronze.bronze_name(result), RUN_TS, OUT)
        print(path.relative_to(ROOT), validation["record_count"], "records", validation["problems"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
