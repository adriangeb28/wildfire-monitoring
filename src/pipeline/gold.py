from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType
from pyspark.sql.window import Window


def _resolve_datalake_dirs() -> tuple[Path, Path]:
    base_dir = Path(__file__).resolve().parents[2]
    silver_dir = Path(os.getenv("DATALAKE_SILVER", base_dir / "datalake_silver"))
    gold_dir = Path(os.getenv("DATALAKE_GOLD", base_dir / "datalake_gold"))
    return silver_dir, gold_dir


def get_spark(app_name: str = "wildfire_silver_to_gold") -> SparkSession:
    spark = (
        SparkSession.builder
        .master("local[*]")
        .appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.parquet.mergeSchema", "true")
        .config("spark.sql.parquet.int96AsTimestamp", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def _read_silver_parquet_spark(
    spark: SparkSession,
    files: list[Path],
    staging_dir: Path,
    prefix: str,
) -> DataFrame:
    stage_subdir = staging_dir / prefix
    stage_subdir.mkdir(parents=True, exist_ok=True)
    for idx, fpath in enumerate(files):
        table = pq.read_table(fpath)
        new_fields = []
        new_cols = []
        for field, col in zip(table.schema, table.columns):
            if pa.types.is_dictionary(field.type):
                val_type = field.type.value_type
                col = col.cast(val_type)
                field = pa.field(field.name, val_type, nullable=field.nullable)
            if pa.types.is_timestamp(field.type):
                target_type = pa.timestamp("us", tz=field.type.tz)
                new_fields.append(pa.field(field.name, target_type, nullable=field.nullable))
                new_cols.append(col.cast(target_type, safe=False))
            elif pa.types.is_null(field.type):
                new_fields.append(pa.field(field.name, pa.string(), nullable=True))
                new_cols.append(col.cast(pa.string()))
            else:
                new_fields.append(field)
                new_cols.append(col)
        norm_table = pa.Table.from_arrays(new_cols, schema=pa.schema(new_fields))
        pq.write_table(
            norm_table,
            stage_subdir / f"part_{idx:03d}.parquet",
            coerce_timestamps="us",
            allow_truncated_timestamps=True,
        )
    return spark.read.parquet(str(stage_subdir / "part_*.parquet"))


def build_governance_df(
    spark: SparkSession,
    df_fires: DataFrame,
    df_weather: DataFrame,
    df_quarantine: DataFrame | None,
    run_ts: datetime,
) -> DataFrame:
    ts_str = run_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_str = run_ts.strftime("%Y-%m-%d")
    rows: list[tuple[str, str, str, str, str, float, str]] = []

    fire_cols = set(df_fires.columns)
    outlier_expr = (
        F.when(F.col("frp_outlier").cast("boolean") == F.lit(True), 1).otherwise(0)
        if "frp_outlier" in fire_cols
        else F.lit(0)
    )
    revised_expr = (
        F.when(F.col("record_status") == "revised", 1).otherwise(0)
        if "record_status" in fire_cols
        else F.lit(0)
    )
    clean_flag_expr = (
        F.when(F.coalesce(F.col("quality_flags").cast("string"), F.lit("")) == "", 1).otherwise(0)
        if "quality_flags" in fire_cols
        else F.lit(1)
    )

    if "processed_at" in fire_cols and "observed_at" in fire_cols:
        latency_expr = F.expr(
            "percentile_approx((unix_timestamp(processed_at) - unix_timestamp(observed_at)) / 3600.0, 0.5)"
        )
    elif "ingested_at" in fire_cols and "observed_at" in fire_cols:
        latency_expr = F.expr(
            "percentile_approx((unix_timestamp(ingested_at) - unix_timestamp(observed_at)) / 3600.0, 0.5)"
        )
    else:
        latency_expr = F.lit(0.0)

    fire_vol = (
        df_fires.withColumn("metric_date", F.to_date("observed_at"))
        .groupBy("metric_date", "satellite")
        .agg(
            F.count("*").cast("double").alias("kpi_value"),
            F.sum(outlier_expr).cast("double").alias("outlier_cnt"),
            F.sum(revised_expr).cast("double").alias("revised_cnt"),
            F.sum(clean_flag_expr).cast("double").alias("clean_flag_cnt"),
            latency_expr.cast("double").alias("median_latency_hours"),
        )
        .collect()
    )

    for r in fire_vol:
        mdate = str(r["metric_date"])
        sat = str(r["satellite"])
        total = float(r["kpi_value"] or 0.0)
        denom = total if total > 0 else 1.0
        rows.append((ts_str, mdate, "firms_nrt", sat, "valid_ingestion_volume", total, "records"))
        rows.append((ts_str, mdate, "firms_nrt", sat, "frp_outlier_rate_pct", round(100.0 * float(r["outlier_cnt"] or 0.0) / denom, 4), "percent"))
        rows.append((ts_str, mdate, "firms_nrt", sat, "revision_rate_pct", round(100.0 * float(r["revised_cnt"] or 0.0) / denom, 4), "percent"))
        rows.append((ts_str, mdate, "firms_nrt", sat, "schema_compliance_rate_pct", round(100.0 * float(r["clean_flag_cnt"] or 0.0) / denom, 4), "percent"))
        rows.append((ts_str, mdate, "firms_nrt", sat, "median_ingestion_latency_h", round(float(r["median_latency_hours"] or 0.0), 2), "hours"))

    if df_quarantine is not None and df_quarantine.head(1):
        q_df = df_quarantine
        if "source" not in q_df.columns:
            q_df = q_df.withColumn("source", F.lit("firms_nrt"))
        q_counts = q_df.groupBy("source", "reason").count().collect()
        total_valid = df_fires.count()
        total_rej = sum(int(r["count"]) for r in q_counts)
        denom = float(max(total_valid + total_rej, 1))
        for r in q_counts:
            rows.append((
                ts_str,
                today_str,
                str(r["source"]),
                str(r["reason"]),
                "quarantine_rejection_rate_pct",
                round(100.0 * float(r["count"]) / denom, 4),
                "percent",
            ))

    fire_total = float(max(df_fires.count(), 1))
    for col_name in ["frp", "bright_ti4", "bright_ti5", "scan", "track"]:
        if col_name in fire_cols:
            null_cnt = df_fires.filter(F.col(col_name).isNull()).count()
            rows.append((ts_str, today_str, "firms_nrt", col_name, "null_rate_pct", round(100.0 * float(null_cnt) / fire_total, 4), "percent"))

    weather_cols = set(df_weather.columns)
    imp_expr = (
        F.when(F.col("imputed").cast("boolean") == F.lit(True), 1).otherwise(0)
        if "imputed" in weather_cols
        else F.lit(0)
    )
    z_expr = (
        F.when(F.coalesce(F.col("quality_flags").cast("string"), F.lit("")).contains("zscore_gt4"), 1).otherwise(0)
        if "quality_flags" in weather_cols
        else F.lit(0)
    )

    weather_stats = (
        df_weather.groupBy("variable")
        .agg(
            F.count("*").alias("n"),
            F.sum(F.when(F.col("value").isNull(), 1).otherwise(0)).alias("null_n"),
            F.sum(imp_expr).alias("imp_n"),
            F.sum(z_expr).alias("z_n"),
        )
        .collect()
    )
    for r in weather_stats:
        var = str(r["variable"])
        n = float(max(int(r["n"]), 1))
        rows.append((ts_str, today_str, "open_meteo", var, "null_rate_pct", round(100.0 * float(r["null_n"] or 0.0) / n, 4), "percent"))
        rows.append((ts_str, today_str, "open_meteo", var, "imputation_rate_pct", round(100.0 * float(r["imp_n"] or 0.0) / n, 4), "percent"))
        rows.append((ts_str, today_str, "open_meteo", var, "extreme_zscore_rate_pct", round(100.0 * float(r["z_n"] or 0.0) / n, 4), "percent"))

    gov_schema = StructType([
        StructField("generated_at", StringType(), False),
        StructField("metric_date", StringType(), False),
        StructField("source", StringType(), False),
        StructField("dimension", StringType(), False),
        StructField("kpi_name", StringType(), False),
        StructField("kpi_value", DoubleType(), False),
        StructField("unit", StringType(), False),
    ])
    return spark.createDataFrame(rows, schema=gov_schema)


def build_storytelling_df(
    df_fires: DataFrame,
    df_weather: DataFrame,
    run_ts: datetime,
) -> DataFrame:
    ts_str = run_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    fires_clustered = (
        df_fires.withColumn("metric_date", F.to_date("observed_at"))
        .withColumn("grid_cell", F.concat_ws("_", F.round("latitude", 2), F.round("longitude", 2)))
    )

    fire_daily = (
        fires_clustered.groupBy("metric_date", "region_id", "region_name")
        .agg(
            F.count("*").alias("detection_count"),
            F.countDistinct("grid_cell").alias("fire_event_count"),
            F.round(F.sum("frp"), 2).alias("total_frp_mw"),
            F.round(F.avg("frp"), 2).alias("mean_frp_mw"),
            F.round(F.max("frp"), 2).alias("max_frp_mw"),
            F.sum(F.when(F.col("confidence_level") == "high", 1).otherwise(0)).alias("high_conf_count"),
            F.sum(F.when(F.col("confidence_level") == "nominal", 1).otherwise(0)).alias("nominal_conf_count"),
            F.sum(F.when(F.col("daynight") == "D", 1).otherwise(0)).alias("day_count"),
            F.sum(F.when(F.col("daynight") == "N", 1).otherwise(0)).alias("night_count"),
            F.sum(F.when(F.col("satellite") == "N20", 1).otherwise(0)).alias("noaa20_count"),
            F.sum(F.when(F.col("satellite") == "N21", 1).otherwise(0)).alias("noaa21_count"),
            F.max("observed_at").alias("last_observed_at"),
        )
    )

    weather_daily = (
        df_weather.withColumn("metric_date", F.to_date("observed_at"))
        .groupBy("metric_date", "region_id")
        .agg(
            F.round(F.max(F.when(F.col("variable") == "temperature_2m", F.col("value"))), 2).alias("temp_max_c"),
            F.round(F.min(F.when(F.col("variable") == "relative_humidity_2m", F.col("value"))), 2).alias("rh_min_pct"),
            F.round(F.sum(F.when(F.col("variable") == "precipitation", F.col("value"))), 2).alias("precip_daily_mm"),
            F.round(F.max(F.when(F.col("variable") == "wind_speed_10m", F.col("value"))), 2).alias("wind_max_kmh"),
        )
    )

    joined = fire_daily.join(weather_daily, on=["metric_date", "region_id"], how="left")

    expected_expr = F.greatest(
        F.lit(1.0),
        (F.coalesce(F.col("temp_max_c"), F.lit(28.0)) / F.lit(10.0))
        * (F.lit(1.0) + F.coalesce(F.col("wind_max_kmh"), F.lit(5.0)) / F.lit(20.0))
        / (F.lit(1.0) + F.coalesce(F.col("precip_daily_mm"), F.lit(0.0)) / F.lit(5.0)),
    )

    w_rank = Window.partitionBy("metric_date").orderBy(F.desc("anomaly_ratio"), F.desc("total_frp_mw"))

    return (
        joined.withColumn("expected_detections", F.round(expected_expr, 2))
        .withColumn("anomaly_ratio", F.round(F.col("detection_count") / F.col("expected_detections"), 2))
        .withColumn(
            "anomaly_level",
            F.when(F.col("anomaly_ratio") < 0.5, "Very low")
            .when(F.col("anomaly_ratio") < 0.9, "Low")
            .when(F.col("anomaly_ratio") < 1.5, "Normal")
            .when(F.col("anomaly_ratio") < 3.0, "Elevated")
            .otherwise("Extreme"),
        )
        .withColumn("daily_severity_rank", F.dense_rank().over(w_rank))
        .withColumn("generated_at", F.lit(ts_str))
    )


def run_gold_pipeline(run_ts: datetime | None = None) -> dict:
    run_ts = run_ts or datetime.now(timezone.utc)
    stamp = run_ts.strftime("%Y%m%d_%H%M%S")
    silver_dir, gold_dir = _resolve_datalake_dirs()
    gold_dir.mkdir(parents=True, exist_ok=True)

    fire_files = sorted(silver_dir.glob("fire_detections_*.parquet"))
    weather_files = sorted(silver_dir.glob("weather_hourly_*.parquet"))
    quarantine_files = sorted((silver_dir / "_quarantine").glob("rejected_*.parquet"))

    spark = get_spark()
    try:
        with tempfile.TemporaryDirectory(prefix="spark_silver_stage_") as tmp:
            stage_path = Path(tmp)
            df_fires = _read_silver_parquet_spark(spark, fire_files, stage_path, "fires")
            df_weather = _read_silver_parquet_spark(spark, weather_files, stage_path, "weather")
            df_quarantine = (
                _read_silver_parquet_spark(spark, quarantine_files, stage_path, "quarantine")
                if quarantine_files
                else None
            )

            gov_df = build_governance_df(spark, df_fires, df_weather, df_quarantine, run_ts)
            story_df = build_storytelling_df(df_fires, df_weather, run_ts)

            gov_path = gold_dir / f"governance_{stamp}.parquet"
            story_path = gold_dir / f"storytelling_{stamp}.parquet"

            gov_pdf = gov_df.toPandas()
            story_pdf = story_df.toPandas()
            gov_pdf.to_parquet(gov_path, index=False, coerce_timestamps="us", allow_truncated_timestamps=True)
            story_pdf.to_parquet(story_path, index=False, coerce_timestamps="us", allow_truncated_timestamps=True)

            return {
                "status": "committed",
                "governance_file": gov_path.name,
                "governance_rows": int(len(gov_pdf)),
                "storytelling_file": story_path.name,
                "storytelling_rows": int(len(story_pdf)),
            }
    finally:
        spark.stop()