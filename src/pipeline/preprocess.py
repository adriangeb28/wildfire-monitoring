"""Silver preprocessing: from a Bronze payload to typed, validated, deduplicated rows.

Every rule below answers a problem observed in the Workshop 1 samples
(workshop_1/findings.md, report Table 3). The rule and its evidence are kept
together in the docstrings so the code can be read as the specification.

Fire detections (F3, FIRMS NRT VIIRS)
-------------------------------------
1. Text/code normalisation: strip, case-fold the coded fields (confidence
   l/n/h, satellite N20/N21, daynight D/N). There is no free text in these
   sources, so NLP steps (stop words, tokenisation) do not apply.
2. Types: numeric fields coerced to float; acq_time is HHMM *without* zero
   padding (W1: 436 night rows had 3 digits, e.g. 658 = 06:58), so it is
   padded before building ``observed_at`` as an explicit UTC timestamp.
3. Required fields (latitude, longitude, acq_date, acq_time, satellite, frp):
   a row missing any of them is quarantined, never imputed: imputing a position
   or a time would invent a detection.
4. Validation: coordinate ranges, Colombia bounding box, valid clock time,
   frp > 0 (W1: one row with frp = 0.00), no timestamp in the future.
5. Region: point-in-polygon; detections outside Colombia are quarantined with
   reason ``outside_colombia`` (W1: only 50 % of the bbox rows are Colombian).
6. Optional fields: bright_ti4/ti5 outside 200-400 K are physically
   implausible for VIIRS and set to null with a flag; null scan/track/brightness
   stay null (they do not enter the indicator); null confidence -> "unknown".
7. Confidence: l/n/h -> ordered category low < nominal < high. VIIRS gives a
   class, not a percentage (W1: ``confidence > 50`` kept 0 of 2 220 rows).
8. Outliers: FRP is heavy-tailed (W1: median 4.8 MW, max 196 MW, the max being
   a real fire seen three times). Outliers are therefore *flagged*, not removed:
   IQR fence on log10(FRP) per satellite (primary) and a z-score on log10(FRP)
   (secondary, stored for inspection).
9. Duplicates: exact duplicates on (source, satellite, lat, lon, observed_at)
   are dropped inside a batch; across batches (the 1-day polling overlap) the
   Silver state registry decides new / revised / duplicate using event_id and
   content_hash. Near-duplicates (W1: 44.5 % share a ~1 km cell) are *not*
   duplicates: they are several detections of one fire and are grouped into
   fire events later (Gold, Workshop 3).

Weather (F4, Open-Meteo forecast)
---------------------------------
Long format (one row per region, hour and variable). Physical range checks per
variable; short gaps (<= 3 consecutive hours) are linearly interpolated and
flagged ``imputed``; longer gaps stay null. Values with |z| > 4 inside the
region-variable series are flagged, not changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from io import StringIO

import numpy as np
import pandas as pd

from . import regions, settings

# ---------------------------------------------------------------------------
# Target schemas (schema enforcement)
# ---------------------------------------------------------------------------
FIRE_SCHEMA: dict[str, str] = {
    "event_id": "string",
    "source": "string",
    "product": "string",
    "satellite": "category",
    "instrument": "category",
    "observed_at": "datetime64[ns, UTC]",
    "acq_date": "datetime64[ns]",
    "latitude": "float64",
    "longitude": "float64",
    "region_id": "string",
    "region_name": "string",
    "frp": "float64",
    "bright_ti4": "float64",
    "bright_ti5": "float64",
    "scan": "float64",
    "track": "float64",
    "confidence_raw": "string",
    "confidence_level": "category",
    "daynight": "category",
    "product_version": "string",
    "frp_outlier": "bool",
    "frp_log_z": "float64",
    "quality_flags": "string",
    "content_hash": "string",
    "record_status": "string",
    "bronze_file": "string",
    "bronze_row": "int64",
    "processed_at": "datetime64[ns, UTC]",
}
FIRE_REQUIRED = ["event_id", "source", "satellite", "observed_at", "latitude", "longitude",
                 "region_id", "frp", "content_hash", "bronze_file"]

WEATHER_SCHEMA: dict[str, str] = {
    "weather_key": "string",
    "source": "string",
    "region_id": "string",
    "observed_at": "datetime64[ns, UTC]",
    "variable": "category",
    "value": "float64",
    "unit": "string",
    "is_forecast": "bool",
    "lead_hours": "float64",
    "imputed": "bool",
    "quality_flags": "string",
    "content_hash": "string",
    "record_status": "string",
    "bronze_file": "string",
    "processed_at": "datetime64[ns, UTC]",
}
WEATHER_REQUIRED = ["weather_key", "region_id", "observed_at", "variable", "content_hash", "bronze_file"]

REJECT_COLUMNS = ["source", "bronze_file", "bronze_row", "reason", "payload"]

CONFIDENCE_LEVELS = ["unknown", "low", "nominal", "high"]
CONFIDENCE_MAP = {"l": "low", "n": "nominal", "h": "high"}

WEATHER_RANGES = {  # physically plausible bounds for Colombia (sanity, not climatology)
    "temperature_2m": (-30.0, 50.0),
    "relative_humidity_2m": (0.0, 100.0),
    "precipitation": (0.0, 200.0),
    "wind_speed_10m": (0.0, 250.0),
}
MAX_GAP_HOURS = 3
Z_FLAG = 4.0


class SchemaError(ValueError):
    pass


def _hash(*parts) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def enforce_schema(frame: pd.DataFrame, schema: dict[str, str], required: list[str]) -> pd.DataFrame:
    """Cast to the target types, order the columns, fail on missing required values."""
    missing_cols = [c for c in schema if c not in frame.columns]
    if missing_cols:
        raise SchemaError(f"missing columns: {missing_cols}")
    out = frame[list(schema)].copy()
    for column, dtype in schema.items():
        if dtype.startswith("datetime64[ns, UTC]"):
            out[column] = pd.to_datetime(out[column], utc=True)
        elif dtype == "datetime64[ns]":
            out[column] = pd.to_datetime(out[column])
        else:
            out[column] = out[column].astype(dtype)
    nulls = {c: int(out[c].isna().sum()) for c in required if out[c].isna().any()}
    if nulls:
        raise SchemaError(f"required fields with nulls: {nulls}")
    return out


def _reject(rows: pd.DataFrame, reason: str, source: str) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=REJECT_COLUMNS)
    payload_cols = [c for c in rows.columns if c not in ("bronze_file", "bronze_row") and not c.startswith("_")]
    return pd.DataFrame({
        "source": source,
        "bronze_file": rows["bronze_file"].values,
        "bronze_row": rows["bronze_row"].values,
        "reason": reason,
        "payload": [json.dumps({k: (None if pd.isna(v) else str(v)) for k, v in r.items()})
                    for r in rows[payload_cols].to_dict("records")],
    })


# ---------------------------------------------------------------------------
# Fire detections
# ---------------------------------------------------------------------------
def preprocess_fires(envelope: dict, bronze_file: str,
                     now: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (clean rows, rejected rows, stats) for one FIRMS Bronze envelope."""
    now = now or datetime.now(timezone.utc)
    source = envelope["source"]
    raw = pd.read_csv(StringIO(envelope["payload"]), dtype=str, keep_default_na=False)
    raw = raw.replace({"": np.nan})
    stats = {"bronze_file": bronze_file, "rows_in": int(len(raw))}
    if raw.empty:
        stats.update(rows_clean=0, rows_rejected=0, duplicates_in_batch=0)
        return pd.DataFrame(columns=list(FIRE_SCHEMA)), pd.DataFrame(columns=REJECT_COLUMNS), stats

    df = raw.copy()
    df["bronze_file"] = bronze_file
    df["bronze_row"] = np.arange(2, len(df) + 2)        # line number in the CSV payload (header = 1)

    # 1. code normalisation
    for col, fn in (("confidence", str.lower), ("satellite", str.upper),
                    ("daynight", str.upper), ("instrument", str.upper)):
        if col in df:
            df[col] = df[col].map(lambda v, f=fn: f(v.strip()) if isinstance(v, str) else v)

    # 2. types
    for col in ("latitude", "longitude", "frp", "bright_ti4", "bright_ti5", "scan", "track"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    acq_time = pd.to_numeric(df["acq_time"], errors="coerce")
    valid_clock = acq_time.between(0, 2359) & ((acq_time % 100) < 60)
    hhmm = acq_time.where(valid_clock).astype("Int64").astype(str).str.zfill(4)
    df["observed_at"] = pd.to_datetime(
        df["acq_date"].astype(str) + " " + hhmm.str[:2] + ":" + hhmm.str[2:],
        format="%Y-%m-%d %H:%M", errors="coerce", utc=True,
    )
    df["acq_date"] = pd.to_datetime(df["acq_date"], format="%Y-%m-%d", errors="coerce")

    rejected = []
    keep = pd.Series(True, index=df.index)

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal keep
        mask = mask & keep
        if mask.any():
            rejected.append(_reject(df[mask], reason, source))
            keep &= ~mask

    # 3. required fields
    for col in ("latitude", "longitude", "acq_date", "satellite", "frp"):
        drop(df[col].isna(), f"missing_{col}")
    drop(~valid_clock | df["observed_at"].isna(), "bad_acq_time")
    # 4. validation
    drop(~df["latitude"].between(-90, 90) | ~df["longitude"].between(-180, 180), "coordinates_out_of_range")
    west, south, east, north = settings.BBOX
    drop(~df["latitude"].between(south, north) | ~df["longitude"].between(west, east), "outside_bbox")
    drop(df["frp"] <= 0, "frp_nonpositive")
    drop(df["observed_at"] > pd.Timestamp(now) + pd.Timedelta(hours=1), "future_timestamp")

    # 5. region (only for rows still valid)
    df["region_id"] = None
    df["region_name"] = None
    idx = df.index[keep]
    if len(idx):
        ids, names = regions.assign(df.loc[idx, "latitude"].to_numpy(), df.loc[idx, "longitude"].to_numpy())
        df.loc[idx, "region_id"] = ids
        df.loc[idx, "region_name"] = names
    drop(df["region_id"].isna(), "outside_colombia")

    df = df[keep].copy()
    flags: list[list[str]] = [[] for _ in range(len(df))]

    # 6. optional fields
    for col in ("bright_ti4", "bright_ti5"):
        bad = df[col].notna() & ~df[col].between(200, 400)
        for pos in np.nonzero(bad.to_numpy())[0]:
            flags[pos].append(f"{col}_implausible")
        df.loc[bad, col] = np.nan

    # 7. confidence
    df["confidence_raw"] = df["confidence"]
    df["confidence_level"] = pd.Categorical(
        df["confidence"].map(CONFIDENCE_MAP).fillna("unknown"),
        categories=CONFIDENCE_LEVELS, ordered=True,
    )
    df["daynight"] = df["daynight"].fillna("U")
    df["instrument"] = df["instrument"].fillna("VIIRS")
    df["product_version"] = df.get("version", pd.Series(index=df.index, dtype=object)).fillna("unknown")

    # 8. outliers on log10(FRP), per satellite
    log_frp = np.log10(df["frp"])
    df["frp_outlier"] = False
    df["frp_log_z"] = np.nan
    for _, group in log_frp.groupby(df["satellite"]):
        if len(group) < 20:              # too few points for a stable fence
            continue
        q1, q3 = group.quantile([0.25, 0.75])
        fence = q3 + 1.5 * (q3 - q1)
        df.loc[group.index, "frp_outlier"] = group > fence
        std = group.std(ddof=0)
        if std > 0:
            df.loc[group.index, "frp_log_z"] = (group - group.mean()) / std
    for pos in np.nonzero(df["frp_outlier"].to_numpy())[0]:
        flags[pos].append("frp_outlier_iqr")

    # 9. keys and within-batch duplicates
    df["source"] = source
    df["product"] = envelope["product"]
    iso = df["observed_at"].dt.strftime("%Y-%m-%dT%H:%MZ")
    df["event_id"] = [
        _hash(source, sat, f"{lat:.5f}", f"{lon:.5f}", t)[:32]
        for sat, lat, lon, t in zip(df["satellite"], df["latitude"], df["longitude"], iso)
    ]
    df["content_hash"] = [
        _hash(*vals) for vals in zip(df["frp"], df["bright_ti4"], df["bright_ti5"],
                                     df["confidence_raw"], df["scan"], df["track"], df["product_version"])
    ]
    df["quality_flags"] = [";".join(f) for f in flags]
    before = len(df)
    df = df.drop_duplicates(subset="event_id", keep="first")
    stats["duplicates_in_batch"] = before - len(df)

    df["record_status"] = "new"          # final value set by the Silver registry
    df["processed_at"] = pd.Timestamp(now)

    clean = enforce_schema(df, FIRE_SCHEMA, FIRE_REQUIRED)
    rejects = pd.concat(rejected, ignore_index=True) if rejected else pd.DataFrame(columns=REJECT_COLUMNS)
    stats.update(rows_clean=int(len(clean)), rows_rejected=int(len(rejects)),
                 rejected_by_reason=rejects["reason"].value_counts().to_dict() if len(rejects) else {},
                 frp_outliers=int(clean["frp_outlier"].sum()))
    return clean, rejects, stats


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def preprocess_weather(envelope: dict, bronze_file: str,
                       now: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (clean long-format rows, rejected rows, stats) for one Open-Meteo envelope."""
    now = now or datetime.now(timezone.utc)
    body = json.loads(envelope["payload"])
    blocks = body if isinstance(body, list) else [body]
    order = envelope.get("extra", {}).get("region_order") or [f"block_{i}" for i in range(len(blocks))]
    fetched_at = pd.Timestamp(envelope.get("fetched_at") or now)

    frames = []
    for region_id, block in zip(order, blocks):
        hourly = block.get("hourly", {})
        units = block.get("hourly_units", {})
        times = pd.to_datetime(hourly.get("time", []), utc=True)
        for variable in settings.OPEN_METEO_HOURLY:
            values = hourly.get(variable)
            if values is None:
                continue
            frames.append(pd.DataFrame({
                "region_id": region_id, "observed_at": times, "variable": variable,
                "value": pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce").to_numpy(),
                "unit": units.get(variable, ""),
            }))
    stats = {"bronze_file": bronze_file, "rows_in": int(sum(len(f) for f in frames))}
    if not frames:
        stats.update(rows_clean=0, rows_rejected=0, imputed=0, duplicates_in_batch=0)
        return pd.DataFrame(columns=list(WEATHER_SCHEMA)), pd.DataFrame(columns=REJECT_COLUMNS), stats

    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(subset=["region_id", "observed_at", "variable"], keep="last")
    stats["duplicates_in_batch"] = before - len(df)
    df = df.sort_values(["region_id", "variable", "observed_at"]).reset_index(drop=True)
    flags = pd.Series("", index=df.index)

    # physical ranges -> null + flag (then eligible for gap filling)
    for variable, (low, high) in WEATHER_RANGES.items():
        bad = (df["variable"] == variable) & df["value"].notna() & ~df["value"].between(low, high)
        df.loc[bad, "value"] = np.nan
        flags[bad] = "out_of_range"

    # short gaps: linear interpolation inside each series, flagged
    df["imputed"] = False
    for _, idx in df.groupby(["region_id", "variable"]).groups.items():
        series = df.loc[idx, "value"]
        if not series.isna().any():
            continue
        filled = series.interpolate(limit=MAX_GAP_HOURS, limit_area="inside")
        # only fill runs that are entirely <= MAX_GAP_HOURS long
        run_id = series.notna().cumsum()
        run_len = series.isna().groupby(run_id).transform("sum")
        ok = series.isna() & filled.notna() & (run_len <= MAX_GAP_HOURS)
        df.loc[ok[ok].index, "value"] = filled[ok]
        df.loc[ok[ok].index, "imputed"] = True
    still_null = df["value"].isna()
    flags[still_null] = (flags[still_null] + ";missing").str.strip(";")

    # z-score flag per series (not for precipitation: zero-inflated)
    for (_, variable), idx in df.groupby(["region_id", "variable"]).groups.items():
        if variable == "precipitation":
            continue
        values = df.loc[idx, "value"]
        std = values.std(ddof=0)
        if std and std > 0:
            z = (values - values.mean()) / std
            hit = z.abs() > Z_FLAG
            flags[hit[hit].index] = (flags[hit[hit].index] + ";zscore_gt4").str.strip(";")

    df["quality_flags"] = flags
    df["source"] = envelope["source"]
    df["is_forecast"] = df["observed_at"] > fetched_at
    df["lead_hours"] = (df["observed_at"] - fetched_at).dt.total_seconds() / 3600.0
    iso = df["observed_at"].dt.strftime("%Y-%m-%dT%H:%MZ")
    df["weather_key"] = [_hash(envelope["source"], r, t, v)[:32]
                         for r, t, v in zip(df["region_id"], iso, df["variable"])]
    df["content_hash"] = [_hash(v) for v in df["value"]]
    df["record_status"] = "new"
    df["bronze_file"] = bronze_file
    df["processed_at"] = pd.Timestamp(now)

    clean = enforce_schema(df, WEATHER_SCHEMA, WEATHER_REQUIRED)
    stats.update(rows_clean=int(len(clean)), rows_rejected=0,
                 imputed=int(clean["imputed"].sum()), missing=int(clean["value"].isna().sum()))
    return clean, pd.DataFrame(columns=REJECT_COLUMNS), stats
