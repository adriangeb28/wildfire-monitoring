"""Tests for the Bronze -> Silver pipeline, on recorded responses (no live calls).

Fixtures in tests/fixtures/ are real FIRMS and Open-Meteo responses from
2026-11-14 wrapped in Bronze envelopes (tools/make_fixtures.py).
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline import bronze, preprocess, silver  # noqa: E402
from pipeline.sources import FetchResult  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)
N20 = FIX / "firms_viirs_noaa20_nrt_20261114_030000.json"
N21 = FIX / "firms_viirs_noaa21_nrt_20261114_030000.json"
WX = FIX / "open_meteo_forecast_20261114_030000.json"

HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
          "confidence,version,bright_ti5,frp,daynight")
BOGOTA = "4.65,-74.10"          # inside Bogota D.C.
CARACAS = "10.48,-66.90"        # inside the bbox, outside Colombia


def firms_envelope(rows: list[str], product: str = "VIIRS_NOAA20_NRT") -> dict:
    payload = "\n".join([HEADER, *rows]) + "\n"
    result = FetchResult("firms_nrt_viirs", product, "test", {}, 200, {}, "text/csv", payload)
    return bronze.build_envelope(result, NOW, bronze.validate_payload(result))


def row(latlon=BOGOTA, acq_time="658", frp="3.08", conf="n", sat="N20", date="2026-11-10", ti4="306.2") -> str:
    return f"{latlon},{ti4},0.55,0.51,{date},{acq_time},{sat},VIIRS,{conf},2.0NRT,293.7,{frp},N"


# ---------------------------------------------------------------- Bronze
def test_bronze_validation_detects_missing_columns():
    result = FetchResult("firms_nrt_viirs", "VIIRS_NOAA20_NRT", "t", {}, 200, {}, "text/csv",
                         "latitude,longitude\n1,2\n")
    report = bronze.validate_payload(result)
    assert not report["ok"]
    assert any(p.startswith("missing_columns") for p in report["problems"])


def test_bronze_empty_window_is_valid():
    result = FetchResult("firms_nrt_viirs", "VIIRS_SNPP_NRT", "t", {}, 200, {}, "text/csv", HEADER + "\n")
    report = bronze.validate_payload(result)
    assert report["ok"] and report["record_count"] == 0 and "empty_window" in report["problems"]


def test_bronze_roundtrip_and_tamper_detection(tmp_path):
    env = firms_envelope([row()])
    path = bronze.write_bronze(env, "firms_viirs_noaa20_nrt", NOW, tmp_path)
    assert path.name == "firms_viirs_noaa20_nrt_20261114_030000.json"
    assert bronze.read_bronze(path)["payload"] == env["payload"]
    data = json.loads(path.read_text())
    data["payload"] = data["payload"].replace("3.08", "9.99")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="sha256"):
        bronze.read_bronze(path)


def test_recorded_fixtures_pass_the_schema_check():
    for path in (N20, N21, WX):
        assert bronze.read_bronze(path)["validation"]["ok"], path.name


# ---------------------------------------------------------------- Fires
def test_acq_time_without_zero_padding_becomes_utc_timestamp():
    clean, _, _ = preprocess.preprocess_fires(firms_envelope([row(acq_time="658"), row(acq_time="3", latlon="4.66,-74.11")]), "f.json", now=NOW)
    times = sorted(clean["observed_at"].dt.strftime("%H:%M"))
    assert times == ["00:03", "06:58"]
    assert str(clean["observed_at"].dt.tz) == "UTC"


def test_invalid_rows_go_to_quarantine_with_reason():
    rows = [row(frp="0.00"), row(latlon=CARACAS), row(acq_time="2471"), row(frp=""), row()]
    clean, rejected, stats = preprocess.preprocess_fires(firms_envelope(rows), "f.json", now=NOW)
    assert len(clean) == 1
    assert sorted(rejected["reason"]) == ["bad_acq_time", "frp_nonpositive", "missing_frp", "outside_colombia"]
    assert stats["rows_in"] == 5 and stats["rows_rejected"] == 4
    assert set(rejected["bronze_row"]) == {2, 3, 4, 5}       # CSV line numbers, header = 1


def test_confidence_codes_become_ordered_levels():
    rows = [row(conf="l", latlon="4.60,-74.10"), row(conf="n", latlon="4.61,-74.10"),
            row(conf="h", latlon="4.62,-74.10"), row(conf="", latlon="4.63,-74.10")]
    clean, _, _ = preprocess.preprocess_fires(firms_envelope(rows), "f.json", now=NOW)
    levels = dict(zip(clean["confidence_raw"].fillna("-"), clean["confidence_level"].astype(str)))
    assert levels == {"l": "low", "n": "nominal", "h": "high", "-": "unknown"}
    assert clean["confidence_level"].cat.ordered


def test_implausible_brightness_is_nulled_and_flagged():
    clean, _, _ = preprocess.preprocess_fires(firms_envelope([row(ti4="999")]), "f.json", now=NOW)
    assert np.isnan(clean["bright_ti4"].iloc[0])
    assert "bright_ti4_implausible" in clean["quality_flags"].iloc[0]


def test_exact_duplicates_are_dropped_inside_a_batch():
    clean, _, stats = preprocess.preprocess_fires(firms_envelope([row(), row()]), "f.json", now=NOW)
    assert len(clean) == 1 and stats["duplicates_in_batch"] == 1


def test_recorded_noaa20_window():
    """The W1 findings must reappear on the recorded response."""
    clean, rejected, stats = preprocess.preprocess_fires(bronze.read_bronze(N20), N20.name, now=NOW)
    assert stats["rows_in"] == 1071
    assert stats["rejected_by_reason"].get("frp_nonpositive") == 1          # W1 finding 3
    assert stats["rejected_by_reason"].get("outside_colombia", 0) > 400     # W1 finding 5
    assert clean["region_id"].str.startswith("CO-").all()
    assert clean["frp_outlier"].sum() >= 1                                   # large fires flagged, kept


def test_largest_recorded_fire_is_flagged_not_removed():
    """W1 finding 4: the 196 MW fire (NOAA-21, Norte de Santander) is real; it must survive."""
    clean, _, _ = preprocess.preprocess_fires(bronze.read_bronze(N21), N21.name, now=NOW)
    big = clean[clean["frp"] > 190]
    assert len(big) >= 1 and big["frp_outlier"].all()
    assert set(big["region_name"]) == {"Norte de Santander"}


# ---------------------------------------------------------------- Weather
def weather_envelope(values: list) -> dict:
    times = pd.date_range("2026-11-14", periods=len(values), freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    hourly = {"time": times}
    units = {"time": "iso8601"}
    for var in ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"):
        hourly[var] = values if var == "temperature_2m" else [1.0] * len(values)
        units[var] = "x"
    body = [{"timezone": "GMT", "hourly": hourly, "hourly_units": units}]
    result = FetchResult("open_meteo_forecast", "forecast", "t", {}, 200, {}, "application/json",
                         json.dumps(body), {"region_order": ["CO-DC"]})
    return bronze.build_envelope(result, NOW, bronze.validate_payload(result))


def test_weather_short_gaps_are_interpolated_long_gaps_stay_null():
    values = [10, None, None, 13, 14, None, None, None, None, 19, 20, 99.0]   # 99 C is out of range
    clean, _, stats = preprocess.preprocess_weather(weather_envelope(values), "w.json", now=NOW)
    temp = clean[clean["variable"] == "temperature_2m"].sort_values("observed_at")
    assert temp["value"].iloc[1] == pytest.approx(11.0) and temp["imputed"].iloc[1]
    assert temp["value"].iloc[5:9].isna().all()                 # 4-hour gap: not invented
    assert np.isnan(temp["value"].iloc[11]) and "out_of_range" in temp["quality_flags"].iloc[11]
    assert stats["imputed"] == 2


def test_recorded_forecast_is_long_format_utc():
    clean, _, stats = preprocess.preprocess_weather(bronze.read_bronze(WX), WX.name, now=NOW)
    assert stats["rows_clean"] == 96 * 4
    assert set(clean["variable"].astype(str)) == {"temperature_2m", "relative_humidity_2m",
                                                  "precipitation", "wind_speed_10m"}
    assert str(clean["observed_at"].dt.tz) == "UTC"


def test_schema_enforcement_rejects_missing_required_values():
    frame = pd.DataFrame({c: [None] for c in preprocess.WEATHER_SCHEMA})
    with pytest.raises(preprocess.SchemaError):
        preprocess.enforce_schema(frame, preprocess.WEATHER_SCHEMA, preprocess.WEATHER_REQUIRED)


# ---------------------------------------------------------------- Silver (idempotency)
@pytest.fixture
def lake(tmp_path, monkeypatch):
    """A private data lake; Parquet is replaced by pickle when pyarrow is absent."""
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        def fake_write(frame, path, metadata):
            frame.to_pickle(path)
        monkeypatch.setattr(silver, "_write_parquet", fake_write)
    bronze_dir, silver_dir = tmp_path / "bronze", tmp_path / "silver"
    bronze_dir.mkdir()
    return bronze_dir, silver_dir


def run(bronze_dir, silver_dir, minute):
    return silver.process_pending(run_ts=datetime(2026, 11, 14, 4, minute, tzinfo=timezone.utc),
                                  bronze_dir=bronze_dir, silver_dir=silver_dir)


def test_silver_is_idempotent(lake):
    bronze_dir, silver_dir = lake
    for path in (N20, N21, WX):
        shutil.copy(path, bronze_dir)
    first = run(bronze_dir, silver_dir, 0)
    assert first["status"] == "committed"
    assert set(first["outputs"]) == {"fire_detections", "weather_hourly", "rejected"}
    assert (silver_dir / "fire_detections_20261114_040000.parquet").exists()
    second = run(bronze_dir, silver_dir, 30)
    assert second["status"] == "nothing_to_do"
    assert len(list(silver_dir.glob("*.parquet"))) == 2


def test_overlapping_poll_drops_duplicates_and_keeps_revisions(lake):
    bronze_dir, silver_dir = lake
    rows = [row(latlon="4.60,-74.10"), row(latlon="4.61,-74.10")]
    bronze.write_bronze(firms_envelope(rows), "firms_viirs_noaa20_nrt", NOW, bronze_dir)
    run(bronze_dir, silver_dir, 0)
    # next poll: same first detection, revised FRP on the second, one new detection
    later = NOW.replace(hour=6)
    rows2 = [row(latlon="4.60,-74.10"), row(latlon="4.61,-74.10", frp="5.50"), row(latlon="4.62,-74.10")]
    bronze.write_bronze(firms_envelope(rows2), "firms_viirs_noaa20_nrt", later, bronze_dir)
    summary = run(bronze_dir, silver_dir, 30)
    stats = summary["files"][0]
    assert stats["duplicates_across_batches"] == 1
    assert stats["revised"] == 1
    assert summary["outputs"]["fire_detections"]["rows"] == 2


def test_orphan_silver_file_from_a_crashed_run_is_removed(lake):
    bronze_dir, silver_dir = lake
    silver_dir.mkdir()
    orphan = silver_dir / "fire_detections_20261114_010000.parquet"
    orphan.write_bytes(b"half written")
    shutil.copy(N20, bronze_dir)
    summary = run(bronze_dir, silver_dir, 0)
    assert orphan.name in summary["orphans_removed"] and not orphan.exists()


def test_silver_rows_trace_back_to_bronze_files(lake):
    bronze_dir, silver_dir = lake
    for path in (N20, N21):
        shutil.copy(path, bronze_dir)
    summary = run(bronze_dir, silver_dir, 0)
    out = silver_dir / summary["outputs"]["fire_detections"]["file"]
    try:
        frame = pd.read_parquet(out)
    except Exception:
        frame = pd.read_pickle(out)
    assert set(frame["bronze_file"]) == {N20.name, N21.name}


def test_real_parquet_file_is_readable(lake):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    bronze_dir, silver_dir = lake
    shutil.copy(N20, bronze_dir)
    summary = run(bronze_dir, silver_dir, 0)
    path = silver_dir / summary["outputs"]["fire_detections"]["file"]
    meta = json.loads(pq.read_schema(path).metadata[b"wildfire_pipeline"])
    assert meta["bronze_files"] == [N20.name]
    assert pd.read_parquet(path)["observed_at"].dt.tz is not None
