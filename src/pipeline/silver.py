"""Silver layer: detect new Bronze files, preprocess them, persist Parquet.

State registry (SQLite, datalake_silver/_state/silver_state.sqlite)
------------------------------------------------------------------
bronze_file   every Bronze file already processed (name, sha256, status, run)
record_key    every record key seen (event_id / weather_key) with its last
              content_hash -> decides new / revised / duplicate across batches
silver_file   every Parquet file the pipeline committed

Idempotency and failure safety
------------------------------
* A Bronze file is processed once; re-running finds nothing new and writes nothing.
* A record already seen with the same content_hash is dropped (duplicate from
  the polling overlap); with a different hash it is kept as ``revised``.
* Parquet files are written first (temp name + rename), then the registry is
  committed in one transaction. On start-up, Parquet files that the registry
  does not know (left by a run that died before its commit) are removed, so a
  crash can never leave duplicated rows in Silver.

File names: ``<topic>_YYYYMMDD_HHMMSS.parquet`` with the processing-run time
(UTC). Topics: ``fire_detections``, ``weather_hourly``; rejected rows go to
``_quarantine/rejected_YYYYMMDD_HHMMSS.parquet``. Every row carries
``bronze_file``, and the Parquet schema metadata lists the Bronze files of the
run, so each Silver file is traceable to its sources.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import bronze, preprocess, settings

log = settings.get_logger(__name__)

PIPELINE_VERSION = "w2-0.1"
TOPICS = {"firms_nrt_viirs": "fire_detections", "firms_archive": "fire_detections",
          "open_meteo_forecast": "weather_hourly"}
KEY_COLUMN = {"fire_detections": "event_id", "weather_hourly": "weather_key"}
SCHEMAS = {"fire_detections": (preprocess.FIRE_SCHEMA, preprocess.FIRE_REQUIRED),
           "weather_hourly": (preprocess.WEATHER_SCHEMA, preprocess.WEATHER_REQUIRED)}
UNITS = {"fire_detections": {"frp": "MW", "bright_ti4": "K", "bright_ti5": "K",
                             "latitude": "deg WGS84", "longitude": "deg WGS84", "observed_at": "UTC"},
         "weather_hourly": {"value": "see unit column", "observed_at": "UTC"}}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bronze_file (
    name TEXT PRIMARY KEY, sha256 TEXT NOT NULL, source TEXT, status TEXT NOT NULL,
    rows_in INTEGER, rows_clean INTEGER, rows_rejected INTEGER, run_ts TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS record_key (
    topic TEXT NOT NULL, key TEXT NOT NULL, content_hash TEXT NOT NULL,
    first_file TEXT NOT NULL, last_file TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (topic, key));
CREATE TABLE IF NOT EXISTS silver_file (
    name TEXT PRIMARY KEY, topic TEXT NOT NULL, rows INTEGER NOT NULL, run_ts TEXT NOT NULL,
    bronze_files TEXT NOT NULL);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or settings.STATE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA_SQL)
    return con


def cleanup_orphans(con: sqlite3.Connection, silver_dir: Path | None = None) -> list[str]:
    """Remove Parquet files that no committed run produced (crash between write and commit)."""
    silver_dir = silver_dir or settings.SILVER_DIR
    known = {row[0] for row in con.execute("SELECT name FROM silver_file")}
    removed = []
    for path in list(silver_dir.glob("*.parquet")) + list((silver_dir / "_quarantine").glob("*.parquet")):
        if path.name not in known:
            path.unlink()
            removed.append(path.name)
            log.warning("removed orphan silver file %s (its run never committed)", path.name)
    for tmp in silver_dir.rglob(".*.tmp"):
        tmp.unlink()
    return removed


def pending_bronze_files(con: sqlite3.Connection, bronze_dir: Path | None = None) -> list[Path]:
    """Bronze files not yet processed (or whose content changed since)."""
    bronze_dir = bronze_dir or settings.BRONZE_DIR
    done = dict(con.execute("SELECT name, sha256 FROM bronze_file"))
    pending = []
    for path in sorted(bronze_dir.glob("*.json")):
        if path.name not in done:
            pending.append(path)
            continue
        try:
            sha = json.loads(path.read_text(encoding="utf-8")).get("payload_sha256")
        except (OSError, json.JSONDecodeError):
            continue
        if sha != done[path.name]:          # same interval re-ingested with new content
            pending.append(path)
    return pending


def _classify(con: sqlite3.Connection, topic: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Set record_status new / revised and drop cross-batch duplicates."""
    if frame.empty:
        return frame
    key_col = KEY_COLUMN[topic]
    keys = frame[key_col].tolist()
    known: dict[str, str] = {}
    for start in range(0, len(keys), 900):
        chunk = keys[start:start + 900]
        marks = ",".join("?" * len(chunk))
        known.update(con.execute(
            f"SELECT key, content_hash FROM record_key WHERE topic=? AND key IN ({marks})",
            [topic, *chunk]))
    previous = frame[key_col].map(known)
    status = pd.Series("new", index=frame.index)
    status[previous.notna() & (previous != frame["content_hash"])] = "revised"
    status[previous.notna() & (previous == frame["content_hash"])] = "duplicate"
    frame = frame.assign(record_status=status.astype("string"))
    return frame[frame["record_status"] != "duplicate"]


def _write_parquet(frame: pd.DataFrame, path: Path, metadata: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(frame, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta[b"wildfire_pipeline"] = json.dumps(metadata).encode()
    table = table.replace_schema_metadata(meta)
    tmp = path.with_name(f".{path.name}.tmp")
    pq.write_table(table, tmp, compression="snappy")
    os.replace(tmp, path)


def process_pending(run_ts: datetime | None = None, bronze_dir: Path | None = None,
                    silver_dir: Path | None = None, state_db: Path | None = None) -> dict:
    """Process every pending Bronze file. Returns a run summary (also logged)."""
    run_ts = (run_ts or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = run_ts.strftime("%Y%m%d_%H%M%S")
    bronze_dir = bronze_dir or settings.BRONZE_DIR
    silver_dir = silver_dir or settings.SILVER_DIR
    quarantine_dir = silver_dir / "_quarantine"
    silver_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {"run_ts": run_ts.isoformat(), "files": [], "outputs": {}, "status": "nothing_to_do"}
    with closing(connect(state_db or silver_dir / "_state" / "silver_state.sqlite")) as con:
        summary["orphans_removed"] = cleanup_orphans(con, silver_dir)
        pending = pending_bronze_files(con, bronze_dir)
        if not pending:
            log.info("no new bronze files")
            return summary

        by_topic: dict[str, list[pd.DataFrame]] = {t: [] for t in TOPICS.values()}
        rejected: list[pd.DataFrame] = []
        file_rows = []
        for path in pending:
            try:
                envelope = bronze.read_bronze(path)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                log.error("cannot read %s: %s", path.name, exc)
                file_rows.append((path.name, "", None, "unreadable", 0, 0, 0, str(exc)))
                continue
            source = envelope["source"]
            if not envelope["validation"].get("ok", False):
                log.warning("%s failed the bronze schema check: %s", path.name, envelope["validation"])
                file_rows.append((path.name, envelope["payload_sha256"], source, "invalid",
                                  envelope["record_count"], 0, 0, json.dumps(envelope["validation"])))
                continue
            if source in ("firms_nrt_viirs", "firms_archive"):
                clean, rej, stats = preprocess.preprocess_fires(envelope, path.name, now=run_ts)
            elif source == "open_meteo_forecast":
                clean, rej, stats = preprocess.preprocess_weather(envelope, path.name, now=run_ts)
            else:
                log.error("%s: unknown source %s", path.name, source)
                continue
            topic = TOPICS[source]
            before = len(clean)
            clean = _classify(con, topic, clean)
            stats["duplicates_across_batches"] = before - len(clean)
            stats["revised"] = int((clean["record_status"] == "revised").sum()) if len(clean) else 0
            by_topic[topic].append(clean)
            rejected.append(rej)
            file_rows.append((path.name, envelope["payload_sha256"], source, "processed",
                              stats["rows_in"], len(clean), stats["rows_rejected"], json.dumps(stats, default=str)))
            summary["files"].append(stats)
            log.info("processed %s: %s", path.name, stats)

        written = []
        for topic, frames in by_topic.items():
            frames = [f for f in frames if len(f)]
            if not frames:
                continue
            frame = pd.concat(frames, ignore_index=True)
            # the same key may appear in two bronze files of this run: keep the latest
            frame = frame.drop_duplicates(subset=KEY_COLUMN[topic], keep="last")
            schema, required = SCHEMAS[topic]
            frame = preprocess.enforce_schema(frame, schema, required)   # concat can loosen dtypes
            sources = sorted(frame["bronze_file"].unique())
            target = silver_dir / f"{topic}_{stamp}.parquet"
            _write_parquet(frame, target, {"topic": topic, "run_ts": run_ts.isoformat(),
                                           "pipeline_version": PIPELINE_VERSION,
                                           "bronze_files": sources, "units": UNITS[topic]})
            written.append((target.name, topic, len(frame), run_ts.isoformat(), json.dumps(sources), frame))
            summary["outputs"][topic] = {"file": target.name, "rows": len(frame)}

        rejected = [r for r in rejected if len(r)]
        if rejected:
            frame = pd.concat(rejected, ignore_index=True)
            target = quarantine_dir / f"rejected_{stamp}.parquet"
            _write_parquet(frame, target, {"topic": "rejected", "run_ts": run_ts.isoformat(),
                                           "bronze_files": sorted(frame["bronze_file"].unique())})
            written.append((target.name, "rejected", len(frame), run_ts.isoformat(),
                            json.dumps(sorted(frame["bronze_file"].unique())), None))
            summary["outputs"]["rejected"] = {"file": target.name, "rows": len(frame),
                                              "by_reason": frame["reason"].value_counts().to_dict()}

        # single commit: files are already on disk, the registry now acknowledges them
        with con:
            for name, topic, rows, ts, sources, frame in written:
                con.execute("INSERT OR REPLACE INTO silver_file VALUES (?,?,?,?,?)", (name, topic, rows, ts, sources))
                if frame is not None:
                    key_col = KEY_COLUMN[topic]
                    con.executemany(
                        """INSERT INTO record_key VALUES (?,?,?,?,?,?)
                           ON CONFLICT(topic, key) DO UPDATE SET content_hash=excluded.content_hash,
                           last_file=excluded.last_file, updated_at=excluded.updated_at""",
                        [(topic, k, h, name, name, ts) for k, h in zip(frame[key_col], frame["content_hash"])])
            con.executemany("INSERT OR REPLACE INTO bronze_file VALUES (?,?,?,?,?,?,?,?,?)",
                            [(*row[:7], run_ts.isoformat(), row[7]) for row in file_rows])

        with (silver_dir / "_manifest.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: v for k, v in summary.items() if k != "files"} |
                                {"bronze_files": [r[0] for r in file_rows]}, default=str) + "\n")
        summary["status"] = "committed"
        log.info("silver run %s committed: %s", stamp, summary["outputs"])
    return summary


def status(state_db: Path | None = None) -> dict:
    with closing(connect(state_db)) as con:
        return {
            "bronze_files": dict(con.execute("SELECT status, COUNT(*) FROM bronze_file GROUP BY status")),
            "silver_files": dict(con.execute("SELECT topic, COUNT(*) FROM silver_file GROUP BY topic")),
            "silver_rows": dict(con.execute("SELECT topic, SUM(rows) FROM silver_file GROUP BY topic")),
            "record_keys": dict(con.execute("SELECT topic, COUNT(*) FROM record_key GROUP BY topic")),
            "last_run": con.execute("SELECT MAX(run_ts) FROM silver_file").fetchone()[0],
        }
